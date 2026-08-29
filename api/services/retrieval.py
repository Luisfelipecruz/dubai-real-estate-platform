"""Hybrid retrieval: dense + lexical, fused on ranks, optionally reranked.

Three stages, and each one exists because the stage before it has a specific blind spot.

**Dense** (cosine KNN over a 384-dim BGE embedding) finds text that MEANS the same
thing as the query. It is the only arm that can answer "somewhere waterfront with
strong rental demand" when no document contains any of those words.

**Lexical** (`ts_rank_cd` over a GIN-indexed tsvector) finds text that CONTAINS the
query's tokens. This is not a legacy fallback. `meter_sale_price`, `CNT`, `Al Thanyah
Fifth` and `v0.5.0` are identity tokens: they mean nothing and denote everything, which
is exactly the class of string a semantic embedding is designed to smear together.
Dense retrieval reliably loses them.

**Fusion** is Reciprocal Rank Fusion: `score = sum over arms of 1 / (k + rank)`.
Deliberately over a weighted blend of the two scores. Cosine similarity lives in
[0, 1] and `ts_rank_cd` is an unbounded relevance mass -- normalising them against each
other requires a constant that has to be re-tuned every time either side changes, and
that constant is invisible in the output. RRF reads only ranks, so it has one parameter,
no calibration step, and no scale to drift.

**Reranking** is a cross-encoder over the fused top candidates. Whether it earns its
200-400 ms is an open question, not an assumption -- m16 measures nDCG@5 with and
without it, and if the number does not move, this stage gets deleted and the result
gets written up.
"""

import time

import httpx
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection

from config import (
    EMBEDDING_MODEL,
    EMBEDDINGS_TIMEOUT_S,
    EMBEDDINGS_URL,
    RRF_K,
)


class RetrievalError(RuntimeError):
    """Retrieval could not run. Carries an HTTP status so the router does not have to
    guess whether the cause was configuration (503) or the caller (422)."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


# Cached per process. `SELECT DISTINCT` over a few thousand rows is cheap, but not
# cheap enough to run on every query, and the answer only changes when the corpus is
# rebuilt -- which restarts nothing, so the cache is cleared explicitly by the indexer's
# callers rather than expiring on a timer.
_model_check_passed: bool = False


def reset_model_check() -> None:
    """Clear the cached embedding-model assertion. Called by tests."""
    global _model_check_passed
    _model_check_passed = False


async def assert_embedding_model(conn: AsyncConnection) -> None:
    """Fail loudly if the stored vectors were not produced by the configured model.

    This is the failure mode that B3 in the plan names: swapping EMBEDDING_MODEL does
    not raise anything. Query vectors from model B are compared against document vectors
    from model A, every cosine distance is meaningless, and the endpoint keeps returning
    five confident results. The only symptom is that the answers get worse.
    """
    global _model_check_passed
    if _model_check_passed:
        return

    try:
        rows = await conn.execute(
            text("SELECT DISTINCT embedding_model FROM doc_chunks")
        )
    except ProgrammingError as exc:
        # doc_chunks lives in init.sql, which runs only on an empty data directory. On a
        # volume created before pgvector, the table is simply absent. That is a known
        # pre-rebuild state with a documented fix, not an unhandled error.
        raise RetrievalError(
            "doc_chunks does not exist. `CREATE EXTENSION vector` and this table are "
            "created by init.sql, which runs only on an empty volume -- see "
            "docs/rag-corpus-design.md section 8 for the rebuild sequence.",
            status_code=503,
        ) from exc

    stored = [r[0] for r in rows]
    if not stored:
        return  # Empty corpus is a valid state; the caller reports zero results.

    mismatched = [m for m in stored if m != EMBEDDING_MODEL]
    if mismatched:
        raise RetrievalError(
            f"doc_chunks holds vectors from {mismatched!r} but EMBEDDING_MODEL is "
            f"{EMBEDDING_MODEL!r}. These vector spaces are not comparable. Re-index "
            f"with `make reindex` or restore the previous model.",
            status_code=503,
        )
    _model_check_passed = True


async def embed_query(query: str) -> list[float]:
    """Embed a query. `kind='query'` is what applies the BGE instruction prefix, and
    the embeddings service owns that prefix so there is one place to get it right."""
    try:
        async with httpx.AsyncClient(timeout=EMBEDDINGS_TIMEOUT_S) as http:
            resp = await http.post(
                f"{EMBEDDINGS_URL}/embed",
                json={"texts": [query], "kind": "query"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError as exc:
        raise RetrievalError(
            f"embeddings service unreachable at {EMBEDDINGS_URL}: {exc}. "
            f"mode=lexical still works without it.",
            status_code=503,
        ) from exc

    if payload["model"] != EMBEDDING_MODEL:
        raise RetrievalError(
            f"embeddings service is serving {payload['model']!r} but this API is "
            f"configured for {EMBEDDING_MODEL!r}.",
            status_code=503,
        )
    return payload["embeddings"][0]


def to_pgvector(vector: list[float]) -> str:
    """pgvector's text input format. asyncpg has no codec for the `vector` type, so the
    value crosses as text and is cast in SQL. Cheaper than registering a codec, and it
    keeps the SQL readable in EXPLAIN output."""
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


_DENSE_SQL = text("""
    SELECT id, source_type, source_id, heading_path, content, token_count,
           generated_at,
           1 - (embedding <=> CAST(:qvec AS vector)) AS cosine_similarity
      FROM doc_chunks
     WHERE (CAST(:source_type AS VARCHAR) IS NULL OR source_type = CAST(:source_type AS VARCHAR))
     -- ORDER BY on the raw distance operator, not on the derived similarity above.
     -- HNSW can only answer `embedding <=> const`; ordering by `1 - (...)` DESC is
     -- mathematically identical and silently falls back to a sequential scan.
     ORDER BY embedding <=> CAST(:qvec AS vector)
     LIMIT :k
""")

# websearch_to_tsquery over plainto_tsquery: it accepts quoted phrases, OR and leading
# `-` from a user without raising, and it never throws on punctuation. plainto_ would
# silently drop the phrase semantics; to_tsquery would raise on a bare apostrophe.
_LEXICAL_SQL = text("""
    SELECT id, source_type, source_id, heading_path, content, token_count,
           generated_at,
           ts_rank_cd(tsv, websearch_to_tsquery('english', :q)) AS lexical_score
      FROM doc_chunks
     WHERE tsv @@ websearch_to_tsquery('english', :q)
       AND (CAST(:source_type AS VARCHAR) IS NULL OR source_type = CAST(:source_type AS VARCHAR))
     ORDER BY lexical_score DESC, id
     LIMIT :k
""")


async def dense_search(
    conn: AsyncConnection, qvec: list[float], k: int, source_type: str | None = None
) -> list[dict]:
    rows = await conn.execute(
        _DENSE_SQL, {"qvec": to_pgvector(qvec), "k": k, "source_type": source_type}
    )
    return [dict(r._mapping) for r in rows]


# Query relaxation, and why the strict form is not enough on its own.
#
# `websearch_to_tsquery` CONJOINS unquoted terms: "Which areas border Business Bay"
# becomes `'area' & 'border' & 'busi' & 'bay'`, and a chunk missing any one stem is
# excluded outright. On a 304-chunk corpus that is fatal rather than selective --
# measured in m13a, the strict query matched **zero chunks for 5 of the 10 golden
# questions**, so the lexical arm contributed nothing at all to half the fusions.
#
# The first run of Experiment 3 could not see this. The eval questions were themselves
# indexed, so every conjunction was satisfied by the document containing the question,
# and the arm looked like it was working.
#
# The relaxation turns the top-level `&` into `|` by rewriting the parsed tsquery's text
# form, so Postgres' own parser still does the parsing and phrase groups (`<->`) survive
# intact. `ts_rank_cd` then does what it is for: rank documents by how many of the terms
# they carry and how close together.
#
# It runs ONLY when the strict query returns nothing, and ONLY when lexical is the sole
# arm. Both restrictions were measured, and the second one was a surprise.
#
# Relaxing inside `mode=hybrid` makes hybrid WORSE: top-1 on the golden set fell from
# 7/10 to 5/10, because the relaxed arm stops returning nothing and starts returning a
# confidently wrong document at rank 1, which RRF then weights equally with a dense
# ranking that was right. Recall improved and precision@1 collapsed, and fusion has no
# notion of which arm to trust -- the same failure as the contaminated run, reached from
# the opposite direction.
#
# The rule that falls out is clean: the fallback exists so the no-model path returns
# SOMETHING, and in hybrid the dense arm already guarantees that. There is nothing for it
# to fix there, and it does measurable harm, so it does not run there.
#
# Relaxing whenever the result set is merely smaller than k would additionally change the
# ranking of queries that already work, to chase a recall number this corpus has not
# shown a need for.
#
# Known edge: a negated term (`-word` -> `!'word'`) becomes an OR-ed negation under the
# rewrite, which matches broadly. Acceptable because it only ever fires on a query that
# matched nothing at all, where "broad" beats "empty".
_LEXICAL_RELAXED_SQL = text("""
    WITH q AS (
        SELECT replace(
                 websearch_to_tsquery('english', :q)::text, ' & ', ' | '
               )::tsquery AS tsq
    )
    SELECT c.id, c.source_type, c.source_id, c.heading_path, c.content, c.token_count,
           c.generated_at,
           ts_rank_cd(c.tsv, q.tsq) AS lexical_score
      FROM doc_chunks c, q
     WHERE c.tsv @@ q.tsq
       AND (CAST(:source_type AS VARCHAR) IS NULL OR c.source_type = CAST(:source_type AS VARCHAR))
     ORDER BY lexical_score DESC, c.id
     LIMIT :k
""")


async def lexical_search(
    conn: AsyncConnection,
    query: str,
    k: int,
    source_type: str | None = None,
    *,
    allow_relaxation: bool = False,
) -> tuple[list[dict], bool]:
    """Returns (rows, relaxed). `relaxed` is reported, never hidden: a caller comparing
    retrieval modes needs to know which query actually ran."""
    rows = await conn.execute(
        _LEXICAL_SQL, {"q": query, "k": k, "source_type": source_type}
    )
    strict = [dict(r._mapping) for r in rows]
    if strict or not allow_relaxation:
        return strict, False

    rows = await conn.execute(
        _LEXICAL_RELAXED_SQL, {"q": query, "k": k, "source_type": source_type}
    )
    return [dict(r._mapping) for r in rows], True


def fuse_rrf(rankings: dict[str, list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion over 1-based ranks.

        score(d) = sum over arms a where d appears of  1 / (k + rank_a(d))

    Pure, and kept pure on purpose: this is the one piece of the pipeline whose
    behaviour can be asserted exactly, without a database, a model or a network call.
    api/tests/test_retrieval.py pins the arithmetic against hand-computed values.

    `k` damps the top of each list. At k=60 the gap between rank 1 and rank 2 is
    1/61 - 1/62 = 0.00026, so a chunk ranked 2nd by BOTH arms outranks one ranked 1st by
    only one arm -- which is the whole point of fusing rather than concatenating.
    """
    scores: dict[int, float] = {}
    for ids in rankings.values():
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


async def rerank(query: str, documents: list[str]) -> list[float]:
    try:
        async with httpx.AsyncClient(timeout=EMBEDDINGS_TIMEOUT_S) as http:
            resp = await http.post(
                f"{EMBEDDINGS_URL}/rerank",
                json={"query": query, "documents": documents},
            )
            resp.raise_for_status()
            return resp.json()["scores"]
    except httpx.HTTPError as exc:
        raise RetrievalError(
            f"reranker unreachable at {EMBEDDINGS_URL}: {exc}", status_code=503
        ) from exc


async def search(
    conn: AsyncConnection,
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int,
    limit: int,
    do_rerank: bool = True,
    source_type: str | None = None,
) -> tuple[list[dict], dict[str, int], int, bool]:
    """Run the pipeline. Returns (results, timings_ms, candidates_considered, relaxed).

    `mode` is not a user-facing toggle. It exists so the ablation in m16 -- dense-only
    vs lexical-only vs hybrid, with and without reranking -- is a set of API calls
    rather than four code branches maintained in a benchmark script.
    """
    timings = {"embed": 0, "dense": 0, "lexical": 0, "fuse": 0, "rerank": 0, "total": 0}
    started = time.perf_counter()

    def elapsed_since(mark: float) -> int:
        return int((time.perf_counter() - mark) * 1000)

    await assert_embedding_model(conn)

    by_id: dict[int, dict] = {}
    rankings: dict[str, list[int]] = {}

    if mode in ("dense", "hybrid"):
        mark = time.perf_counter()
        qvec = await embed_query(query)
        timings["embed"] = elapsed_since(mark)

        mark = time.perf_counter()
        dense_rows = await dense_search(conn, qvec, top_k, source_type)
        timings["dense"] = elapsed_since(mark)

        rankings["dense"] = [r["id"] for r in dense_rows]
        for rank, row in enumerate(dense_rows, start=1):
            entry = by_id.setdefault(row["id"], dict(row))
            entry["dense_rank"] = rank
            entry["cosine_similarity"] = float(row["cosine_similarity"])

    lexical_relaxed = False
    if mode in ("lexical", "hybrid"):
        mark = time.perf_counter()
        lexical_rows, lexical_relaxed = await lexical_search(
            conn, query, top_k, source_type, allow_relaxation=(mode == "lexical")
        )
        timings["lexical"] = elapsed_since(mark)

        rankings["lexical"] = [r["id"] for r in lexical_rows]
        for rank, row in enumerate(lexical_rows, start=1):
            entry = by_id.setdefault(row["id"], dict(row))
            entry["lexical_rank"] = rank
            entry["lexical_score"] = float(row["lexical_score"])

    mark = time.perf_counter()
    fused = fuse_rrf(rankings)
    for chunk_id, score in fused.items():
        by_id[chunk_id]["rrf"] = score
    ordered = sorted(
        by_id.values(),
        # Tie-break on id so a fused list with equal scores is stable across runs. An
        # unstable order makes the m16 regression gate flap for no reason.
        key=lambda r: (-r.get("rrf", 0.0), r["id"]),
    )
    timings["fuse"] = elapsed_since(mark)
    candidates = len(ordered)

    if do_rerank and ordered:
        mark = time.perf_counter()
        scores = await rerank(query, [r["content"] for r in ordered])
        for row, score in zip(ordered, scores, strict=True):
            row["rerank"] = float(score)
        ordered.sort(key=lambda r: (-r["rerank"], r["id"]))
        timings["rerank"] = elapsed_since(mark)

    timings["total"] = elapsed_since(started)
    return ordered[:limit], timings, candidates, lexical_relaxed


async def explain_plans(
    conn: AsyncConnection, query: str, qvec: list[float] | None, top_k: int
) -> dict[str, list[str]]:
    """EXPLAIN (ANALYZE, BUFFERS) for both arms.

    Exists because of the precedent in docs/postgis-query-plans.md: a GiST index made a
    222-row lookup SLOWER than the sequential scan it replaced. The corpus here is the
    same order of magnitude, so whether HNSW earns its place is an open question, and
    the answer belongs in the repository rather than in a claim.
    """
    plans: dict[str, list[str]] = {}

    if qvec is not None:
        rows = await conn.execute(
            text(
                "EXPLAIN (ANALYZE, BUFFERS) "
                + str(_DENSE_SQL).replace(":qvec", "'" + to_pgvector(qvec) + "'")
                .replace(":k", str(top_k))
                .replace(":source_type", "NULL")
            )
        )
        plans["dense"] = [r[0] for r in rows]

    rows = await conn.execute(
        text(
            "EXPLAIN (ANALYZE, BUFFERS) "
            + str(_LEXICAL_SQL).replace(":q", "'" + query.replace("'", "''") + "'")
            .replace(":k", str(top_k))
            .replace(":source_type", "NULL")
        )
    )
    plans["lexical"] = [r[0] for r in rows]
    return plans
