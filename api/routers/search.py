"""Retrieval endpoints.

`GET /search` is the retrieval layer on its own, with no model in front of it. That
separation is the point: it makes retrieval quality measurable independently of
generation quality, so when an answer is wrong in m14 there is a way to tell whether
the retriever found the wrong thing or the model ignored the right thing.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from config import (
    EMBEDDING_MODEL,
    RERANK_TOP_N,
    RETRIEVAL_TOP_K,
)
from database import engine
from models.search import (
    ChunkScores,
    SearchResponse,
    SearchResult,
    SearchTimings,
)
from services import retrieval

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2, description="Natural-language query"),
    k: int = Query(RERANK_TOP_N, ge=1, le=50, description="Results to return"),
    # BOTH DEFAULTS CHANGED IN m13a, and both were changed because they were measured
    # rather than because anything felt wrong. The numbers are in
    # docs/hybrid-retrieval-plans.md, Experiment 3 run 2, on a corpus with the eval
    # questions finally outside it. n=10 questions, so read them as a strong signal on
    # this corpus, not as a law.
    #
    #                      top-1 ideal      recall@5     p50 latency
    #   dense,   no rerank      8/10          9/10           67 ms   <- the new default
    #   hybrid,  no rerank      7/10          9/10           67 ms   <- the old mode
    #   dense,   rerank         3/10          6/10        2,944 ms   <- the old default
    #   hybrid,  rerank         2/10          6/10        2,944 ms
    #
    # mode: hybrid never beat dense at any k in any configuration measured, and lost one
    # position at k=1. RRF has no notion of which arm to trust, and this corpus's lexical
    # arm is weak enough that fusing it in is a cost with no observed benefit. Revisit if
    # the corpus grows exact-match surface -- identifiers, error strings, procedure
    # numbers -- which ten hand-written prose questions do not exercise.
    mode: str = Query("dense", pattern="^(dense|lexical|hybrid)$"),
    # rerank: the cross-encoder costs 2.9 s AND drops top-1 from 8/10 to 3/10. It is the
    # rare change that is both 44x faster and more accurate, so it is opt-in now.
    # See "What the cross-encoder does to ranking" in docs/hybrid-retrieval-plans.md --
    # it is drawn to text that RESEMBLES the question, which on this corpus means the
    # routing tables full of example questions.
    rerank: bool = Query(False, description="Run the cross-encoder over fused candidates"),
    source_type: str | None = Query(
        None,
        pattern="^(doc|area_sheet|note)$",
        description="Restrict to one corpus source.",
    ),
    top_k: int = Query(
        RETRIEVAL_TOP_K, ge=1, le=100, description="Candidates per arm before fusion"
    ),
):
    """Hybrid retrieval over the document corpus.

    **This endpoint does not answer questions about numbers, and must not be used to.**
    "Median price per m2 in Dubai Marina in 2024" is a PERCENTILE_CONT over an indexed
    column -- exact, fast, and already served by `GET /areas/{name}/history`. Routing it
    through a 384-dimensional vector index can only make it wrong, and wrong fluently.
    The corpus here is documentation, generated area fact sheets, and analyst notes;
    see docs/rag-corpus-design.md for the routing table.

    `mode=lexical` is the only mode that works with the embeddings service stopped.
    That is deliberate degradation, not an accident: the platform's 27 core operations
    and half of retrieval keep serving on a machine that cannot host the models.
    """
    async with engine.connect() as conn:
        try:
            rows, timings, candidates, lexical_relaxed = await retrieval.search(
                conn,
                q,
                mode=mode,
                top_k=top_k,
                limit=k,
                do_rerank=rerank,
                source_type=source_type,
            )
        except retrieval.RetrievalError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return SearchResponse(
        query=q,
        mode=mode,
        reranked=rerank and bool(rows),
        candidates_considered=candidates,
        lexical_relaxed=lexical_relaxed,
        embedding_model=EMBEDDING_MODEL,
        results=[
            SearchResult(
                chunk_id=row["id"],
                source_type=row["source_type"],
                source_id=row["source_id"],
                heading_path=row["heading_path"],
                content=row["content"],
                token_count=row["token_count"],
                generated_at=row["generated_at"].isoformat()
                if row.get("generated_at")
                else None,
                scores=ChunkScores(
                    dense_rank=row.get("dense_rank"),
                    lexical_rank=row.get("lexical_rank"),
                    cosine_similarity=row.get("cosine_similarity"),
                    lexical_score=row.get("lexical_score"),
                    rrf=row.get("rrf"),
                    rerank=row.get("rerank"),
                ),
            )
            for row in rows
        ],
        timings_ms=SearchTimings(**timings),
    )


@router.get("/search/corpus")
async def corpus_stats():
    """What is actually indexed, per source.

    Cheap, and the first thing worth checking when retrieval returns nothing: an empty
    corpus and a broken retriever look identical from `/search`.
    """
    async with engine.connect() as conn:
        try:
            await retrieval.assert_embedding_model(conn)
        except retrieval.RetrievalError as exc:
            # Reported, not raised as a 500: this endpoint exists precisely to answer
            # "what is the state of the index", and "not built yet" is an answer.
            if "does not exist" in str(exc):
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        rows = await conn.execute(
            text("""
                SELECT source_type,
                       COUNT(*)                        AS chunks,
                       COUNT(DISTINCT source_id)       AS sources,
                       SUM(token_count)                AS tokens,
                       MIN(token_count)                AS min_tokens,
                       MAX(token_count)                AS max_tokens,
                       ROUND(AVG(token_count))         AS avg_tokens,
                       MIN(generated_at)               AS oldest,
                       MAX(generated_at)               AS newest
                  FROM doc_chunks
                 GROUP BY source_type
                 ORDER BY source_type
            """)
        )
        by_source = [dict(r._mapping) for r in rows]

        models = await conn.execute(
            text("SELECT DISTINCT embedding_model FROM doc_chunks")
        )
        stored_models = [m[0] for m in models]

        size = await conn.execute(
            text("""
                SELECT pg_size_pretty(pg_total_relation_size('doc_chunks')) AS total,
                       pg_size_pretty(pg_relation_size('idx_chunks_hnsw'))  AS hnsw,
                       pg_size_pretty(pg_relation_size('idx_chunks_tsv'))   AS gin
            """)
        )
        sizes = dict(size.one()._mapping)

    return {
        "configured_embedding_model": EMBEDDING_MODEL,
        "stored_embedding_models": stored_models,
        # A mismatch here means every stored vector is in a different space from every
        # query vector. /search raises rather than serving it; this reports it.
        "model_matches": stored_models in ([], [EMBEDDING_MODEL]),
        "total_chunks": sum(r["chunks"] for r in by_source),
        "by_source": by_source,
        "storage": sizes,
    }


@router.get("/search/debug")
async def search_debug(
    q: str = Query(..., min_length=2),
    top_k: int = Query(RETRIEVAL_TOP_K, ge=1, le=100),
):
    """EXPLAIN (ANALYZE, BUFFERS) for both retrieval arms.

    Feeds docs/hybrid-retrieval-plans.md directly. The question it exists to answer is
    whether the HNSW index is used at all at this corpus size, or whether the planner
    prefers a sequential scan -- which is what happened to the GiST index over 222
    community polygons in docs/postgis-query-plans.md.
    """
    qvec = None
    embed_error = None
    try:
        qvec = await retrieval.embed_query(q)
    except retrieval.RetrievalError as exc:
        # The lexical plan is still worth returning with the embedder down.
        embed_error = str(exc)

    async with engine.connect() as conn:
        plans = await retrieval.explain_plans(conn, q, qvec, top_k)

    return {"query": q, "embed_error": embed_error, "plans": plans}
