"""M-47: the run that gathers everything and says nothing.

8 of the 147 runs that reported `outcome='answered'` came back with a null answer -- 5.4%,
and always the longest and most expensive ones. Plan §12.4 calls it the worst bug on the
page, because hiding the machinery turns that run from "seven step cards and six tool
calls" into a completely blank screen after 66 seconds.

The handoff's open question asked whether it is a max-token truncation, a final-turn parse
failure, or the provider returning an empty message, and recorded that nothing distinguishes
them. **Something does, and it was being thrown away.** `finish_reason` arrives on every
response, is carried as `LLMResponse.stop_reason`, is copied onto `AgentStep.stop_reason`,
and is persisted nowhere. Measured on 2026-08-30 by wrapping the provider and replaying
both populations, it splits the eight runs cleanly in half:

    finish_reason='length', 1200 of 1200 tokens, 4,906 chars of reasoning, 0 of content
    finish_reason='stop',   14 tokens,           0 chars of reasoning,     0 of content

TWO causes, four runs each, needing different handling and different words. Neither is a
parse failure: in both cases there was nothing to parse.

FIVE RULES
1. A run with no answer is not an answered run -- and the fix is to GIVE it an answer, not
   to relabel the outcome.
2. The discriminator must be persisted. It existed in memory for the length of one request
   and was dropped, which is why the question stood for three milestones.
3. A retry only helps where the input changes. Temperature is 0.
4. The salvage message reports the evidence and never draws the conclusion.
5. The two causes get different words, because they tell an operator to do different things.

`verdict.py` decides what a turn means; `census.py` counts how often each case occurs, on
data recorded long before any of this existed.
"""

from services.synthesis.census import (
    BlankRun,
    Census,
    blank_runs,
    census,
    stop_reason_is_persisted,
)
from services.synthesis.verdict import (
    TRUNCATION_REASONS,
    Diagnosis,
    Finding,
    FinalTurn,
    Verdict,
    assess,
    retry_would_help,
)

__all__ = [
    "TRUNCATION_REASONS",
    "BlankRun",
    "Census",
    "Diagnosis",
    "FinalTurn",
    "Finding",
    "Verdict",
    "assess",
    "blank_runs",
    "census",
    "retry_would_help",
    "stop_reason_is_persisted",
]
