"""The voice path, tested without a model, a microphone or the voice container.

Every test here runs in a bare venv. That is not a convenience — it is the same property
m16's graders have and for the same reason: the voice service is 820 MB and profiled out of
`docker compose up` by default, so a test suite that needed it would be a test suite that
gets skipped on every machine that has not opted in.

What is asserted is the logic this milestone actually wrote: where a sentence is split for
early synthesis, which stages count toward time-to-first-audio, that an unmeasured stage
reports null rather than zero, and that a missing voice container is a 503 rather than a
crash. The MODELS are measured in docs/voice-latency.md, by hand, with the host load beside
every figure — because M-21, M-35, M-48 and now the TTS stage itself all say a latency
number from this stack means nothing without it.
"""

import json

import httpx
import pytest

from services.voice import pipeline
from services.voice.settings import BUDGET_MS, STAGES, settings_snapshot


# ── splitting for early synthesis ───────────────────────────────────────────


def test_the_opening_sentence_is_split_from_the_rest():
    opening, rest = pipeline.first_sentence(
        "Business Bay recorded 10,669 transactions in the period. "
        "The median sale price was AED 1.33 million."
    )
    assert opening == "Business Bay recorded 10,669 transactions in the period."
    assert rest.startswith("The median")


def test_a_short_opening_is_not_split_off():
    """"AED 120,000." is not worth speaking alone.

    An opening too short to cover the synthesis of what follows buys no perceived latency
    and adds a seam a listener can hear. Below `min_chars` the whole answer is spoken,
    which is the behaviour without the lever — never a truncated one.
    """
    text = "AED 120,000. That is the median annual rent per property in the area."
    opening, rest = pipeline.first_sentence(text)
    assert opening == text.strip()
    assert rest == ""


def test_a_single_sentence_returns_itself_and_nothing():
    opening, rest = pipeline.first_sentence("There were 10,669 transactions in Business Bay.")
    assert rest == ""
    assert opening.endswith(".")


def test_an_abbreviation_does_not_split_the_sentence():
    # The split requires whitespace then a capital or digit, so "approx. 10" does not
    # end a sentence. Erring toward not splitting is the safe direction.
    opening, rest = pipeline.first_sentence(
        "The area saw approx. 10,669 transactions over the period recorded."
    )
    assert rest == ""


def test_empty_input_is_not_an_error():
    assert pipeline.first_sentence("") == ("", "")


# ── the budget as data ──────────────────────────────────────────────────────


def test_every_stage_target_carries_its_provenance():
    """A target from a measurement and a target from a plan deserve different confidence.

    Three of the five come from figures this project measured on this machine; two come
    from §7.2. A budget that does not distinguish them invites a reader to trust all of
    them equally.
    """
    for stage in STAGES:
        assert stage.source.strip(), stage.name
        assert stage.target_ms > 0


def test_an_unmeasured_stage_reports_null_not_zero():
    # `$0.00` and `null` are different facts in this repository, and so are milliseconds.
    # Zero claims the stage was instant; null says nobody has run it.
    verdicts = {v["stage"]: v for v in pipeline.stage_verdicts({})}
    assert verdicts["stt"]["measured_ms"] is None
    assert verdicts["stt"]["within_target"] is None
    assert verdicts["stt"]["over_by_ms"] is None


def test_a_measured_stage_reports_its_distance_from_target():
    verdicts = {v["stage"]: v for v in pipeline.stage_verdicts({"stt": 400.0})}
    assert verdicts["stt"]["measured_ms"] == 400.0
    assert verdicts["stt"]["over_by_ms"] == 150.0
    assert verdicts["stt"]["within_target"] is False


def test_the_declared_targets_already_exceed_the_budget():
    """§7.2's own table sums to more than §7.2's own budget, and that is the finding.

    1,320 ms of targets against an 800 ms budget. The plan says so in prose; asserting it
    means the arithmetic cannot drift out of agreement with the prose without a test going
    red.
    """
    snapshot = settings_snapshot()
    assert snapshot["target_total_ms"] > snapshot["budget_ms"]
    assert snapshot["target_total_ms"] == 1320
    assert snapshot["budget_ms"] == 800


def test_the_voice_path_does_not_rerank():
    # Not a latency sacrifice. m16 measured the cross-encoder at 8/20 top-1 against
    # dense's 17/20 while costing 2.9 s: it loses on both axes, so skipping it is free.
    assert settings_snapshot()["rerank_on_voice_path"] is False


# ── the turn, against a scripted voice service ──────────────────────────────


def _scripted(*, transcript="how many transactions in business bay", endpoint_ms=3340,
              stt_cold=False, tts_cold=False):
    """A voice service that answers instantly, so the LOGIC can be tested at all.

    The real thing is 820 MB and its timings are the subject of a separate, manual
    measurement. What this exercises is what the pipeline does with the numbers.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/vad":
            return httpx.Response(200, json={
                "frames": 202, "speech_frames": 167, "speech_ratio": 0.83,
                "endpoint_ms": endpoint_ms, "took_ms": 0.35,
            })
        if request.url.path == "/stt":
            return httpx.Response(200, json={
                "text": transcript, "language": "en", "audio_ms": 3440,
                "took_ms": 400.0, "realtime_factor": 0.116, "model": "base.en",
                "cold": stt_cold,
            })
        if request.url.path == "/tts":
            return httpx.Response(200, content=b"\x00\x01" * 800, headers={
                "X-Took-Ms": "450.0", "X-First-Chunk-Ms": "440.0",
                "X-Audio-Ms": "3400", "X-Sample-Rate": "22050",
                "X-Cold": "true" if tts_cold else "false",
            })
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _Reply:
    def __init__(self, answer, answered=True, retrieve=200, generate=2000):
        self.answer = answer
        self.answered = answered
        self.timings_ms = type("T", (), {"retrieve": retrieve, "generate": generate})()


@pytest.fixture
def scripted_ask(monkeypatch):
    """Replace `ask.answer` so the turn can run with no model and no database."""
    import services.ask as ask_module

    async def fake(conn, query, **kwargs):
        return _Reply("Business Bay recorded 10,669 transactions. The median was high.")

    monkeypatch.setattr(ask_module, "answer", fake)
    return fake


@pytest.mark.asyncio
async def test_a_turn_reports_every_stage(scripted_ask):
    async with _scripted() as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert result.transcript
    assert result.answered
    for stage in ("vad", "stt", "retrieve", "generate", "tts_first_audio"):
        assert stage in result.stages_ms, stage


@pytest.mark.asyncio
async def test_time_to_first_audio_excludes_vad(scripted_ask):
    """The budget clock starts when the SPEAKER stops.

    Endpoint detection is what decides that they have, so counting it would charge the
    pipeline for the moment it is measuring from. `tts_total` is excluded for the opposite
    reason: the listener hears the first chunk, not the last.
    """
    async with _scripted() as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert "vad" in result.stages_ms
    expected = sum(
        v for k, v in result.stages_ms.items() if k not in ("vad", "tts_total")
    )
    assert result.to_first_audio_ms == pytest.approx(expected)
    assert result.to_first_audio_ms < result.total_ms


@pytest.mark.asyncio
async def test_a_slow_turn_is_a_result_not_an_exception(scripted_ask):
    # Missing the budget is the EXPECTED outcome and the measurement is the deliverable.
    # Raising would turn this milestone's central finding into an error page.
    async with _scripted() as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert result.within_budget is False
    assert result.over_budget_by_ms > 0
    assert result.to_first_audio_ms > BUDGET_MS


@pytest.mark.asyncio
async def test_a_cold_model_says_so_rather_than_reporting_a_comparable_number(scripted_ask):
    async with _scripted(stt_cold=True, tts_cold=True) as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert any("COLD" in w for w in result.warnings)
    assert sum("COLD" in w for w in result.warnings) == 2


@pytest.mark.asyncio
async def test_a_missing_endpoint_is_a_warning_not_a_failure(scripted_ask):
    """Null is the normal state of every frame but the last in a live stream."""
    async with _scripted(endpoint_ms=None) as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert result.endpoint_ms is None
    assert result.answered
    assert any("no endpoint" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_an_empty_transcript_stops_before_the_model(scripted_ask):
    # Silence must not reach the generation layer. A 2-second model call on an empty
    # question is the most expensive possible way to say nothing.
    async with _scripted(transcript="") as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert result.answer == ""
    assert "generate" not in result.stages_ms
    assert any("empty transcript" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_only_the_opening_sentence_is_synthesised_and_it_says_so(scripted_ask):
    async with _scripted() as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert result.spoken_first == "Business Bay recorded 10,669 transactions."
    assert any("opening sentence" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_answer_overhead_is_attributed_rather_than_dropped(scripted_ask, monkeypatch):
    """Wall clock the route does not account for is still time a listener waited through."""
    import services.ask as ask_module

    async def slow(conn, query, **kwargs):
        import asyncio

        await asyncio.sleep(0.05)
        return _Reply("A sentence long enough to be split from the next one here. Second.",
                      retrieve=1, generate=1)

    monkeypatch.setattr(ask_module, "answer", slow)
    async with _scripted() as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client)
    assert result.stages_ms["answer_overhead"] > 40


@pytest.mark.asyncio
async def test_speak_false_measures_the_pipeline_without_tts(scripted_ask):
    async with _scripted() as client:
        result = await pipeline.run_turn(None, b"\x00\x00" * 32000, client=client, speak=False)
    assert "tts_first_audio" not in result.stages_ms
    assert result.audio_bytes == 0


# ── the endpoint, with the voice container absent ───────────────────────────


@pytest.mark.asyncio
async def test_a_missing_voice_service_is_a_503(client, monkeypatch):
    """The voice container is profiled out of `up` by default, exactly like embeddings.

    A stack running without it is a CONFIGURATION, not a fault, and the message has to
    name the service — an unexplained 500 is how a missing optional dependency becomes an
    afternoon of debugging.
    """
    import routers.voice as voice_router

    async def unreachable(*args, **kwargs):
        raise httpx.ConnectError("nope")

    broken = httpx.AsyncClient(transport=httpx.MockTransport(unreachable))
    monkeypatch.setattr(voice_router, "get_client", lambda: broken)

    response = await client.post(
        "/voice/turn", content=b"\x00\x00" * 16000,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 503
    assert "voice service unreachable" in response.json()["detail"]


def test_the_websocket_actually_sends_the_audio_it_documents(monkeypatch):
    """The regression guard for a protocol that lied.

    `/voice/stream` documented a binary frame after the answer and sent none: the pipeline
    kept only the LENGTH of the synthesised audio, which was enough for the JSON
    measurement endpoint and left the socket silent. A client would have received a correct
    transcript, a correct answer, correct timings — and nothing to play. Found by
    connecting a real client and counting frames, not by reading the code.

    Uses starlette's TestClient because httpx's ASGI transport does not speak WebSocket.
    """
    from starlette.testclient import TestClient

    import routers.voice as voice_router
    import services.ask as ask_module
    from main import app

    async def fake_answer(conn, query, **kwargs):
        return _Reply("Business Bay recorded 10,669 transactions. The median was high.")

    monkeypatch.setattr(ask_module, "answer", fake_answer)
    monkeypatch.setattr(voice_router, "get_client", _scripted)

    with TestClient(app) as http:
        with http.websocket_connect("/voice/stream") as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(b"\x00\x00" * 16000)
            seen, frames, payload = [], 0, 0
            while True:
                message = socket.receive()
                if "bytes" in message and message["bytes"] is not None:
                    frames += 1
                    payload += len(message["bytes"])
                    continue
                body = json.loads(message["text"])
                seen.append(body["type"])
                if body["type"] == "timings":
                    break

    assert seen == ["endpoint", "transcript", "answer", "audio", "timings"]
    assert frames > 0, "the socket documented audio frames and sent none"
    assert payload == 1600  # the scripted TTS body, delivered whole


def test_the_websocket_rejects_an_unknown_command(monkeypatch):
    from starlette.testclient import TestClient

    import routers.voice as voice_router
    from main import app

    monkeypatch.setattr(voice_router, "get_client", _scripted)
    with TestClient(app) as http:
        with http.websocket_connect("/voice/stream") as socket:
            socket.receive_json()
            socket.send_json({"type": "sing"})
            body = socket.receive_json()
    assert body["type"] == "error" and "sing" in body["detail"]


def test_the_websocket_will_not_flush_an_empty_buffer(monkeypatch):
    # Silence must not reach the model, and an empty flush must not look like a turn.
    from starlette.testclient import TestClient

    import routers.voice as voice_router
    from main import app

    monkeypatch.setattr(voice_router, "get_client", _scripted)
    with TestClient(app) as http:
        with http.websocket_connect("/voice/stream") as socket:
            socket.receive_json()
            socket.send_json({"type": "flush"})
            body = socket.receive_json()
    assert body["type"] == "error" and "no audio" in body["detail"]


@pytest.mark.asyncio
async def test_an_empty_body_is_a_400(client):
    response = await client.post("/voice/turn", content=b"")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_an_unknown_route_is_rejected(client):
    response = await client.post(
        "/voice/turn?route=magic", content=b"\x00\x00" * 16000,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 400
    assert "magic" in response.json()["detail"]


@pytest.mark.asyncio
async def test_the_budget_endpoint_answers_before_anything_has_run(client):
    response = await client.get("/voice/budget")
    assert response.status_code == 200
    body = response.json()
    assert body["budget_ms"] == BUDGET_MS
    assert body["target_total_ms"] > body["budget_ms"]
    assert len(body["stages"]) == len(STAGES)
    assert all(stage["source"] for stage in body["stages"])
