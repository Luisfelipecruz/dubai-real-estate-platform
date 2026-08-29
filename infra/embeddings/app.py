"""Embedding and reranking service.

Two models, two very different jobs:

  bi-encoder  (BAAI/bge-small-en-v1.5)   query and document embedded INDEPENDENTLY,
                                         so vectors can be precomputed and indexed.
  cross-encoder (BAAI/bge-reranker-base) query and document read TOGETHER, so it
                                         models interaction and cannot be indexed.

The bi-encoder runs over the whole corpus at index time. The cross-encoder runs over
at most a few dozen candidates at query time. Using either in the other's place is the
classic mistake: a cross-encoder over 4,000 chunks per query is minutes, and a
bi-encoder as a final ranker leaves accuracy on the table.

The BGE asymmetric prefix lives HERE rather than in the caller. Queries must be
embedded with an instruction prefix and documents must not; getting it backwards, or
forgetting it, costs 5-10 points of recall with no error raised anywhere. Centralising
it means there is exactly one place to get it right, and GET /health publishes the
exact string so a test can assert on it rather than trusting this comment.
"""

import os
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")

# The prefix BAAI publishes for bge-*-en-v1.5 retrieval. Documents get no prefix.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Loaded lazily on first use rather than at import. The container answers /health
# immediately and reports ready=false while the weights download, which keeps a cold
# start from looking like a crashed service to compose's healthcheck.
_encoder = None
_reranker = None

app = FastAPI(title="Embeddings", version="0.1.0")


def get_encoder():
    global _encoder
    if _encoder is None:
        from sentence_transformers import SentenceTransformer

        _encoder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    return _encoder


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANKER_MODEL, device="cpu")
    return _reranker


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    kind: Literal["query", "document"] = Field(
        "document",
        description="'query' applies the BGE instruction prefix; 'document' does not. "
        "Asymmetric by design -- see the module docstring.",
    )


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    embeddings: list[list[float]]
    token_counts: list[int] = Field(
        ...,
        description="Counted by the model's own tokenizer, before truncation. The "
        "chunker upstream uses a cheap word-based estimate to pick boundaries; this is "
        "what the tokenizer actually saw, and it is what gets stored.",
    )
    truncated: list[bool] = Field(
        ...,
        description="True where the input exceeded the model's max sequence length and "
        "the tail was silently dropped. Silent truncation is how a chunking bug hides.",
    )
    elapsed_ms: int


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(..., min_length=1)


class RerankResponse(BaseModel):
    model: str
    scores: list[float]
    elapsed_ms: int


@app.get("/health")
async def health():
    """Reports readiness AND configuration.

    The prefix and dimensions are in the payload so callers and tests can assert on
    the live configuration instead of a constant copied into three repositories.
    """
    return {
        "status": "ok",
        "embedding_model": EMBEDDING_MODEL,
        "reranker_model": RERANKER_MODEL,
        "query_prefix": QUERY_PREFIX,
        "encoder_loaded": _encoder is not None,
        "reranker_loaded": _reranker is not None,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    started = time.perf_counter()
    encoder = get_encoder()

    texts = (
        [QUERY_PREFIX + t for t in req.texts] if req.kind == "query" else list(req.texts)
    )

    tokenizer = encoder.tokenizer
    max_len = encoder.max_seq_length
    encoded = tokenizer(texts, add_special_tokens=True, truncation=False)["input_ids"]
    token_counts = [len(ids) for ids in encoded]
    truncated = [n > max_len for n in token_counts]

    vectors = encoder.encode(
        texts,
        normalize_embeddings=True,  # cosine distance in pgvector assumes unit norm
        batch_size=32,
        show_progress_bar=False,
    )

    return EmbedResponse(
        model=EMBEDDING_MODEL,
        dimensions=int(vectors.shape[1]),
        embeddings=vectors.tolist(),
        token_counts=token_counts,
        truncated=truncated,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    if len(req.documents) > 100:
        # A cross-encoder is O(candidates) forward passes. 100 on CPU is already
        # seconds; refusing is better than blowing the caller's latency budget.
        raise HTTPException(
            status_code=422,
            detail=f"rerank accepts at most 100 documents, got {len(req.documents)}",
        )

    started = time.perf_counter()
    scores = get_reranker().predict(
        [(req.query, doc) for doc in req.documents],
        batch_size=16,
        show_progress_bar=False,
    )
    return RerankResponse(
        model=RERANKER_MODEL,
        scores=[float(s) for s in scores],
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
