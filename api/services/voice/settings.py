"""The latency budget, as data.

WHY THE BUDGET IS AN OBJECT AND NOT A PARAGRAPH
------------------------------------------------
§7.2 of the plan states an 800 ms end-to-end target and a stage table adding up to
~1,320 ms, then says plainly that the naive pipeline does not hit it. That is the right
conclusion and the wrong place for it to live: a number in a document is not checked by
anything, and this project has already watched a documented trap get re-introduced by a new
tool under a friendly name (the v0.5.0 / G-02 rent trap, twice).

So the targets live here, `GET /voice/budget` returns them beside whatever the last runs
actually measured, and the verdict — met, missed, or never measured — is computed rather
than written down. "We miss the budget" becomes a queryable fact with a number attached.

WHAT THE EXISTING MEASUREMENTS ALREADY SAY
-------------------------------------------
Three of the five stages were measured before this milestone started, and they are the
reason the answer is already known:

    M-8    reranking costs 2,919 ms p50, 99.2% of the retrieval pipeline
    M-21   /ask generation p50 7,914 ms in the best of three runs, 20,927 ms in the worst
    M-48   an agent run is 1.4-58.6 s per question

Against 800 ms. Generation alone is 10x over at its best and 26x at its worst, and no
amount of care in the audio stages closes a gap of that size. m17's job is to measure the
whole thing honestly and say which stages could ever be in an interactive path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["BUDGET_MS", "STAGES", "Stage", "VOICE_URL", "settings_snapshot"]

VOICE_URL = os.getenv("VOICE_URL", "http://voice:8200")

# The plan's number. Conversational turn-taking degrades past roughly 800 ms of silence;
# below that a listener reads the pause as thinking rather than as a broken system.
BUDGET_MS = int(os.getenv("VOICE_BUDGET_MS", "800"))


@dataclass(frozen=True)
class Stage:
    """One stage of a spoken turn, its target, and where the target came from.

    `source` is not documentation. Every target in §7.2 is either a published figure for a
    component or a guess, and a budget that does not distinguish the two invites the
    reader to trust all of them equally. A stage whose target came from a vendor's README
    deserves less confidence than one this project has already measured on this machine.
    """

    name: str
    target_ms: int
    source: str
    interactive: bool = True


STAGES: tuple[Stage, ...] = (
    Stage("vad", 200, "plan §7.2 — trailing-silence threshold, tunable and measured here"),
    Stage("stt", 250, "plan §7.2 — faster-whisper base.en int8 on CPU, measured here"),
    Stage("retrieve", 320, "M-8: 67 ms p50 retrieval WITHOUT rerank; 2,944 ms with it"),
    Stage("generate", 400, "plan §7.2 — and M-21 measured 7,914-20,927 ms p50 for /ask"),
    Stage("tts_first_audio", 150, "plan §7.2 — Piper streams by sentence, measured here"),
)

# Reranking is NOT a stage in this budget, and the reason is stronger than latency.
#
# §7.2 lever 2 frames it as a trade: 287 ms for an nDCG gain, pay it if the gain is worth
# it. m16 measured the gain and it is NEGATIVE. On the 20-question golden set, dense scores
# 17/20 at top-1 and hybrid+rerank scores 8/20; on the original m13a ten it is 9/10 against
# 2/10. The cross-encoder makes ranking WORSE on this corpus while costing 2.9 s.
#
# So the voice path does not skip the reranker to buy latency at the cost of quality. It
# skips it because it costs 2.9 s AND loses quality, which is not a trade-off at all. That
# is only knowable because m16 ran the ablation; without it, this would have been a
# defensible-sounding sacrifice.
RERANK_ON_VOICE_PATH = False


def settings_snapshot() -> dict:
    return {
        "budget_ms": BUDGET_MS,
        "voice_url": VOICE_URL,
        "rerank_on_voice_path": RERANK_ON_VOICE_PATH,
        "stages": [
            {
                "name": stage.name,
                "target_ms": stage.target_ms,
                "source": stage.source,
                "interactive": stage.interactive,
            }
            for stage in STAGES
        ],
        "target_total_ms": sum(stage.target_ms for stage in STAGES),
    }
