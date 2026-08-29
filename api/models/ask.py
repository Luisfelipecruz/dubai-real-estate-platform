"""Request and response shapes for `POST /ask`.

Two kinds of model live here and the split matters.

`GroundedAnswer` and `Citation` are what the LLM is asked to produce. Their field
descriptions are not documentation -- they are shipped to the model inside the JSON
Schema and they are part of the prompt, so they are written to be read by the thing
generating the object.

Everything else is what the API returns, which is the model's answer AFTER it has been
checked: citations resolved against the chunks actually retrieved, quotes located in the
chunk text, confidence downgraded where the grounding did not hold. The distinction is
the point of the endpoint. A system that returns the model's own claim about its
citations has not verified anything.
"""

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


# ── what the model produces ─────────────────────────────────────────────────


class Citation(BaseModel):
    """One piece of evidence. A chunk id and the exact words relied on."""

    chunk_id: int = Field(
        ...,
        description="The chunk_id of the context block this claim came from, exactly as "
        "it appears in the CONTEXT section. Never invent one.",
    )
    quote: str = Field(
        ...,
        description="A short span copied VERBATIM from that chunk -- the words that "
        "support the claim. Copy, do not paraphrase: this quote is checked against the "
        "chunk text and a paraphrase will fail the check.",
    )


class GroundedAnswer(BaseModel):
    """The structured answer. Parsed, never regex-scraped.

    `unanswerable_reason` is load-bearing rather than decorative. Retrieval on this
    corpus misses roughly one question in ten -- two of the ten golden questions have no
    retrievable answer at any k in any mode -- so a system with no way to say "the
    context does not contain this" is not merely imperfect, it is guaranteed to invent
    an answer on those. m16 measures the abstention rate directly.
    """

    answer: str = Field(
        ...,
        description="The answer, grounded ONLY in the context provided. If the context "
        "does not support an answer, leave this empty and set unanswerable_reason.",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="One entry per claim that rests on the context. Empty is correct "
        "when the answer is a refusal.",
    )
    confidence: Confidence = Field(
        ...,
        description="high = the context states this directly; medium = it follows from "
        "the context but is not stated; low = the context is only tangentially related.",
    )
    unanswerable_reason: str | None = Field(
        None,
        description="Set to a one-sentence explanation when the context does not "
        "support an answer, and leave `answer` empty. Null otherwise. Refusing is a "
        "correct outcome, not a failure.",
    )


# ── what the API returns ────────────────────────────────────────────────────


class ResolvedCitation(BaseModel):
    """A citation after checking, not as claimed.

    `resolved` and `quote_found` are separate because they fail for different reasons and
    mean different things. An unresolved chunk_id is a fabricated source. A resolved id
    with a quote that is not in the chunk is a paraphrase presented as a quotation --
    much more common, much easier to miss, and the reason the quote is checked at all.
    """

    chunk_id: int
    quote: str
    resolved: bool = Field(
        ..., description="chunk_id was in the set of chunks actually retrieved."
    )
    quote_found: bool = Field(
        ..., description="The quote appears verbatim in that chunk's stored content."
    )
    source_type: str | None = None
    source_id: str | None = None
    heading_path: str | None = None


class AskContext(BaseModel):
    """A retrieved chunk, as it was handed to the model.

    Returned in full. An /ask response that shows the answer but not the evidence cannot
    be audited by the person reading it, and this endpoint's entire claim is that the
    answer is checkable.
    """

    chunk_id: int
    source_type: str
    source_id: str
    heading_path: str | None
    content: str
    token_count: int
    cosine_similarity: float | None = None
    echoes_question: bool = Field(
        False,
        description="This chunk contains the question's own words nearly verbatim. Not "
        "evidence: a chunk that RESTATES a question is what a cross-encoder promotes and "
        "what an LLM will happily write an answer around. Flagged, not removed.",
    )


class AskUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    estimated_input_tokens: int = Field(
        0,
        description="What the budget guard computed BEFORE the call, from the same "
        "WordPiece estimator the chunker uses. Reported next to the provider's real "
        "count so the estimator's error is visible rather than assumed.",
    )
    cost_usd: float | None = Field(
        None, description="Null when the model is not in the rate table. Not zero."
    )
    cost_priced: bool = Field(
        ..., description="False means unpriced, which is visibly different from $0.00."
    )
    repair_attempts: int = Field(
        0, description="Invalid-JSON retries before this answer. Capped; see settings."
    )


class AskTimings(BaseModel):
    retrieve: int = 0
    generate: int = 0
    total: int = 0


class AskRetrieval(BaseModel):
    mode: str
    reranked: bool
    k: int
    candidates_considered: int
    lexical_relaxed: bool = False


class AskResponse(BaseModel):
    query: str
    provider: str
    model: str
    answered: bool = Field(
        ...,
        description="False when the system refused. A refusal is a successful 200, not "
        "an error: two of the ten golden questions have no retrievable answer, and "
        "reporting that as a 5xx would make an honest outcome look like a fault.",
    )
    answer: str | None
    unanswerable_reason: str | None
    confidence: Confidence
    citations: list[ResolvedCitation]
    grounding_warnings: list[str] = Field(
        default_factory=list,
        description="What did not hold. Present and empty on a clean answer; never "
        "silently dropped, because the confidence downgrade alone does not say why.",
    )
    contexts: list[AskContext]
    retrieval: AskRetrieval
    usage: AskUsage
    timings_ms: AskTimings
    request_id: str | None = None
