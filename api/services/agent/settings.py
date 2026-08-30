"""Budgets for the orchestration layer. Ceilings, not targets.

Every number here is derived from something m14 measured rather than chosen because it
looked round. The derivations are in the comments, because a budget whose reasoning is
not written down is a budget the next person raises when it fires.
"""

import os

# ── The step cap ────────────────────────────────────────────────────────────
#
# IMPLEMENTATION-PLAN.md §5.3 specifies a hard cap at 8 tool calls. m14 measured what a
# step costs: generate p50 was 7,914 ms in the best of three runs and 20,927 ms in the
# worst, on identical code and an identical model, because a local 20B saturates the host
# it shares (M-21). Eight steps is therefore between one and three MINUTES, and the
# variance is the problem rather than the median.
#
# The cap stays at 8 because it is the plan's number and changing it would need a
# measurement. What changed is what happens when it is reached: the run returns its
# partial findings LABELLED partial, rather than raising. A truncated answer presented as
# a complete one is the failure this cap exists to make visible.
AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "8"))

# Wall-clock ceiling for a whole run, independent of the step count. Eight steps at the
# worst observed latency is ~168 s of generation alone; this stops a pathological run
# rather than sizing a normal one.
AGENT_TIMEOUT_S = float(os.environ.get("AGENT_TIMEOUT_S", "300"))

# ── Cost ────────────────────────────────────────────────────────────────────
#
# LLM_MAX_COST_USD_PER_REQUEST is m14's per-CALL ceiling. A run is many calls, so the
# run-level ceiling is separate and is enforced from `llm_calls` rows -- the same table
# /ask/costs already aggregates -- rather than from a counter nobody reads. On the local
# provider every row prices at $0.00 and the ceiling never binds, which is exactly why it
# must be enforced from data: the first hosted run is the first time it means anything,
# and by then it is too late to discover the accounting was notional.
AGENT_MAX_COST_USD_PER_RUN = float(os.environ.get("AGENT_MAX_COST_USD_PER_RUN", "2.00"))

# ── Result size ─────────────────────────────────────────────────────────────
#
# A tool result goes into the context of every subsequent turn, so a large one is not
# paid once -- it is paid on every remaining step. `area_price_history` over 19 years is
# the natural worst case here. Truncation is reported inside the result itself so the
# model knows it is looking at part of something.
AGENT_MAX_TOOL_RESULT_CHARS = int(
    os.environ.get("AGENT_MAX_TOOL_RESULT_CHARS", "6000")
)

# Output tokens per turn. Lower than /ask's 1,500: a turn that only decides which tool to
# call needs very few, and the final synthesis is the only one that needs room.
AGENT_MAX_OUTPUT_TOKENS = int(os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "1200"))

# `effort` on the hosted provider. The local one has no equivalent and logs that it
# ignored the value rather than pretending the two are interchangeable.
AGENT_EFFORT = os.environ.get("AGENT_EFFORT", "high")
