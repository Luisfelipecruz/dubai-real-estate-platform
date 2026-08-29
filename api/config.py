import os


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://dubai_user:dubai_pass@localhost:5432/dubai_re",
)

# Sync URL for ingestion (psycopg2 doesn't support asyncpg://)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "").replace(
    "postgresql://", "postgresql://"
)

# ── Copilot: retrieval layer ────────────────────────────────────────────────
#
# Local and keyless by design. The embedding layer is fixed and runs in-cluster; only
# the generation layer (m14) is pluggable. See docs/rag-corpus-design.md.
#
# EMBEDDING_MODEL is not just a service setting -- it is written into every row of
# doc_chunks and asserted at query time. Changing it invalidates every stored vector,
# and a mismatch that is not caught returns fluent nonsense rather than an error.
EMBEDDINGS_URL = os.environ.get("EMBEDDINGS_URL", "http://embeddings:8100")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIMENSIONS = 384

# Candidates pulled from each retrieval arm before fusion.
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "20"))
# Results returned after cross-encoder reranking.
RERANK_TOP_N = int(os.environ.get("RERANK_TOP_N", "5"))
# Reciprocal Rank Fusion constant. 60 is the value from Cormack et al. (2009); it is
# inherited here as a starting point and measured in m16, not taken on faith.
RRF_K = int(os.environ.get("RRF_K", "60"))

# Retrieval must not be able to hang a request. The embeddings service loads ~1.2 GB of
# weights on first call, so the ceiling is generous but finite.
EMBEDDINGS_TIMEOUT_S = float(os.environ.get("EMBEDDINGS_TIMEOUT_S", "30"))
