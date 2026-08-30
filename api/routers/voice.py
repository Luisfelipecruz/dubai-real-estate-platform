"""The spoken path: one measurable turn, one live stream, one budget.

THREE OPERATIONS, AND THE SPLIT IS THE POINT
---------------------------------------------
    POST /voice/turn     audio in, answer and speech out, every stage timed
    WS   /voice/stream   the interactive path — frames in, events and audio out
    GET  /voice/budget   the targets, the last measurements, and the verdict

`POST /voice/turn` exists because a WebSocket cannot be measured with `curl`, and a number
nobody can reproduce from a shell is a number that quietly rots. It takes the same audio
and runs the same pipeline; it just does not stream. Every figure in
`docs/voice-latency.md` comes from it.

`WS /voice/stream` is the shape a real client needs and SSE cannot provide: audio has to
travel *upstream* as well as down, and server-sent events are one-directional. It is the
interactive path and it is deliberately the one that is harder to measure, because the
measurement lives next door.

WHAT THIS ROUTER DOES NOT DO
-----------------------------
It does not put `/agent/query` in the interactive path by default. M-48 measured an agent
run at 1.4-58.6 s per question against an 800 ms budget, and the handoff's standing rule is
that a multi-step agent run cannot live there. `route=agent` exists so the cost can be
measured rather than asserted — which is the same reason `beam_size` and
`trailing_silence_ms` are parameters instead of constants.

`api/main.py` is untouched by this milestone. `voice` has been in `COPILOT_ROUTERS` since
m13 and the tolerant loop finds it by name — the third time that design has paid off, after
`ask` in m14 and `agent` in m15.
"""

import json
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from database import engine
from models.voice import BudgetResponse, TurnResponse
from services.voice import pipeline
from services.voice.settings import (
    BUDGET_MS,
    RERANK_ON_VOICE_PATH,
    STAGES,
    VOICE_URL,
    settings_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# The last turn's stage timings, in memory, so GET /voice/budget can answer "measured
# against target" without a database round trip. Deliberately NOT persisted: a latency
# figure from this stack is worthless without the host load beside it (M-21, M-35, M-48),
# and a table of orphaned milliseconds would invite exactly the comparison those three
# measurements say cannot be made. The durable record is docs/voice-latency.md.
_last_measured: dict[str, float] = {}

# One client for the whole process. The voice service is three HTTP hops away in an
# interactive path; opening a connection per call would add a TCP handshake to a budget
# measured in hundreds of milliseconds and then report it as model time.
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # 600 s because a COLD Whisper or Piper load is a download, and a timeout there
        # would look like a broken service rather than a first run. The warm path is
        # three orders of magnitude inside this.
        _client = httpx.AsyncClient(timeout=600.0)
    return _client


def _verdict(measured: dict[str, float]) -> str:
    if not measured:
        return "never measured — run POST /voice/turn"
    to_first_audio = sum(
        value for name, value in measured.items() if name not in ("vad", "tts_total")
    )
    if to_first_audio <= BUDGET_MS:
        return f"MET: {to_first_audio:.0f} ms to first audio against {BUDGET_MS} ms"
    return (
        f"MISSED: {to_first_audio:.0f} ms to first audio against {BUDGET_MS} ms, "
        f"{to_first_audio / BUDGET_MS:.1f}x over"
    )


@router.get("/budget", response_model=BudgetResponse)
async def budget() -> BudgetResponse:
    """The latency budget as data, with the last measurement beside each target.

    §7.2 states the budget in prose and concludes that the naive pipeline misses it. That
    conclusion is correct and prose is the wrong place for it: nothing checks a paragraph.
    This endpoint computes the verdict from whatever actually ran.
    """
    snapshot = settings_snapshot()
    return BudgetResponse(
        budget_ms=BUDGET_MS,
        target_total_ms=snapshot["target_total_ms"],
        stages=pipeline.stage_verdicts(_last_measured),
        verdict=_verdict(_last_measured),
        rerank_on_voice_path=RERANK_ON_VOICE_PATH,
        measured=dict(_last_measured),
    )


@router.post("/turn", response_model=TurnResponse)
async def turn(
    request: Request,
    route: str = "ask",
    trailing_silence_ms: int = 200,
    beam_size: int = 1,
    speak: bool = True,
) -> TurnResponse:
    """One complete spoken turn from raw PCM. The measurement path.

    Body is raw 16 kHz mono s16le PCM — no WAV header, no base64, no multipart. The format
    is what `webrtcvad` requires and what `faster-whisper` wants anyway, so nothing in the
    path spends time converting.
    """
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty body; expected raw 16 kHz mono s16le PCM")
    if route not in ("ask", "agent"):
        raise HTTPException(400, f"unknown route {route!r}; use 'ask' or 'agent'")

    try:
        async with engine.connect() as conn:
            result = await pipeline.run_turn(
                conn,
                audio,
                client=get_client(),
                route=route,
                trailing_silence_ms=trailing_silence_ms,
                beam_size=beam_size,
                speak=speak,
            )
    except httpx.HTTPError as exc:
        # 503, not 500. The voice container is optional and profiled out of `up` by
        # default, exactly like the embeddings service — a stack running without it is a
        # configuration, not a fault, and the message says which service is missing.
        raise HTTPException(
            503, f"voice service unreachable at {VOICE_URL}: {type(exc).__name__}: {exc}"
        ) from exc

    _last_measured.clear()
    _last_measured.update(result.stages_ms)

    return TurnResponse(
        transcript=result.transcript,
        answer=result.answer,
        answered=result.answered,
        route=result.route,
        spoken_first=result.spoken_first,
        stages_ms={k: round(v, 2) for k, v in result.stages_ms.items()},
        budget=pipeline.stage_verdicts(result.stages_ms),
        to_first_audio_ms=round(result.to_first_audio_ms, 2),
        total_ms=round(result.total_ms, 2),
        budget_ms=BUDGET_MS,
        within_budget=result.within_budget,
        over_budget_by_ms=result.over_budget_by_ms,
        audio_bytes=result.audio_bytes,
        audio_ms=result.audio_ms,
        sample_rate=result.sample_rate,
        stt_realtime_factor=result.stt_realtime_factor,
        endpoint_ms=result.endpoint_ms,
        warnings=result.warnings,
    )


@router.websocket("/stream")
async def stream(socket: WebSocket) -> None:
    """The interactive path. Binary frames up, JSON events and binary audio down.

    Protocol, deliberately small:

        server -> {"type": "ready", "sample_rate": 16000, "frame_ms": 20}
        client -> binary frames of 16 kHz mono s16le PCM, any size
        client -> {"type": "flush"}          end the turn without waiting for silence
        server -> {"type": "endpoint", "at_ms": N}
        server -> {"type": "transcript", "text": ...}
        server -> {"type": "answer", "text": ..., "answered": bool}
        server -> binary audio, then {"type": "timings", ...}

    ENDPOINTING RUNS ON THE SERVER, on the accumulated buffer, once per received chunk.
    That is the honest simple version and it has a cost worth naming: a browser that
    endpointed locally would save a round trip per chunk. VAD compute is 0.35 ms for four
    seconds of audio, so the saving is transport, not computation — and this project has
    no browser client to put it in. Recorded rather than hidden.
    """
    await socket.accept()
    await socket.send_json({"type": "ready", "sample_rate": 16000, "frame_ms": 20})

    buffer = bytearray()
    client = get_client()

    try:
        while True:
            message = await socket.receive()
            if message.get("type") == "websocket.disconnect":
                return

            if (chunk := message.get("bytes")) is not None:
                buffer.extend(chunk)
                # Endpoint only once there is enough audio for the question to be worth
                # asking. Below ~300 ms every clip looks like trailing silence.
                if len(buffer) < 16000 * 2 * 0.3:
                    continue
                vad = await client.post(
                    f"{VOICE_URL}/vad",
                    content=bytes(buffer),
                    headers={"Content-Type": "application/octet-stream"},
                )
                if vad.status_code != 200 or vad.json().get("endpoint_ms") is None:
                    continue
            elif (raw := message.get("text")) is not None:
                try:
                    command = json.loads(raw).get("type")
                except json.JSONDecodeError:
                    await socket.send_json({"type": "error", "detail": "not JSON"})
                    continue
                if command != "flush":
                    await socket.send_json(
                        {"type": "error", "detail": f"unknown command {command!r}"}
                    )
                    continue
                if not buffer:
                    await socket.send_json({"type": "error", "detail": "no audio buffered"})
                    continue
            else:
                continue

            audio = bytes(buffer)
            buffer.clear()
            async with engine.connect() as conn:
                result = await pipeline.run_turn(conn, audio, client=client, speak=True)

            _last_measured.clear()
            _last_measured.update(result.stages_ms)

            await socket.send_json({"type": "endpoint", "at_ms": result.endpoint_ms})
            await socket.send_json({"type": "transcript", "text": result.transcript})
            await socket.send_json(
                {"type": "answer", "text": result.answer, "answered": result.answered}
            )

            # The audio, in the same 20 ms framing the client sends. One 300 kB frame
            # would arrive as a single event and defeat the entire point of streaming it:
            # a client can begin playback on the first frame, which is what
            # `to_first_audio_ms` is measuring.
            if result.audio:
                await socket.send_json(
                    {"type": "audio", "bytes": result.audio_bytes,
                     "sample_rate": result.sample_rate, "audio_ms": result.audio_ms}
                )
                frame = result.sample_rate * 2 * 20 // 1000 or 640
                for offset in range(0, len(result.audio), frame):
                    await socket.send_bytes(result.audio[offset : offset + frame])

            await socket.send_json(
                {
                    "type": "timings",
                    "stages_ms": {k: round(v, 2) for k, v in result.stages_ms.items()},
                    "to_first_audio_ms": round(result.to_first_audio_ms, 2),
                    "budget_ms": BUDGET_MS,
                    "within_budget": result.within_budget,
                    "warnings": result.warnings,
                }
            )
    except WebSocketDisconnect:
        return
    except httpx.HTTPError as exc:
        logger.warning("voice service unreachable: %s", exc)
        await socket.send_json(
            {"type": "error", "detail": f"voice service unreachable at {VOICE_URL}"}
        )
        await socket.close(code=1011)
