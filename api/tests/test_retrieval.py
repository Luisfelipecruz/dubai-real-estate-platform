"""Retrieval tests.

Split deliberately into two halves.

The **pure** half pins the fusion arithmetic. RRF is the one part of the pipeline whose
behaviour can be asserted exactly, with no database, no model and no network -- so it is,
against hand-computed values rather than a golden file that could drift with the code.

The **integration** half runs against the live stack and skips when the corpus is empty
or the embeddings service is down. Those are real configurations, not broken ones:
mode=lexical is expected to work with no model running at all, and the 27 core
operations have no dependency on any of this.
"""

import pytest

from services.retrieval import fuse_rrf, to_pgvector


# ── Fusion arithmetic (pure) ────────────────────────────────────────────────


def test_rrf_matches_hand_computed_scores():
    """score(d) = sum over arms where d appears of 1 / (k + rank), ranks 1-based."""
    scores = fuse_rrf({"dense": [10, 20, 30], "lexical": [20, 40]}, k=60)

    assert scores[10] == pytest.approx(1 / 61)
    assert scores[20] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[30] == pytest.approx(1 / 63)
    assert scores[40] == pytest.approx(1 / 62)


def test_rrf_rewards_agreement_over_a_single_strong_hit():
    """This is the whole reason for fusing rather than concatenating: a chunk both arms
    rank 2nd should beat one that only a single arm ranks 1st."""
    scores = fuse_rrf({"dense": [1, 2], "lexical": [3, 2]}, k=60)
    assert scores[2] > scores[1]
    assert scores[2] > scores[3]


def test_rrf_preserves_order_within_a_single_arm():
    scores = fuse_rrf({"dense": [7, 8, 9]}, k=60)
    assert scores[7] > scores[8] > scores[9]


def test_rrf_ignores_absolute_scores_entirely():
    """The point of fusing on RANKS: cosine similarity and ts_rank_cd are on
    incomparable scales, and any weighted blend needs a constant that has to be
    re-tuned whenever either side changes. RRF cannot see a score at all."""
    a = fuse_rrf({"dense": [5, 6]}, k=60)
    b = fuse_rrf({"lexical": [5, 6]}, k=60)
    assert a == b


def test_rrf_k_damps_the_top_of_each_list():
    """Small k makes rank 1 dominant; large k flattens the list. Both are defensible
    and the value is measured in m16, not inherited on faith."""
    tight = fuse_rrf({"dense": [1, 2]}, k=1)
    flat = fuse_rrf({"dense": [1, 2]}, k=1000)
    assert tight[1] / tight[2] > flat[1] / flat[2]


def test_rrf_of_nothing_is_nothing():
    assert fuse_rrf({}) == {}
    assert fuse_rrf({"dense": []}) == {}


def test_pgvector_literal_format():
    """asyncpg has no codec for the `vector` type, so the value crosses as text and is
    cast in SQL. The format is not negotiable -- pgvector parses it strictly."""
    assert to_pgvector([1.0, -0.5, 0.25]) == "[1,-0.5,0.25]"


# ── Endpoint behaviour (integration) ────────────────────────────────────────


async def corpus_is_populated(client) -> bool:
    resp = await client.get("/search/corpus")
    return resp.status_code == 200 and resp.json()["total_chunks"] > 0


async def test_corpus_stats_reports_the_configured_model(client):
    resp = await client.get("/search/corpus")
    if resp.status_code == 503:
        # doc_chunks is created by init.sql, which runs only on an empty data directory.
        # Before the pgvector rebuild the table does not exist, and that is a documented
        # state with a fix -- not a regression this suite should report as one.
        pytest.skip(resp.json()["detail"])

    assert resp.status_code == 200
    body = resp.json()
    assert "configured_embedding_model" in body
    # A False here means every stored vector is in a different space from every query
    # vector, and /search would be returning confident nonsense. It is the single most
    # important boolean in the retrieval layer.
    assert body["model_matches"] is True


async def test_search_rejects_an_unknown_mode(client):
    resp = await client.get("/search", params={"q": "rent contracts", "mode": "magic"})
    assert resp.status_code == 422


async def test_search_requires_a_query(client):
    resp = await client.get("/search", params={"q": "a"})
    assert resp.status_code == 422


async def test_lexical_search_needs_no_model(client):
    """The degradation contract: with the embeddings service stopped, half of retrieval
    keeps working. Asserted here because it is the difference between a stack that
    needs 14 GB of models to boot and one that does not."""
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    resp = await client.get(
        "/search", params={"q": "rent contract deduplication", "mode": "lexical",
                           "rerank": "false"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "lexical"
    assert body["timings_ms"]["embed"] == 0, "lexical mode called the embedder"
    for result in body["results"]:
        assert result["scores"]["lexical_rank"] is not None
        assert result["scores"]["dense_rank"] is None


async def test_hybrid_search_reports_per_stage_timings(client):
    """Timings are in the response body from the first commit, not added later. The
    voice latency budget in m17 is built on these numbers; guessing at them is how a
    budget becomes a hope."""
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    resp = await client.get(
        "/search",
        params={"q": "how are rent contracts deduplicated", "mode": "hybrid"},
    )
    if resp.status_code == 503:
        pytest.skip(f"embeddings service unavailable: {resp.json()['detail']}")

    assert resp.status_code == 200
    timings = resp.json()["timings_ms"]
    assert timings["embed"] > 0
    assert timings["total"] >= timings["embed"] + timings["dense"]


async def test_source_type_filter_restricts_the_corpus(client):
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    resp = await client.get(
        "/search",
        params={"q": "median price", "mode": "lexical", "rerank": "false",
                "source_type": "doc"},
    )
    assert resp.status_code == 200
    assert all(r["source_type"] == "doc" for r in resp.json()["results"])


async def test_search_returns_at_most_k(client):
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    resp = await client.get(
        "/search", params={"q": "index", "mode": "lexical", "rerank": "false", "k": 3}
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 3


# ── The defaults, which are measurements rather than preferences ────────────


async def test_the_default_mode_is_dense_and_the_default_is_not_reranked(client):
    """Pinned because both defaults CHANGED in m13a, on evidence, and a silent revert
    would be invisible: every other test still passes under the old defaults.

    Measured on the golden set once the eval questions were outside the corpus
    (docs/hybrid-retrieval-plans.md, Experiment 3 run 2):

        dense,  no rerank   top-1 8/10   recall@5 9/10      67 ms p50
        hybrid, no rerank   top-1 7/10   recall@5 9/10      67 ms p50
        dense,  rerank      top-1 3/10   recall@5 6/10   2,944 ms p50

    Hybrid never won at any k. The cross-encoder cost 44x the latency and lost five of
    eight correct top-1 answers.
    """
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    resp = await client.get("/search", params={"q": "how are rent contracts deduplicated"})
    if resp.status_code == 503:
        pytest.skip(f"embeddings service unavailable: {resp.json()['detail']}")

    body = resp.json()
    assert body["mode"] == "dense", "the default mode changed without the numbers changing"
    assert body["reranked"] is False, "the cross-encoder is opt-in; it costs 2.9 s"
    assert body["timings_ms"]["rerank"] == 0
    assert body["timings_ms"]["lexical"] == 0, "dense mode ran the lexical arm"


async def test_lexical_relaxes_exactly_when_the_strict_query_matches_nothing(client):
    """`websearch_to_tsquery` ANDs its terms, so a natural-language question is a
    conjunction over 4-6 stems and one missing stem returns an empty set -- measured at
    zero chunks for 5 of the 10 golden questions. The fallback ORs the terms.

    REWRITTEN IN m16, AND THE REASON IS THE POINT. The original pinned one question: the
    fact sheets say "shares a boundary with", the question says "border", and no chunk
    contained both that stem and the area name, so strict matched nothing and the fallback
    ran. That held until `make index` picked up m15's write-up, whose opening paragraph
    contains both -- and the test failed with the exact sentence its own error message had
    predicted: "the corpus gained a chunk containing both".

    A test whose premise is a fact about a corpus that grows every time someone documents
    the system is a test with a shelf life. So it now asserts the INVARIANT rather than
    one instance of it: the relaxation fires if and only if the strict conjunctive query
    matched nothing. That is true whatever the corpus contains, and it still fails if the
    fallback is wired to the wrong condition -- which is what the original was protecting.

    The strict count is taken from Postgres directly, because `/search` reports only
    whether the fallback ran and not what the strict arm found.
    """
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from config import DATABASE_URL

    question = "Which areas border Business Bay?"
    resp = await client.get(
        "/search",
        params={"q": question, "mode": "lexical", "rerank": "false"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # NullPool for the same reason test_corpus_isolation.py uses it: the shared engine
    # pools connections and pytest-asyncio gives every test its own loop.
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            strict = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM doc_chunks "
                        "WHERE tsv @@ websearch_to_tsquery('english', :q)"
                    ),
                    {"q": question},
                )
            ).scalar()
    finally:
        await engine.dispose()

    assert body["lexical_relaxed"] is (strict == 0), (
        f"strict conjunctive query matched {strict} chunk(s) but lexical_relaxed="
        f"{body['lexical_relaxed']}. The fallback must run when strict finds nothing "
        f"and must not run when it finds something."
    )
    assert body["results"], "the lexical arm returned nothing at all"


async def test_hybrid_does_not_relax_its_lexical_arm(client):
    """Relaxing inside hybrid dropped top-1 from 7/10 to 5/10: the relaxed arm stops
    returning nothing and starts returning a confidently wrong document at rank 1, which
    RRF weights equally with a dense ranking that was right. The dense arm already
    guarantees a non-empty result, so the fallback has no job there."""
    if not await corpus_is_populated(client):
        pytest.skip("corpus not indexed - run `make index`")

    resp = await client.get(
        "/search",
        params={"q": "Which areas border Business Bay?", "mode": "hybrid",
                "rerank": "false"},
    )
    if resp.status_code == 503:
        pytest.skip(f"embeddings service unavailable: {resp.json()['detail']}")

    assert resp.json()["lexical_relaxed"] is False
