"""The verdict for one answer.

WHAT A RUBRIC FOR A NUMERIC ANSWER LOOKS LIKE
----------------------------------------------
The retrieval fixture grades documents, which is a solved shape: a fixed set of source
ids, a 0-3 relevance scale, and rank metrics on top. Grading a number is not that, and
m16's first job was to work out what it even is before writing a harness.

It is four things, and the fourth is the one this project had to earn:

    1. a QUERY, not a value        `truth.py` — literals go stale and can be circular
    2. a TOLERANCE                 exact for counts, ±1% for money, absolute for ratios
    3. a UNIT                      because the model invented one (M-32): given AED
                                   medians it produced a table headed "USD" with $ on
                                   every figure. Numbers real, arithmetic sound, label
                                   false — and a units error survives every other check
    4. a DECOY, with a query too   the near-miss this question is known to attract

The fourth is R-05 made into a field. "Wrong" is a useless verdict when the interesting
question is *how* wrong: a value 0.3% out is a stale reload, and a value that is exactly
`AVG(annual_amount)` when the truth is a per-property median is the v0.5.0 trap
re-entering through a new tool under a friendly name. The first is noise. The second is a
regression with a name, and the harness should print the name.

A decoy is therefore recorded the same way the truth is — as SQL — so the harness can say
"this is not merely wrong, it is the contract total again" without anyone having to
recognise the number by eye. Nobody recognised it by eye the first time. It took a
grounding warning, a hand-written percentile query, and an afternoon.

WHAT IS DELIBERATELY NOT HERE
------------------------------
No model call. §6.2 of the plan reserves LLM-as-judge for narrative answers and forbids it
anywhere a deterministic check will do, because a judge is a measurement instrument with
its own bias and a bias inside a regression gate is a bias nobody sees again. Every
verdict in this module is arithmetic and set membership.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from services.evaluation.numeric import (
    Tolerance,
    extract_numbers,
    first_number,
    matches,
)
from services.evaluation.text import normalise

__all__ = [
    "AnswerVerdict",
    "SetVerdict",
    "check_unit",
    "grade_numeric",
    "grade_set",
    "mentioned_names",
]

# Currency tokens that are NOT the expected unit are a failure, not a warning. Observed
# once and it was total: every figure in the table was right and every one was labelled
# with the wrong symbol, which is a 3.67x error a reader cannot see.
_CURRENCY_TOKENS = {
    "AED": re.compile(r"\b(?:AED|dirham(?:s)?|د\.إ)\b", re.IGNORECASE),
    "USD": re.compile(r"(?:\bUSD\b|\bUS\$|\bdollar(?:s)?\b|(?<![A-Za-z])\$(?=\s?[\d,]))"),
    "EUR": re.compile(r"(?:\bEUR\b|\beuro(?:s)?\b|€)", re.IGNORECASE),
    "GBP": re.compile(r"(?:\bGBP\b|\bpound(?:s)? sterling\b|£)", re.IGNORECASE),
}


@dataclass
class AnswerVerdict:
    """One graded numeric answer, with every reason behind the verdict.

    `passed` is separate from `verdict` because they answer different questions. The
    verdict is what happened; `passed` is whether the threshold file should count it. A
    `decoyed` answer and a `wrong` answer both fail, and conflating them is how the R-05
    class of bug stays invisible.
    """

    verdict: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    truth: Decimal | None = None
    matched: Decimal | None = None
    decoy_hit: str | None = None
    decoy_value: Decimal | None = None
    candidates: list[Decimal] = field(default_factory=list)
    leads_with_truth: bool | None = None
    unit_ok: bool | None = None


@dataclass
class SetVerdict:
    """One graded set answer — the spatial questions.

    Precision is computable here and is not usually computable over prose, because the
    universe is closed: there are 222 community polygons and 221 distinct area spellings,
    so "which names did this answer mention" is a finite question with an exact answer.
    That is worth having. An answer that lists the four true neighbours of Business Bay
    scores the same recall as one that lists all 222 areas, and only precision separates
    them.
    """

    verdict: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)
    mentioned: list[str] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    recall: float = 0.0
    precision: float = 0.0


def check_unit(answer: str, unit: str | None) -> tuple[bool, list[str]]:
    """Does the answer label its figures with the unit the tools returned?

    Absence is not a failure. "Business Bay had 10,669 transactions" names no currency and
    needs none, and a check that demanded one would fire on every count question in the
    set. What fails is naming a DIFFERENT currency — the observed failure, and the one
    that is invisible downstream.
    """
    if not unit:
        return True, []
    reasons = []
    for name, pattern in _CURRENCY_TOKENS.items():
        if name == unit:
            continue
        if pattern.search(answer or ""):
            reasons.append(
                f"the answer labels figures {name} but the tools returned {unit}"
            )
    return (not reasons), reasons


def grade_numeric(
    answer: str,
    outcome: str,
    truth: Decimal | None,
    tolerance: Tolerance,
    *,
    unit: str | None = None,
    decoys: dict[str, Decimal] | None = None,
    expect_abstain: bool = False,
) -> AnswerVerdict:
    """Grade one numeric answer against a value the fixture's own SQL produced.

    The order of the checks is the argument. Abstention is settled first, because a
    refusal is not a wrong answer and grading it as one is what pinned this project's
    abstention rate at zero for a whole eval run. Then the decoy, before the general
    "wrong", so a known trap is reported by name rather than as an anonymous miss.
    """
    candidates = extract_numbers(answer or "")
    lead = first_number(answer or "")
    unit_ok, unit_reasons = check_unit(answer or "", unit)

    # AN EMPTY ANSWER LABELLED `answered` IS ITS OWN FAILURE, and the first full run found
    # two of them: A-39 and A-40 came back with `outcome: "answered"` and `answer: ""`,
    # after 63 s and 54 s — the two longest runs in the set. That is a defect in the loop,
    # not an answer to grade, and it is the exact thing m15's executor docstring said it
    # was avoiding: "a 200 with an empty answer would make an outage look like a hard
    # question." Folding it into `wrong` or `over_answered` would hide a system fault
    # inside a quality metric, so it gets a verdict of its own and is counted separately.
    if not (answer or "").strip() and outcome != "refused":
        return AnswerVerdict(
            "empty",
            False,
            [f"outcome was {outcome!r} but the answer body is empty"],
            truth,
            None,
            None,
            None,
            candidates,
        )

    if expect_abstain:
        if outcome == "refused":
            return AnswerVerdict("abstained", True, [], None, None, None, None, candidates)
        # A number in an answer to an unanswerable question is the failure the whole
        # unanswerable set exists to catch. Reported as `fabricated` rather than `wrong`
        # because there is no true value for it to be wrong ABOUT.
        verdict = "fabricated" if candidates else "over_answered"
        reason = (
            f"should have declined; answered with {candidates[0]}"
            if candidates
            else "should have declined; answered without a figure"
        )
        return AnswerVerdict(verdict, False, [reason], None, None, None, None, candidates)

    if outcome == "refused":
        return AnswerVerdict(
            "refused_wrongly",
            False,
            ["declined a question that has an answer in the data"],
            truth,
            None,
            None,
            None,
            candidates,
        )

    if truth is None:
        return AnswerVerdict(
            "no_ground_truth",
            False,
            ["the fixture's ground-truth query returned no rows"],
            None,
            None,
            None,
            None,
            candidates,
        )

    if not candidates:
        return AnswerVerdict(
            "absent", False, ["the answer contains no figure"], truth, None,
            None, None, candidates, None, unit_ok,
        )

    hit = next((c for c in candidates if matches(c, truth, tolerance)), None)
    if hit is not None:
        leads = lead is not None and matches(lead, truth, tolerance)
        reasons = list(unit_reasons)
        if not leads:
            reasons.append(
                f"correct value present but the answer leads with {lead}"
            )
        return AnswerVerdict(
            "correct" if unit_ok else "wrong_unit",
            unit_ok,
            reasons,
            truth,
            hit,
            None,
            None,
            candidates,
            leads,
            unit_ok,
        )

    for name, value in (decoys or {}).items():
        struck = next((c for c in candidates if matches(c, value, tolerance)), None)
        if struck is not None:
            return AnswerVerdict(
                "decoyed",
                False,
                [
                    f"answered {struck} — the known decoy {name!r} ({value}), "
                    f"not the true {truth}"
                ]
                + unit_reasons,
                truth,
                struck,
                name,
                value,
                candidates,
                False,
                unit_ok,
            )

    return AnswerVerdict(
        "wrong",
        False,
        [f"no figure within {tolerance.describe()} of {truth}; saw {candidates[:6]}"]
        + unit_reasons,
        truth,
        None,
        None,
        None,
        candidates,
        False,
        unit_ok,
    )


def mentioned_names(answer: str, universe: list[str]) -> list[str]:
    """Which names from a closed universe does this answer actually name?

    Longest first, and each match consumes its span. Without that, `AL QUSAIS` matches
    inside `AL QUSAIS FIRST` and an answer naming one area is scored as naming two — which
    would silently halve precision on every question about an area whose name is a prefix
    of another. There are several such pairs in this dataset.
    BOTH SIDES ARE NORMALISED, and skipping that failed all six spatial questions on the
    first full run while the model was right every time. It writes `Burj Khalifa` with
    U+202F and `Zaa’beel Second` with U+2019; the community table stores `BURJ KHALIFA`
    and `ZAA'BEEL SECOND`. A literal substring test between those two strings is false,
    and the harness reported "never named [...]" for four perfectly listed neighbours.
    """
    haystack = normalise(answer).upper()
    found: list[tuple[int, str]] = []
    for name in sorted(universe, key=len, reverse=True):
        needle = normalise(name).upper()
        index = haystack.find(needle)
        if index != -1:
            found.append((index, name))
            haystack = haystack[:index] + " " * len(needle) + haystack[index + len(needle) :]
    # MATCHED longest-first, RETURNED in order of appearance, and the two orders are not
    # the same. The first version returned universe order, so `leading_only` grading —
    # which asks what the answer leads with — was reading whichever matching name happened
    # to be the longest. Caught by its own test on the first run, which is the second time
    # in this file that writing the test first has paid for itself.
    return [name for _, name in sorted(found)]


def grade_set(
    answer: str,
    outcome: str,
    expected: list[str],
    universe: list[str],
    *,
    expect_abstain: bool = False,
    subjects: list[str] | None = None,
    leading_only: bool = False,
) -> SetVerdict:
    """Grade an answer whose right shape is a set of place names.

    An EMPTY expected set is a pass when the answer says so in words and a failure when
    the answer claims the data is missing. m15 paid for that distinction twice: asked for
    Palm Jumeirah's neighbours the agent resolved the transliterated polygon name,
    queried it correctly, received `[]` — because an artificial island borders nothing —
    and reported that no polygon existed.

    `subjects` names the place the question is ABOUT, and leaving it out was a real bug
    in the first version of this function. "Business Bay borders Al Wasl and Burj Khalifa"
    is a perfect answer that restates its own question, and the subject is in the same
    closed universe as the neighbours — so it was counted as a wrongly-named extra and the
    answer scored `partial` at precision 0.67. Every well-formed answer to a spatial
    question would have failed. Caught by a unit test written the same hour, which is the
    argument for these graders having tests at all.
    """
    if not (answer or "").strip() and outcome != "refused":
        # Same reasoning as `grade_numeric`: a system fault, not a quality verdict.
        return SetVerdict(
            "empty",
            False,
            [f"outcome was {outcome!r} but the answer body is empty"],
            expected,
        )

    if expect_abstain:
        passed = outcome == "refused"
        return SetVerdict(
            "abstained" if passed else "over_answered",
            passed,
            [] if passed else [f"should have declined; outcome was {outcome!r}"],
            expected,
        )

    expected_upper_all = {e.upper() for e in expected}
    ignore = {
        s.upper() for s in (subjects or []) if s.upper() not in expected_upper_all
    }
    mentioned = [m for m in mentioned_names(answer, universe) if m.upper() not in ignore]
    expected_upper = {e.upper() for e in expected}
    hits = [m for m in mentioned if m.upper() in expected_upper]
    extras = [m for m in mentioned if m.upper() not in expected_upper]
    missing = [e for e in expected if e.upper() not in {m.upper() for m in mentioned}]

    if not expected:
        # "Nothing borders it" — graded on whether the answer says the set is empty
        # rather than on whether it is silent. Silence and "no data" both fail.
        said_none = bool(
            re.search(
                r"\b(no|none|zero|does not (?:share|border)|borders? nothing|"
                r"not (?:share|adjacent)|no (?:adjacent|neighbou?rs?|bordering))\b",
                answer or "",
                re.IGNORECASE,
            )
        )
        blamed_data = bool(
            re.search(
                r"\b(no (?:polygon|record|data|boundary)|not (?:in|present in) the "
                r"(?:data|dataset|database)|could not (?:find|locate))\b",
                answer or "",
                re.IGNORECASE,
            )
        )
        if said_none and not blamed_data and not extras:
            return SetVerdict("correct", True, [], expected, mentioned, [], extras, [], 1.0, 1.0)
        reason = (
            "the true set is empty and the answer blamed missing data"
            if blamed_data
            else "the true set is empty and the answer did not say so"
        )
        return SetVerdict("wrong", False, [reason], expected, mentioned, [], extras, [], 0.0, 0.0)

    if leading_only:
        # SUPERLATIVE QUESTIONS — "which of these has the highest volume?" — where the
        # answer is one name but a GOOD answer shows the comparison it made. The first
        # full run scored A-26 `partial` for naming Burj Khalifa first and then printing
        # the other three neighbours in a table with their counts. That is better practice
        # than a bare name, and penalising it measured verbosity rather than correctness.
        #
        # This is the same containment-versus-assertion distinction the numeric grader
        # already draws with `leads_with_truth`, applied to names: what is graded is what
        # the answer LEADS with, and the rest is working shown.
        lead = mentioned[0] if mentioned else None
        ok = lead is not None and lead.upper() in expected_upper_all
        return SetVerdict(
            "correct" if ok else ("wrong" if mentioned else "absent"),
            ok,
            [] if ok else [f"leads with {lead!r}; expected one of {expected}"],
            expected,
            mentioned,
            [lead] if ok else [],
            [],
            [] if ok else expected,
            1.0 if ok else 0.0,
            1.0 if ok else 0.0,
        )

    recall = len(hits) / len(expected)
    precision = len(hits) / len(mentioned) if mentioned else 0.0
    reasons = []
    if missing:
        reasons.append(f"never named {missing}")
    if extras:
        reasons.append(f"named {extras}, which do not border it")
    passed = not missing and not extras
    return SetVerdict(
        "correct" if passed else ("partial" if hits else "wrong"),
        passed,
        reasons,
        expected,
        mentioned,
        hits,
        extras,
        missing,
        recall,
        precision,
    )
