"""The graders, under test — which is the whole reason they stopped being a script.

Every grading bug this project has found so far was found by reading output by hand:

  - the refusal detector matched `I can't` with an ASCII apostrophe while `gpt-oss` writes
    `I can’t`, so three correct refusals scored zero and the abstention rate sat at zero
  - a refusal marker matched in the SECOND sentence, so an answer with a caveat read as a
    declined question
  - `truncate()` sliced with a negative index and returned 600 characters for a limit of
    100

Two of those three are one assertion each. That is the argument for this file. A grader is
measurement equipment, and equipment nobody calibrates reports whatever it likes.

Nothing here touches the database or the model: the numeric and set graders are pure, and
that is deliberate — a check that needs 561,115 rows to run is a check that gets skipped.
"""

from decimal import Decimal

import pytest

from services.evaluation.grading import (
    check_unit,
    grade_numeric,
    grade_set,
    mentioned_names,
)
from services.evaluation.numeric import (
    extract_numbers,
    first_number,
    matches,
    parse_tolerance,
)
from services.evaluation.retrieval import aggregate, score_question
from services.evaluation.truth import UnsafeFixtureSQL, check_sql_is_readonly

EXACT = parse_tolerance("exact")
ONE_PERCENT = parse_tolerance(0.01)


# ── pulling numbers out of prose ────────────────────────────────────────────


def test_thousands_separators_and_currency_prefixes():
    assert extract_numbers("AED 550,010 per year") == [Decimal("550010")]
    assert extract_numbers("11,390 transactions") == [Decimal("11390")]


def test_a_space_is_a_thousands_separator_because_the_model_used_one():
    # Observed on the fourth routing run: gpt-oss wrote "AED 550 010" and the naive regex
    # saw 550 and 010, neither of which is any tool's output.
    assert extract_numbers("AED 550 010") == [Decimal("550010")]


def test_the_separator_the_model_actually_used_was_not_an_ascii_space():
    """U+202F, NARROW NO-BREAK SPACE. Verbatim from the first real run of this grader.

    The answer was CORRECT — AED 120,000 for A-14 — and the grader reported `saw [120, 0]`
    and failed it. Third time this project has been caught by a character it did not
    expect, after U+2019 in the refusal detector and an ASCII space in m15's numeric
    guard. The string below is copied out of the response body, not written by hand.
    """
    observed = "is **AED 120 000** per year"
    assert extract_numbers(observed) == [Decimal("120000")]


@pytest.mark.parametrize(
    "space", [" ", " ", " ", " ", " "]
)
def test_every_unicode_digit_group_separator_is_normalised(space):
    assert extract_numbers(f"AED 550{space}010") == [Decimal("550010")]


def test_a_space_before_a_non_triple_is_not_a_separator():
    # The blanket version of the rule above fuses "5 areas 10 rows" into 510 and invents a
    # figure nobody wrote.
    assert extract_numbers("5 areas 10 rows") == [Decimal("5"), Decimal("10")]
    assert extract_numbers("4 areas 1234 rows") == [Decimal("4"), Decimal("1234")]


def test_scale_words_resolve():
    # A model that reads 13786936424 and writes "AED 13.79 bn" is correct, and a grader
    # that fails it is measuring prose style.
    assert extract_numbers("AED 13.79 bn") == [Decimal("13.79") * 10**9]
    assert extract_numbers("1.2 million contracts") == [Decimal("1.2") * 10**6]


def test_decimals_and_percentages():
    assert extract_numbers("up 18.9% to 22,035.73") == [
        Decimal("18.9"),
        Decimal("22035.73"),
    ]


def test_first_number_is_the_one_the_answer_leads_with():
    assert first_number("Business Bay had 10,669 transactions, ahead of 1,615") == Decimal(
        "10669"
    )
    assert first_number("no figures here") is None


def test_extract_returns_empty_for_empty_input():
    assert extract_numbers("") == []
    assert extract_numbers(None) == []


# ── comparison ─────────────────────────────────────────────────────────────


def test_exact_tolerance_ignores_trailing_zeros_but_not_off_by_one():
    assert matches(Decimal("11390.0"), Decimal("11390"), EXACT)
    assert not matches(Decimal("11391"), Decimal("11390"), EXACT)


def test_relative_tolerance():
    assert matches(Decimal("120500"), Decimal("120000"), ONE_PERCENT)
    assert not matches(Decimal("122000"), Decimal("120000"), ONE_PERCENT)


def test_relative_tolerance_around_zero_admits_only_zero():
    # Dividing by a truth of zero is the obvious bug; saying so is the fix.
    assert matches(Decimal("0"), Decimal("0"), ONE_PERCENT)
    assert not matches(Decimal("0.4"), Decimal("0"), ONE_PERCENT)


def test_absolute_tolerance():
    assert matches(Decimal("18.4"), Decimal("18.9"), parse_tolerance("abs:0.5"))
    assert not matches(Decimal("18.3"), Decimal("18.9"), parse_tolerance("abs:0.5"))


def test_a_bare_number_means_relative():
    assert parse_tolerance(0.01) == parse_tolerance("rel:0.01")


def test_an_unknown_tolerance_kind_is_an_error_not_a_default():
    with pytest.raises(ValueError):
        parse_tolerance("about:0.01")


# ── the R-05 case, which is why this module exists ─────────────────────────


def test_the_decoy_is_reported_by_name():
    """The worked example: right route, wrong answer, and the harness names the trap."""
    verdict = grade_numeric(
        "A typical Dubai Marina apartment rents for about AED 550,010 per year.",
        "answered",
        truth=Decimal("120000"),
        tolerance=ONE_PERCENT,
        unit="AED",
        decoys={"contract_total_not_per_property": Decimal("550009.53")},
    )
    assert verdict.verdict == "decoyed"
    assert not verdict.passed
    assert verdict.decoy_hit == "contract_total_not_per_property"
    assert "contract_total_not_per_property" in verdict.reasons[0]


def test_the_true_answer_to_the_same_question_passes():
    verdict = grade_numeric(
        "A typical Dubai Marina apartment rents for about AED 120,000 a year.",
        "answered",
        truth=Decimal("120000"),
        tolerance=ONE_PERCENT,
        unit="AED",
        decoys={"contract_total_not_per_property": Decimal("550009.53")},
    )
    assert verdict.verdict == "correct"
    assert verdict.passed
    assert verdict.leads_with_truth


def test_wrong_but_not_a_known_decoy_is_wrong_not_decoyed():
    verdict = grade_numeric(
        "About AED 91,000.", "answered", Decimal("120000"), ONE_PERCENT,
        decoys={"contract_total_not_per_property": Decimal("550009.53")},
    )
    assert verdict.verdict == "wrong"


def test_containment_and_leading_are_reported_separately():
    # A long answer can contain the right figure by accident. Both rates are printed so
    # nobody has to guess which one a headline number meant.
    verdict = grade_numeric(
        "There are 30,367 rent contracts; the median is AED 70,000.",
        "answered",
        Decimal("70000"),
        ONE_PERCENT,
    )
    assert verdict.verdict == "correct"
    assert verdict.leads_with_truth is False


# ── units: the failure that survives every other check ─────────────────────


def test_a_foreign_currency_label_fails_even_with_the_right_number():
    verdict = grade_numeric(
        "The median is $120,000 (USD).", "answered", Decimal("120000"), ONE_PERCENT,
        unit="AED",
    )
    assert verdict.verdict == "wrong_unit"
    assert not verdict.passed


def test_naming_no_currency_at_all_is_fine():
    # Every count question in the set would fail if absence were an error.
    ok, reasons = check_unit("Business Bay had 10,669 transactions.", "AED")
    assert ok and reasons == []


def test_the_expected_currency_is_not_flagged_as_foreign():
    ok, _ = check_unit("AED 120,000 per year, roughly.", "AED")
    assert ok


def test_a_bare_dollar_sign_before_a_figure_counts():
    ok, reasons = check_unit("about $120,000", "AED")
    assert not ok and "USD" in reasons[0]


# ── abstention: the half that was silently pinned at zero ──────────────────


def test_a_refusal_to_an_unanswerable_question_passes():
    verdict = grade_numeric(
        "I can’t forecast future prices.", "refused", None, EXACT, expect_abstain=True
    )
    assert verdict.verdict == "abstained"
    assert verdict.passed


def test_a_number_for_an_unanswerable_question_is_fabricated():
    verdict = grade_numeric(
        "The median in Abu Dhabi Corniche is AED 1,850,000.",
        "answered", None, EXACT, expect_abstain=True,
    )
    assert verdict.verdict == "fabricated"
    assert not verdict.passed


def test_answering_an_unanswerable_question_without_a_figure_is_still_a_failure():
    verdict = grade_numeric(
        "Prices there are broadly similar to Dubai.",
        "answered", None, EXACT, expect_abstain=True,
    )
    assert verdict.verdict == "over_answered"


def test_refusing_an_answerable_question_is_its_own_verdict():
    # Not "wrong". An over-cautious system and an inaccurate one need different fixes,
    # and one bucket for both hides which you have.
    verdict = grade_numeric("I can’t answer that.", "refused", Decimal("10669"), EXACT)
    assert verdict.verdict == "refused_wrongly"


def test_an_answer_with_no_figure_at_all_is_absent():
    verdict = grade_numeric("Business Bay is busy.", "answered", Decimal("10669"), EXACT)
    assert verdict.verdict == "absent"


def test_a_ground_truth_query_that_returned_nothing_fails_loudly():
    # Silently skipping would shrink the denominator and improve the pass rate, which is
    # the exact shape of the m15 refusal-detector bug.
    verdict = grade_numeric("10,669", "answered", None, EXACT)
    assert verdict.verdict == "no_ground_truth"


# ── set answers ────────────────────────────────────────────────────────────

UNIVERSE = [
    "BUSINESS BAY",
    "BURJ KHALIFA",
    "AL WASL",
    "AL QOUZ FIRST",
    "ZAA'BEEL SECOND",
    "AL QUSAIS",
    "AL QUSAIS FIRST",
    "NAKHLAT JUMEIRA",
]


def test_the_name_the_model_wrote_is_not_the_name_the_table_stores():
    """Verbatim from the first full run, where this failed all six spatial questions.

    Every one of those six answers was correct and the harness reported "never named
    [...]" for each. The model writes `Burj Khalifa` with U+202F between the words and
    `Zaa’beel Second` with U+2019; the community table stores `BURJ KHALIFA` and
    `ZAA'BEEL SECOND`. Both sides are normalised now. The strings below are copied out of
    the response bodies, not written by hand.
    """
    answer = "| Burj Khalifa | 3,526.33 |\n| Zaa’beel Second | 1,516.67 |"
    # In ORDER OF APPEARANCE, which is not the order they are matched in — see
    # `mentioned_names`. `leading_only` grading depends on this ordering being the text's.
    assert mentioned_names(answer, UNIVERSE) == ["BURJ KHALIFA", "ZAA'BEEL SECOND"]


def test_the_whole_spatial_answer_from_the_first_run_now_passes():
    # The complete A-23 body, which named all four neighbours correctly and scored `wrong`.
    answer = (
        "**Communities that share a border with Business Bay**\n\n"
        "| Community | Shared boundary (m) |\n"
        "| Burj Khalifa | 3,526.33 |\n| Al Wasl | 2,341.16 |\n"
        "| Al Qouz First | 2,229.01 |\n| Zaa’beel Second | 1,516.67 |\n"
    )
    verdict = grade_set(
        answer,
        "answered",
        ["AL QOUZ FIRST", "AL WASL", "BURJ KHALIFA", "ZAA'BEEL SECOND"],
        UNIVERSE,
        subjects=["BUSINESS BAY"],
    )
    assert verdict.verdict == "correct" and verdict.passed


def test_an_empty_answer_labelled_answered_is_its_own_verdict():
    """Two questions came back `answered` with an empty body, after 63 s and 54 s.

    That is a fault in the loop, not an answer to grade. Folding it into `wrong` would
    hide a system failure inside a quality metric — and m15's executor docstring says
    precisely why: a 200 with an empty answer makes an outage look like a hard question.
    """
    assert grade_numeric("", "answered", Decimal("1"), EXACT).verdict == "empty"
    assert grade_numeric("", "answered", None, EXACT, expect_abstain=True).verdict == "empty"
    assert grade_set("", "answered", ["AL WASL"], UNIVERSE).verdict == "empty"


def test_an_empty_body_on_a_refusal_is_not_an_empty_answer():
    # A refusal is graded on the outcome. Some refusals put their reason in the body and
    # some do not, and an empty one is not a fault.
    assert grade_numeric("", "refused", None, EXACT, expect_abstain=True).verdict == "abstained"


def test_a_prefix_name_is_not_counted_twice():
    # AL QUSAIS is a prefix of AL QUSAIS FIRST. A naive substring match scores one named
    # area as two and silently halves precision on every question involving either.
    assert mentioned_names("It borders AL QUSAIS FIRST only.", UNIVERSE) == [
        "AL QUSAIS FIRST"
    ]


def test_a_complete_and_exact_set_passes():
    verdict = grade_set(
        "Business Bay borders AL QOUZ FIRST, AL WASL, BURJ KHALIFA and ZAA'BEEL SECOND.",
        "answered",
        ["AL QOUZ FIRST", "AL WASL", "BURJ KHALIFA", "ZAA'BEEL SECOND"],
        UNIVERSE,
        subjects=["Business Bay"],
    )
    assert verdict.verdict == "correct" and verdict.passed
    assert verdict.recall == 1.0 and verdict.precision == 1.0


def test_the_subject_of_the_question_is_not_a_wrongly_named_neighbour():
    """The bug this test was written to catch, kept as a regression.

    A well-formed answer restates its own question, and the subject lives in the same
    closed universe as the neighbours. Without `subjects` every correct answer to every
    spatial question scored `partial` — precision 0.67 on a perfect reply.
    """
    answer = "Business Bay borders AL WASL and BURJ KHALIFA."
    expected = ["AL WASL", "BURJ KHALIFA"]
    assert not grade_set(answer, "answered", expected, UNIVERSE).passed
    assert grade_set(
        answer, "answered", expected, UNIVERSE, subjects=["Business Bay"]
    ).passed


def test_a_subject_that_is_genuinely_in_the_expected_set_is_still_graded():
    # Ignoring the subject must not become a way to miss it. If the fixture says the
    # subject belongs in the answer, `subjects` does not suppress it.
    verdict = grade_set(
        "The busiest is BURJ KHALIFA.", "answered", ["BURJ KHALIFA"], UNIVERSE,
        subjects=["BURJ KHALIFA"],
    )
    assert verdict.passed and verdict.hits == ["BURJ KHALIFA"]


def test_one_extra_name_fails_on_precision():
    verdict = grade_set(
        "It borders AL WASL, BURJ KHALIFA and AL QUSAIS.",
        "answered",
        ["AL WASL", "BURJ KHALIFA"],
        UNIVERSE,
    )
    assert not verdict.passed
    assert verdict.recall == 1.0
    assert verdict.extras == ["AL QUSAIS"]


def test_the_empty_set_is_an_answer_when_the_answer_says_so():
    # Palm Jumeirah is an artificial island: it touches nothing. m15 spent two fixes here.
    verdict = grade_set(
        "Palm Jumeirah shares no border with any other community.",
        "answered", [], UNIVERSE,
    )
    assert verdict.verdict == "correct" and verdict.passed


def test_the_empty_set_fails_when_the_answer_blames_the_data():
    verdict = grade_set(
        "There is no polygon for Palm Jumeirah in the dataset.",
        "answered", [], UNIVERSE,
    )
    assert not verdict.passed
    assert "blamed missing data" in verdict.reasons[0]


def test_silence_about_an_empty_set_is_also_a_failure():
    verdict = grade_set("Palm Jumeirah is a large development.", "answered", [], UNIVERSE)
    assert not verdict.passed


def test_a_superlative_question_grades_the_name_the_answer_leads_with():
    """Showing the comparison is better practice than a bare name, and scored .

    A-26 answered "Burj Khalifa" and then printed the other three neighbours with their
    transaction counts. Those areas DO border Business Bay; they are simply not the
    maximum. Requiring an answer to mention nothing else measured verbosity, not accuracy.
    Same containment-versus-assertion distinction as `leads_with_truth`, applied to names.
    """
    answer = (
        "The neighboring area with the highest volume is **BURJ KHALIFA**.\n"
        "| BURJ KHALIFA | 11,390 |\n| AL WASL | 1,615 |\n| AL QOUZ FIRST | 125 |"
    )
    assert not grade_set(answer, "answered", ["BURJ KHALIFA"], UNIVERSE,
                         subjects=["BUSINESS BAY"]).passed
    verdict = grade_set(answer, "answered", ["BURJ KHALIFA"], UNIVERSE,
                        subjects=["BUSINESS BAY"], leading_only=True)
    assert verdict.verdict == "correct" and verdict.passed


def test_leading_grading_still_fails_when_the_wrong_name_comes_first():
    answer = "AL WASL leads, ahead of BURJ KHALIFA."
    verdict = grade_set(answer, "answered", ["BURJ KHALIFA"], UNIVERSE,
                        subjects=["BUSINESS BAY"], leading_only=True)
    assert verdict.verdict == "wrong" and not verdict.passed


# ── retrieval metrics ──────────────────────────────────────────────────────

RELEVANCE = {
    "docs/architecture.md": 3,
    "docs/concurrent-inserts.md": 1,
    "docs/rag-corpus-design.md": 0,
}


def test_top1_ideal_requires_a_three_not_merely_a_relevant_document():
    scored = score_question("G-01", ["docs/architecture.md"], RELEVANCE)
    assert scored.top1_ideal
    scored = score_question("G-01", ["docs/concurrent-inserts.md"], RELEVANCE)
    assert not scored.top1_ideal


def test_a_grade_of_one_does_not_count_as_a_hit():
    # 1 is "same subject, does not answer it". Counting it would score a retriever for
    # returning topically adjacent prose, which is what the 0-3 scale exists to expose.
    scored = score_question("G-01", ["docs/concurrent-inserts.md"], RELEVANCE, ks=(1,))
    assert scored.hit_at[1] is False


def test_mrr_is_the_reciprocal_of_the_first_relevant_rank():
    ranked = ["docs/rag-corpus-design.md", "docs/architecture.md"]
    assert score_question("G-01", ranked, RELEVANCE).mrr == 0.5


def test_a_decoy_above_the_answer_is_recorded_by_name():
    # The number a nearest-neighbour list should be judged on, and the one an average
    # recall hides: G-10's dense arm put the decoy first every time and still scored a hit.
    ranked = ["docs/rag-corpus-design.md", "docs/architecture.md"]
    scored = score_question("G-10", ranked, RELEVANCE)
    assert scored.decoys_above_answer == ["docs/rag-corpus-design.md"]


def test_a_decoy_at_rank_one_is_recorded_even_when_nothing_relevant_is_found():
    """The case `decoys_above_answer` cannot see, and the worst one.

    If no relevant document appears anywhere in the results there is nothing for a decoy
    to be "above", so the sharpest signal a run produces went unreported in exactly the
    situation that matters most. Found when a write-up of this milestone became a decoy
    for one of the questions it describes.
    """
    scored = score_question("G-07", ["docs/rag-corpus-design.md"], RELEVANCE)
    assert scored.decoys_above_answer == []
    assert scored.decoy_at_top == "docs/rag-corpus-design.md"


def test_an_ungraded_document_at_rank_one_is_not_a_decoy():
    # Unjudged is not the same as explicitly graded 0. Only a document the fixture NAMED
    # as a decoy counts, or the metric becomes "anything unexpected", which is every run.
    scored = score_question("G-01", ["docs/polygon-simplification.md"], RELEVANCE)
    assert scored.decoy_at_top is None


def test_duplicate_source_slots_are_counted_not_silently_dropped():
    # A document with three chunks in the top 5 occupies three slots. hit@k and MRR are
    # taken on the raw list — deduplicating would promote a relevant document past the
    # repeats of another — and the repeat count is reported instead of hidden.
    ranked = ["docs/architecture.md", "docs/architecture.md", "docs/concurrent-inserts.md"]
    assert score_question("G-01", ranked, RELEVANCE).duplicate_slots == 1


def test_ndcg_cannot_exceed_one():
    """It did: 2.436 on the first real run, because chunks repeat and the ideal does not.

    The fixture grades DOCUMENTS and `/search` ranks CHUNKS, so one document occupying
    three of the top five slots contributed its gain three times against an ideal built
    from each graded document once. A ratio bounded at 1 came back at 2.4 and nobody would
    have noticed it in a summary table full of plausible decimals.
    """
    ranked = ["docs/architecture.md"] * 5
    assert score_question("G-01", ranked, RELEVANCE).ndcg_at_5 <= 1.0


def test_ndcg_is_one_when_the_ideal_document_leads():
    scored = score_question(
        "G-01", ["docs/architecture.md", "docs/concurrent-inserts.md"], {"docs/architecture.md": 3}
    )
    assert scored.ndcg_at_5 == 1.0


def test_an_empty_result_list_scores_zero_rather_than_raising():
    scored = score_question("G-01", [], RELEVANCE)
    assert scored.mrr == 0.0 and scored.ndcg_at_5 == 0.0 and not scored.top1_ideal


def test_aggregate_reports_counts_beside_means():
    scored = [
        score_question("a", ["docs/architecture.md"], RELEVANCE),
        score_question("b", ["docs/rag-corpus-design.md"], RELEVANCE),
    ]
    agg = aggregate(scored, ks=(1,))
    assert agg["n"] == 2
    assert agg["top1_ideal_count"] == 1
    assert agg["top1_ideal"] == 0.5


def test_aggregate_of_nothing_does_not_divide_by_zero():
    assert aggregate([])["n"] == 0


# ── the fixture SQL guard ──────────────────────────────────────────────────


def test_a_select_passes_and_loses_its_trailing_semicolon():
    assert check_sql_is_readonly("SELECT COUNT(*) FROM raw_transactions;") == (
        "SELECT COUNT(*) FROM raw_transactions"
    )


def test_a_cte_passes():
    assert check_sql_is_readonly("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM raw_transactions",
        "UPDATE raw_transactions SET actual_worth = 0",
        "SELECT 1; DELETE FROM raw_transactions",
        "",
        "   ",
    ],
)
def test_anything_that_is_not_one_read_only_statement_is_rejected(sql):
    with pytest.raises(UnsafeFixtureSQL):
        check_sql_is_readonly(sql)
