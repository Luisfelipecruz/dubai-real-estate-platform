"""One spoken turn, stage by stage, with the clock running on every stage.

WHAT THIS MEASURES, AND WHY IT IS TIME-TO-FIRST-AUDIO
------------------------------------------------------
A listener does not experience the end of a sentence; they experience the silence before it
starts. So the headline number is **time to first audio** — endpoint detected to first PCM
sample available — and the total is reported beside it rather than instead of it. A
pipeline that produces a complete 12-second answer in 9 seconds and one that starts
speaking after 900 ms have identical totals and completely different behaviour.

THE THREE LEVERS FROM §7.2, AND WHICH ONES THIS CAN ACTUALLY PULL
------------------------------------------------------------------
1. **Overlap, don't serialise.** PARTIALLY IMPLEMENTED. Retrieval can start on the partial
   transcript while the speaker is still going, and `run_turn` accepts a prefetch. What it
   cannot do is start the *generation* early, because the question is not known until the
   speaker stops.
2. **Skip the reranker.** DONE, and it turned out not to be a sacrifice. §7.2 framed it as
   buying 287 ms at some cost in quality; m16 measured the quality and reranking is WORSE
   on this corpus — 8/20 against dense's 17/20 at top-1. `/ask` already hard-wires
   `rerank=false` for that reason, so the voice path inherits it and pays nothing.
3. **Speak the first sentence early.** PARTIALLY IMPLEMENTED, and the limit is worth
   stating rather than hiding. This splits the answer and synthesises the opening sentence
   first, which is real. The larger half of the lever — beginning synthesis while the model
   is still generating — needs token streaming out of the generation layer, and m15
   deliberately did not build SSE because nothing consumed it. So this milestone measures
   the half it has and records what the other half would be worth.

WHY IT CALLS `ask.answer` IN PROCESS
-------------------------------------
Not over HTTP. A localhost round trip is single-digit milliseconds and would be noise
against a 7-second generation — but it is noise pointed the wrong way, and the whole point
of the exercise is to be able to say where the time went without a caveat. The in-process
call also inherits `/ask`'s hard-wired retrieval configuration, which m13a measured and
m16 re-confirmed at n=20, rather than re-deriving it here where it could drift.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

from services.voice.settings import BUDGET_MS, STAGES, VOICE_URL

__all__ = ["TurnResult", "first_sentence", "run_turn", "stage_verdicts"]

# A sentence boundary good enough to pick an opening clause to speak. Deliberately not a
# sentence tokenizer: this runs in an interactive path, the input is one paragraph of the
# model's own prose, and a 40 kB dependency to split on a full stop is not a trade worth
# making. It errs toward NOT splitting, which degrades to "speak the whole thing" — the
# behaviour without the lever, never a truncated one.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def first_sentence(text: str, min_chars: int = 40) -> tuple[str, str]:
    """Split into (opening, remainder) for early synthesis.

    `min_chars` stops the split on "AED 120,000." or "Yes." — an opening too short to cover
    the synthesis of what follows buys nothing and adds a seam a listener can hear.
    """
    if not text:
        return "", ""
    for match in _SENTENCE_END.finditer(text):
        if match.start() >= min_chars:
            return text[: match.start()].strip(), text[match.end() :].strip()
    return text.strip(), ""


@dataclass
class TurnResult:
    """One turn, and every number needed to say whether it fit the budget."""

    transcript: str = ""
    answer: str = ""
    answered: bool = False
    spoken_first: str = ""
    audio: bytes = b""
    audio_bytes: int = 0
    audio_ms: int = 0
    sample_rate: int = 0
    stages_ms: dict[str, float] = field(default_factory=dict)
    to_first_audio_ms: float = 0.0
    total_ms: float = 0.0
    within_budget: bool = False
    over_budget_by_ms: float = 0.0
    route: str = "ask"
    warnings: list[str] = field(default_factory=list)
    stt_realtime_factor: float = 0.0
    endpoint_ms: int | None = None


def stage_verdicts(stages_ms: dict[str, float]) -> list[dict]:
    """Per-stage measured-against-target, for `GET /voice/budget`.

    A stage with no measurement reports `null` rather than 0. Zero is a claim that the
    stage was instant; null is the truth, which is that nobody has run it yet. This project
    has a standing rule that `$0.00` and `null` are different facts, and the same applies
    to milliseconds.
    """
    out = []
    for stage in STAGES:
        measured = stages_ms.get(stage.name)
        out.append(
            {
                "stage": stage.name,
                "target_ms": stage.target_ms,
                "measured_ms": None if measured is None else round(measured, 1),
                "over_by_ms": None if measured is None else round(measured - stage.target_ms, 1),
                "within_target": None if measured is None else measured <= stage.target_ms,
                "source": stage.source,
            }
        )
    return out


async def run_turn(
    conn,
    audio: bytes,
    *,
    client: httpx.AsyncClient,
    route: str = "ask",
    trailing_silence_ms: int = 200,
    beam_size: int = 1,
    speak: bool = True,
) -> TurnResult:
    """Audio in, answer and speech out, with the clock on every stage.

    Raises nothing on a slow turn. Missing the budget is the expected outcome and the
    measurement is the deliverable; an exception would turn the finding into an error page.
    """
    result = TurnResult(route=route)
    stages: dict[str, float] = {}

    # ── 1. endpointing ──────────────────────────────────────────────────────
    mark = time.perf_counter()
    vad = await client.post(
        f"{VOICE_URL}/vad",
        content=audio,
        params={"trailing_silence_ms": trailing_silence_ms},
        headers={"Content-Type": "application/octet-stream"},
    )
    vad.raise_for_status()
    vad_body = vad.json()
    stages["vad"] = (time.perf_counter() - mark) * 1000
    result.endpoint_ms = vad_body.get("endpoint_ms")
    if result.endpoint_ms is None:
        # Not an error. It means the speaker had not finished by the end of the buffer,
        # which is the normal state of every frame but the last in a live stream. In a
        # one-shot measurement it means the clip has no trailing silence, and the honest
        # thing is to say so rather than to invent an endpoint.
        result.warnings.append(
            "no endpoint detected: the audio ends while speech is still active, so "
            "`vad` here measures detection cost rather than endpointing latency"
        )

    # ── 2. transcription ────────────────────────────────────────────────────
    mark = time.perf_counter()
    stt = await client.post(
        f"{VOICE_URL}/stt",
        content=audio,
        params={"beam_size": beam_size},
        headers={"Content-Type": "application/octet-stream"},
    )
    stt.raise_for_status()
    stt_body = stt.json()
    stages["stt"] = (time.perf_counter() - mark) * 1000
    result.transcript = stt_body["text"]
    result.stt_realtime_factor = stt_body["realtime_factor"]
    if stt_body.get("cold"):
        result.warnings.append(
            "the STT model was COLD on this call: the timing includes a one-off load and "
            "must not be compared with a warm run"
        )

    if not result.transcript:
        result.stages_ms = stages
        result.warnings.append("empty transcript; nothing to answer")
        result.total_ms = sum(stages.values())
        return result

    # ── 3. the answer ───────────────────────────────────────────────────────
    mark = time.perf_counter()
    if route == "agent":
        from services.agent import executor

        agent = await executor.run(conn, result.transcript)
        result.answer = agent.answer or ""
        result.answered = agent.outcome == "answered"
        # `timings_ms` is a pydantic model on both routes, not a dict — AskTimings and
        # AgentTimings. Attribute access, not `.get`, and the two carry DIFFERENT field
        # names for the same idea: `/ask` splits retrieve/generate, the agent splits
        # tools/generate. Mapping the agent's tool time onto `retrieve` keeps the two
        # routes comparable stage for stage instead of collapsing one into a single
        # opaque number.
        stages["retrieve"] = float(agent.timings_ms.tools)
        stages["generate"] = float(agent.timings_ms.generate)
    else:
        from services import ask

        reply = await ask.answer(conn, result.transcript, endpoint="/voice/turn")
        result.answer = reply.answer or ""
        result.answered = reply.answered
        stages["retrieve"] = float(reply.timings_ms.retrieve)
        stages["generate"] = float(reply.timings_ms.generate)
    answer_ms = (time.perf_counter() - mark) * 1000
    # The route's own split may not account for all of its wall clock (verification,
    # citation resolution, the database round trip). Whatever is left over is real time a
    # listener waited through, so it is attributed rather than dropped.
    unattributed = answer_ms - stages.get("retrieve", 0) - stages.get("generate", 0)
    if unattributed > 1:
        stages["answer_overhead"] = unattributed

    # ── 4. speech ───────────────────────────────────────────────────────────
    if speak and result.answer:
        opening, remainder = first_sentence(result.answer)
        result.spoken_first = opening
        mark = time.perf_counter()
        tts = await client.post(f"{VOICE_URL}/tts", json={"text": opening})
        tts.raise_for_status()
        stages["tts_first_audio"] = float(tts.headers.get("X-First-Chunk-Ms", 0))
        stages["tts_total"] = (time.perf_counter() - mark) * 1000
        # The PCM itself, not just its length. The first version kept only the count,
        # which was enough for `POST /voice/turn` — a JSON measurement endpoint — and
        # silently made the WEBSOCKET protocol a lie: its own docstring documents a binary
        # frame after the answer and it sent none. A client would have received a correct
        # transcript, a correct answer, correct timings, and complete silence. Found by
        # connecting a real client and counting the frames.
        result.audio = tts.content
        result.audio_bytes = len(tts.content)
        result.audio_ms = int(tts.headers.get("X-Audio-Ms", 0))
        result.sample_rate = int(tts.headers.get("X-Sample-Rate", 0))
        if tts.headers.get("X-Cold") == "true":
            result.warnings.append(
                "the TTS voice was COLD on this call: the timing includes a one-off "
                "download and load"
            )
        if remainder:
            result.warnings.append(
                f"only the opening sentence was synthesised ({len(opening)} of "
                f"{len(result.answer)} chars). The rest would stream behind it; "
                f"time-to-first-audio is the number that matters and it is above."
            )

    # ── the verdict ─────────────────────────────────────────────────────────
    result.stages_ms = stages
    # Time to first audio EXCLUDES the VAD stage on purpose. The budget clock starts when
    # the speaker stops, and endpoint detection is what decides that they have — counting
    # it would charge the pipeline for the moment it is measuring from.
    result.to_first_audio_ms = sum(
        value for name, value in stages.items()
        if name not in ("vad", "tts_total")
    )
    result.total_ms = sum(stages.values())
    result.within_budget = result.to_first_audio_ms <= BUDGET_MS
    result.over_budget_by_ms = round(result.to_first_audio_ms - BUDGET_MS, 1)
    return result
