"""The fixtures themselves, checked — because a broken fixture reports a healthy system.

Three fixtures now grade three different things and two of them are joined by id. That
join is exactly the kind of thing that rots silently: rename a question in one file, and
`--suite agent` stops grading its route, prints one fewer line in a table nobody counts,
and the route accuracy goes UP because the hardest linked question left the denominator.

m15 has the canonical example of this failure shape. A refusal detector that never matched
anything reported an abstention rate of zero on three correct refusals, and nothing went
red. So the invariants that hold the harness together get assertions rather than trust.

Everything here is pure file reading except the two corpus-isolation tests at the end,
which are marked and skipped without a database.
"""

from pathlib import Path

import pytest
import yaml

from services.evaluation.numeric import parse_tolerance
from services.evaluation.truth import UnsafeFixtureSQL, check_sql_is_readonly


def _golden(name: str) -> Path:
    """/app/eval in the container, <repo>/eval from a checkout. Both, deliberately.

    Same reasoning as `test_corpus_isolation.py`: this is not a test that should quietly
    skip because a mount is missing.
    """
    for parents in (1, 2):
        candidate = Path(__file__).resolve().parents[parents] / "eval" / "golden" / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"eval/golden/{name} not found. Do not fix this by skipping.")


ANSWERS = yaml.safe_load(_golden("answers.yaml").read_text(encoding="utf-8"))
ROUTING = yaml.safe_load(_golden("routing.yaml").read_text(encoding="utf-8"))
RETRIEVAL = yaml.safe_load(_golden("retrieval.yaml").read_text(encoding="utf-8"))

ANSWER_QUESTIONS = ANSWERS["questions"]
ROUTING_BY_ID = {q["id"]: q for q in ROUTING["questions"]}


# ── the fixtures are what they claim to be ─────────────────────────────────


@pytest.mark.parametrize("fixture", [ANSWERS, ROUTING, RETRIEVAL], ids=["answers", "routing", "retrieval"])
def test_every_fixture_declares_it_was_graded_before_the_run(fixture):
    # Both runners refuse to start without this flag. The flag is a claim a human makes
    # once and the runner cannot verify, which is precisely why it is written down where
    # a reviewer reads it rather than assumed.
    assert fixture.get("graded_before_run", True) is True


def test_answer_ids_are_unique():
    ids = [q["id"] for q in ANSWER_QUESTIONS]
    assert len(ids) == len(set(ids))


def test_every_answer_question_has_a_kind_the_harness_can_grade():
    known = {"count", "money", "ratio", "name_set", "unanswerable"}
    for question in ANSWER_QUESTIONS:
        assert question["kind"] in known, question["id"]


def test_every_tolerance_parses():
    for question in ANSWER_QUESTIONS:
        if "tolerance" in question:
            parse_tolerance(question["tolerance"])


# ── the join to the routing set ────────────────────────────────────────────


def test_linked_questions_have_byte_identical_text():
    """The join that lets one response be graded twice.

    `--suite agent` issues ONE request per question and applies the route grader and the
    answer grader to the same response body. If the texts drift apart, the two graders are
    scoring different questions and the headline finding of this milestone — a route that
    was right while the answer was wrong — becomes a comparison of two unrelated runs.
    """
    linked = [q for q in ANSWER_QUESTIONS if q.get("routing_id")]
    assert linked, "the join is the point; something has removed every routing_id"
    for question in linked:
        routing = ROUTING_BY_ID.get(question["routing_id"])
        assert routing is not None, f"{question['id']} points at a missing routing id"
        assert question["text"] == routing["text"], question["id"]


def test_the_worked_example_is_still_linked():
    # R-05 / A-14 is the reason this file exists at all: it passed the routing eval with
    # an answer 4.6x wrong. If the link disappears, so does the demonstration.
    a14 = next(q for q in ANSWER_QUESTIONS if q["id"] == "A-14")
    assert a14["routing_id"] == "R-05"
    assert a14["decoys"], "the decoy IS the finding"


def test_no_routing_id_is_claimed_twice():
    claimed = [q["routing_id"] for q in ANSWER_QUESTIONS if q.get("routing_id")]
    assert len(claimed) == len(set(claimed))


# ── ground truth is a query, and the query is read-only ────────────────────


def test_every_answerable_question_carries_a_query_not_a_literal():
    for question in ANSWER_QUESTIONS:
        if question.get("expect") == "abstain":
            continue
        assert question.get("ground_truth_sql"), question["id"]
        check_sql_is_readonly(question["ground_truth_sql"])


def test_every_decoy_is_a_query_too():
    for question in ANSWER_QUESTIONS:
        for name, sql in (question.get("decoys") or {}).items():
            assert name and name.strip(), question["id"]
            check_sql_is_readonly(sql)


def test_no_fixture_query_can_write():
    # Belt and braces over the guard's own unit tests: this asserts it against the real
    # file, so a future question added by hand cannot slip past by never being executed.
    for question in ANSWER_QUESTIONS:
        for sql in [question.get("ground_truth_sql"), *(question.get("decoys") or {}).values()]:
            if not sql:
                continue
            try:
                check_sql_is_readonly(sql)
            except UnsafeFixtureSQL as exc:  # pragma: no cover - a failing fixture
                pytest.fail(f"{question['id']}: {exc}")


def test_unanswerable_questions_have_a_reason_and_no_query():
    """A reason a human wrote, in prose, for every question the system must decline.

    The unanswerable set is the one most projects omit and the one that catches the most
    damaging failure, so "why can't this be answered" is not allowed to be tacit. A
    question that abstains for a reason nobody wrote down is a question that gets deleted
    the first time it fails.
    """
    unanswerable = [q for q in ANSWER_QUESTIONS if q.get("expect") == "abstain"]
    assert len(unanswerable) >= 7, "the plan specifies at least seven"
    for question in unanswerable:
        assert question.get("unanswerable_reason", "").strip(), question["id"]
        assert "ground_truth_sql" not in question, question["id"]


def test_set_questions_declare_a_universe_and_a_subject():
    """Both fields, and neither is decoration.

    Without `universe` precision is not computable over prose. Without `subjects` every
    correct answer scores `partial`, because a well-formed answer restates its own
    question and the subject is in the same closed universe as its neighbours.
    """
    for question in ANSWER_QUESTIONS:
        if question["kind"] != "name_set":
            continue
        assert question.get("universe") in ANSWERS["universes"], question["id"]
        # The KEY must be present; an empty list is a legitimate value. A-29 asks which
        # area is busiest and names no place, so it has no subject — but "no subject" has
        # to be a decision someone wrote down, not a field someone forgot.
        assert "subjects" in question, question["id"]
        assert isinstance(question["subjects"], list), question["id"]


def test_money_questions_declare_their_unit():
    # The model invented a currency once — AED medians in a table headed USD, every figure
    # right and each wrong by 3.67x. A money question with no unit cannot catch that.
    for question in ANSWER_QUESTIONS:
        if question["kind"] == "money":
            assert question.get("unit"), question["id"]


# ── the two route graders must not drift apart ─────────────────────────────


def _fake_response(called: list[str], outcome: str) -> dict:
    return {
        "steps": [{"tool_calls": [{"name": name} for name in called]}],
        "categories": [],
        "outcome": outcome,
    }


def test_the_two_route_graders_agree_on_every_routing_question():
    """`run_eval.py` and `run_routing_eval.py` must score a route identically.

    They are separate files on purpose — m15's runner needs no database and stays exactly
    as it shipped — but two graders means two chances to disagree, and if they ever do,
    m15's routing numbers stop being comparable with m16's. So the agreement is asserted
    rather than assumed, on synthetic responses covering the pass and both failure modes.
    """
    import sys

    # /app/scripts in the container, <repo>/scripts from a checkout — the same two-place
    # lookup `_golden` does, with one extra condition that is not paranoia.
    #
    # The FIRST version checked only the container path, so on a CI runner it would have
    # skipped silently: a test that cannot fail, which is the anti-pattern this repo
    # already paid for when a bare `except` turned a broken connection into a green skip.
    #
    # The SECOND version checked `is_dir()` on both and still failed, because
    # `api/scripts/` EXISTS ON THE HOST AND IS EMPTY. docker-compose bind-mounts `./api`
    # at `/app` and `./scripts` at `/app/scripts`; creating that nested mountpoint wrote an
    # empty directory back through the outer bind mount into the source tree. Git never
    # showed it — git does not track empty directories — so it sat there invisibly and the
    # lookup matched it first.
    #
    # So the condition is "the directory that CONTAINS the module", not "a directory with
    # the right name".
    scripts = next(
        (p for p in (Path(__file__).resolve().parents[i] / "scripts" for i in (1, 2))
         if (p / "run_eval.py").is_file()),
        None,
    )
    if scripts is None:  # pragma: no cover - neither layout present
        pytest.fail(
            "scripts/run_eval.py not found in either layout. Do not fix this by skipping."
        )
    sys.path.insert(0, str(scripts))
    import run_eval  # noqa: PLC0415
    import run_routing_eval  # noqa: PLC0415

    for question in ROUTING["questions"]:
        expected = question.get("expect_tools") or []
        forbidden = question.get("forbid_tools") or []
        outcome = "refused" if question["route"] == "refuse" else "answered"
        cases = [
            (expected, outcome),                          # the clean pass
            ([], outcome),                                # called nothing
            (expected + forbidden[:1], outcome),          # reached for a forbidden tool
            (expected, "max_steps"),                      # ran out of room
        ]
        for called, got in cases:
            response = _fake_response(called, got)
            mine, _ = run_eval.grade_route(question, response)
            theirs = run_routing_eval.grade(question, response, None)["verdict"] == "pass"
            assert mine is theirs, (question["id"], called, got)


# ── isolation: the answer questions must not be in the corpus either ───────


@pytest.mark.asyncio
async def test_no_answer_question_appears_verbatim_in_the_corpus():
    """The m13a rule, applied to the second fixture.

    It matters less here than it did for retrieval — these questions route to SQL, and a
    `COUNT(*)` cannot be leaked by a document — but `docs/llm-eval-harness.md` describes
    this harness and is itself indexed, so the same discipline applies: refer to a
    question by id in prose, never by quoting it.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            try:
                total = (await conn.execute(text("SELECT COUNT(*) FROM doc_chunks"))).scalar()
            except ProgrammingError:
                pytest.skip("doc_chunks does not exist; run `make index`")
            if not total:
                pytest.skip("corpus is empty; run `make index`")
            leaked = []
            for question in ANSWER_QUESTIONS:
                probe = question["text"]
                for char in ("\\", "%", "_"):
                    probe = probe.replace(char, "\\" + char)
                found = (
                    await conn.execute(
                        text("SELECT COUNT(*) FROM doc_chunks WHERE content ILIKE :p ESCAPE '\\'"),
                        {"p": f"%{probe}%"},
                    )
                ).scalar()
                if found:
                    leaked.append(question["id"])
            assert not leaked, f"these questions are inside the corpus they grade: {leaked}"
    finally:
        await engine.dispose()
