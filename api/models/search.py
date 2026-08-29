from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["dense", "lexical", "hybrid"]


class ChunkScores(BaseModel):
    """Every score that contributed to this result's position, kept separately.

    Not debug output. Reporting a single blended number makes it impossible to say why
    a chunk surfaced, and the ablation in m16 is exactly the question of which arm was
    responsible. Ranks are 1-based; None means that arm did not return this chunk at all.
    """

    dense_rank: int | None = None
    lexical_rank: int | None = None
    cosine_similarity: float | None = Field(
        None, description="1 - cosine distance. Only present when the dense arm ran."
    )
    lexical_score: float | None = Field(
        None, description="ts_rank_cd. Not comparable with cosine_similarity -- which "
        "is precisely why fusion is done on ranks (RRF) rather than on scores."
    )
    rrf: float | None = Field(
        None, description="Sum of 1/(k + rank) across the arms that returned this chunk."
    )
    rerank: float | None = Field(
        None, description="Cross-encoder logit. Present only when rerank=true."
    )


class SearchResult(BaseModel):
    chunk_id: int
    source_type: str = Field(..., description="doc | area_sheet | note")
    source_id: str
    heading_path: str | None
    content: str
    token_count: int
    generated_at: str | None = Field(
        None,
        description="When this chunk was indexed. For area_sheet rows this is also when "
        "the underlying aggregates were read, so staleness is detectable rather than "
        "assumed.",
    )
    scores: ChunkScores


class SearchTimings(BaseModel):
    """Per-stage timings, in the response body from the first commit.

    Adding these later would mean guessing at the latency budget the voice path (m17)
    has to fit inside. Having them from the start makes that budget a measurement.
    """

    embed: int = 0
    dense: int = 0
    lexical: int = 0
    fuse: int = 0
    rerank: int = 0
    total: int = 0


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    reranked: bool
    candidates_considered: int = Field(
        ..., description="Distinct chunks after fusion, before the top-k cut."
    )
    embedding_model: str
    results: list[SearchResult]
    lexical_relaxed: bool = False
    """True when the strict conjunctive tsquery matched nothing and the OR-ed fallback
    ran instead. Reported rather than hidden: two runs of the same query can take
    different lexical paths, and a quality comparison that cannot see which one ran is
    comparing two different systems."""

    timings_ms: SearchTimings
