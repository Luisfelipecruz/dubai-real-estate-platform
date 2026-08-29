"""Corpus isolation — the evaluation set must not be inside the thing it evaluates.

m13 measured retrieval quality against ten questions that were written down in
`docs/hybrid-retrieval-plans.md`, and that file is part of the corpus. So the questions
were indexed alongside the documents they were meant to test, and the lexical arm
returned the eval document itself for 8 of the 10 -- `websearch_to_tsquery` matches a
question against the literal text of that question far better than against any document
that merely answers it. Fusing that arm into RRF made hybrid, the shipped default, worse
than dense alone on 5 of 10.

That class of bug does not announce itself. Nothing crashes, no test goes red, and the
numbers look good -- better than they should, which is the tell nobody checks. So it
gets a test rather than a paragraph.

The fix these tests lock in is structural, not a filter: `build_corpus.py` globs
`docs/*.md`, and the golden set lives in `eval/`, which is not under `docs/`. There is
nothing to remember at build time.
"""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from config import DATABASE_URL

# /app/eval in the test container (docker-compose mounts ./eval read-only), and
# <repo>/eval when pytest is run from a checkout. Both, because this test is the one
# that must not be quietly skipped.
GOLDEN_CANDIDATES = (
    Path(__file__).resolve().parents[1] / "eval" / "golden" / "retrieval.yaml",
    Path(__file__).resolve().parents[2] / "eval" / "golden" / "retrieval.yaml",
)


def golden_path() -> Path:
    for candidate in GOLDEN_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "eval/golden/retrieval.yaml not found in "
        + " or ".join(str(c) for c in GOLDEN_CANDIDATES)
        + ". If this is the container, ./eval is not mounted -- see the `test` service "
        "in docker-compose.yml. Do not 'fix' this by skipping the test."
    )


def load_golden() -> list[dict]:
    return yaml.safe_load(golden_path().read_text(encoding="utf-8"))["questions"]


def like_literal(value: str) -> str:
    r"""Escape LIKE metacharacters so the match is verbatim.

    `no_of_prop` is in G-02 and `_` is a single-character wildcard, so without this the
    pattern is looser than the claim the test is making. Looser would still catch a real
    leak, but a test whose assertion is vaguer than its docstring is how a suite starts
    lying, and the escaping costs one line.
    """
    for char in ("\\", "%", "_"):
        value = value.replace(char, "\\" + char)
    return value


# A fresh engine per test, with NullPool.
#
# The shared `database.engine` pools connections, and pytest-asyncio gives every test its
# own event loop -- so the second test to borrow a pooled connection gets one bound to a
# dead loop. The first version of this file caught that with a bare `except` and returned
# "corpus not populated", which turned a broken connection into a green skip. A test that
# cannot fail is worse than no test, and that failure mode is the exact thing this file
# was written to catch, one level up.
def _engine():
    return create_async_engine(DATABASE_URL, poolclass=NullPool)


async def fetch_scalars(sql: str, params: dict | None = None) -> list:
    engine = _engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def corpus_is_populated() -> bool:
    """Skips only for the one state that is a migration, not a result: doc_chunks absent
    (it is created by init.sql, which runs on an empty data directory). Every other
    database error propagates and fails the run."""
    try:
        total = await fetch_scalars("SELECT COUNT(*) FROM doc_chunks")
    except ProgrammingError as exc:
        if "doc_chunks" in str(exc) and "does not exist" in str(exc):
            return False
        raise
    return bool(total[0])


# ── The load-bearing one ────────────────────────────────────────────────────


async def test_no_golden_question_appears_in_the_corpus():
    """A question inside the corpus measures self-reference, not recall."""
    if not await corpus_is_populated():
        pytest.skip("corpus not indexed - run `make index`")

    leaked: dict[str, list[str]] = {}
    for case in load_golden():
        needle = like_literal(case["text"].rstrip("?"))
        hits = await fetch_scalars(
            "SELECT DISTINCT source_id FROM doc_chunks "
            " WHERE content      ILIKE :q ESCAPE '\\' "
            "    OR heading_path ILIKE :q ESCAPE '\\' "
            " ORDER BY source_id",
            {"q": f"%{needle}%"},
        )
        if hits:
            leaked[case["id"]] = hits

    assert not leaked, (
        "golden questions are indexed in the corpus they are used to evaluate: "
        + "; ".join(f"{qid} -> {', '.join(srcs)}" for qid, srcs in sorted(leaked.items()))
        + ". Every retrieval score computed against this corpus is meaningless. "
        "The fix is to move the question text out of docs/, not to relax this test."
    )


# ── Structural guarantees, no database required ─────────────────────────────


def test_the_golden_set_is_not_reachable_from_the_indexed_directory():
    """build_corpus.py globs `docs/*.md`. This asserts the layout that makes the leak
    impossible, rather than trusting a deny-list to be maintained."""
    path = golden_path()
    assert "docs" not in path.parts, f"the golden set is under docs/: {path}"
    assert path.suffix != ".md", "a .md golden set in docs/ would be indexed verbatim"


def test_every_golden_question_is_gradeable():
    """A fixture with a missing rubric is worse than no fixture: it produces a number."""
    for case in load_golden():
        assert case["text"].strip(), f"{case['id']} has no question text"
        graded = "relevance" in case or "expect_source_type" in case
        assert graded, (
            f"{case['id']} has neither a relevance map nor an expected source_type, "
            "so nothing can be scored against it"
        )
        for source_id, grade in case.get("relevance", {}).items():
            assert grade in (0, 1, 2, 3), f"{case['id']}: {source_id} graded {grade}"


async def test_graded_documents_exist_in_the_corpus():
    """Catches a stale grade after a document is renamed or a fact sheet drops below the
    MIN_RECORDS_FOR_SHEET floor -- a rubric pointing at nothing scores zero forever and
    looks like a retrieval regression."""
    if not await corpus_is_populated():
        pytest.skip("corpus not indexed - run `make index`")

    indexed = set(await fetch_scalars("SELECT DISTINCT source_id FROM doc_chunks"))

    missing = {
        case["id"]: sorted(set(case.get("relevance", {})) - indexed)
        for case in load_golden()
        if set(case.get("relevance", {})) - indexed
    }
    assert not missing, f"graded source_ids absent from the corpus: {missing}"
