"""Configuration for the generation layer.

── WHY THIS IS NOT IN api/config.py ────────────────────────────────────────────

Two reasons, and the weaker one is the architectural one.

The weaker reason: these settings are read by exactly one package, and putting them
next to it means the generation layer can be deleted in one `rm -r`. api/config.py
holds settings that the whole application shares.

The stronger reason is bookkeeping, and it is worth writing down rather than
disguising. Commits in this repository are deliberately deferred across sessions, and
api/config.py is claimed by the m13 commit that has not been made yet. Editing it now
would put m14's constants inside m13's diff -- silently, because `git add` stages a
file's CURRENT content, not its content when the milestone finished. The ownership
ledger in market-intelligence-agent/GIT-COMMANDS.sh §1 records the claim and a hash
manifest detects exactly this drift. A detector that gets re-baselined the first time
it fires is not a detector, so the code moved instead of the manifest.

── ONE KNOWN GAP ───────────────────────────────────────────────────────────────

LLM_TIMEOUT_S, LLM_MAX_OUTPUT_TOKENS and LLM_REPAIR_ATTEMPTS are read from the
environment here but are NOT in docker-compose.yml's `api.environment` block, so a
value set in .env does not reach the container -- compose passes only what it lists.
The defaults below are the effective values in Docker today. The fix is three lines in
docker-compose.yml, which m13 claims for the same reason as above; it is listed in
docs/llm-app-layer.md so it lands with m13's next edit rather than being rediscovered.
"""

import os

# local | anthropic | none. `none` is a supported configuration, not a broken one.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "local").strip().lower()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")

# ── Budgets. Ceilings, not targets. ─────────────────────────────────────────
#
# The corpus is ~320 chunks / ~68k tokens in total, and five retrieved chunks come to
# roughly 1,500. 8,000 is therefore ~25x a normal request and ~12% of the whole corpus:
# a request that trips it is a bug upstream, not a large question. The guard REFUSES
# rather than truncating, because truncating a grounded answer's context silently
# removes the evidence the answer is supposed to rest on.
LLM_MAX_INPUT_TOKENS = int(os.environ.get("LLM_MAX_INPUT_TOKENS", "8000"))
LLM_MAX_COST_USD_PER_REQUEST = float(
    os.environ.get("LLM_MAX_COST_USD_PER_REQUEST", "0.50")
)
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "1500"))

# A 20B model on Metal answers a five-context question in roughly 10-30 s. 120 s is a
# hang detector, not a latency target -- /ask reports its own p50 and that is the number
# to look at.
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "120"))

# Capped, and the cap is logged. An uncapped JSON-repair loop is how one question
# becomes forty requests; see docs/llm-app-layer.md.
LLM_REPAIR_ATTEMPTS = int(os.environ.get("LLM_REPAIR_ATTEMPTS", "2"))

# Retrieval settings /ask inherits. NOT re-derived and NOT tunable per request:
# m13a measured both of them and changing either is a measurement, not an opinion.
#   dense   8/10 top-1, 9/10 recall@5,    67 ms   <- this
#   hybrid  7/10 top-1, 9/10 recall@5,    67 ms
#   +rerank 3/10 top-1, 6/10 recall@5, 2,944 ms
ASK_RETRIEVAL_MODE = "dense"
ASK_RERANK = False
# recall@1 is 8/10 and recall@5 is 9/10. The ninth answer is reachable only at k=5, and
# four more chunks cost ~1,100 tokens -- about $0.006 on claude-opus-5 and nothing at
# all locally. Paying that to move recall a tenth is obviously correct.
ASK_TOP_K = 5
# Candidates per arm before fusion, matching RETRIEVAL_TOP_K's default.
ASK_CANDIDATES = 20
