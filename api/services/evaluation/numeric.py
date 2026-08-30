"""Getting a number out of a sentence, and deciding whether it is the right one.

WHY THIS IS NOT THE SAME CODE AS `verify_numbers`
--------------------------------------------------
`services/agent/executor.py` has a number extractor already, and it is tempting to import
it. It answers a different question. `verify_numbers` asks *did this number come from a
tool* — a provenance check over strings, where "550010" and "550,010.53" both flatten to
digits and a substring test is exactly right. Grading asks *is this number the right
value*, which is arithmetic: 550,010 is not 550,010.53 as a string and is within 0.001%
of it as a quantity.

A shared extractor would have to serve both, and the m15 register already contains what
happens when one guard serves two purposes. They stay separate, and the duplication is
about twenty lines.

WHAT COUNTS AS A NUMBER HERE
-----------------------------
Prose, so: thousands separators, a currency prefix or suffix, a percent sign, an en dash
between two figures, and — measured on this stack, not imagined — a SPACE used as a
thousands separator. `gpt-oss:20b` wrote "AED 550 010" on the fourth routing run and the
naive regex saw 550 and 010. Only a space followed by exactly three digits collapses; a
blanket rule fuses "5 areas 10 rows" into 510 and invents a figure nobody wrote.

Ordinals and years are extracted like anything else. They are not filtered out, because
filtering "2020" would also filter a price of 2,020 and the fixture knows which of those
it asked for while this module does not.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from services.evaluation.text import normalise

__all__ = ["extract_numbers", "first_number", "matches", "Tolerance", "parse_tolerance"]

# THE SEPARATOR IS NOT ALWAYS AN ASCII SPACE, and this cost a correct answer.
#
# The first real run of the answer grader failed A-14 and printed `saw [120, 0]` against a
# truth of 120000. The model was right: it had written **AED 120 000** using U+202F,
# NARROW NO-BREAK SPACE, which is the typographically correct digit-group separator and
# what a model trained on well-set text reaches for.
#
# The normalisation now lives in `text.normalise`, shared with the name matcher, because
# the same two characters went on to fail all six spatial questions in the first full run.
# See that module's docstring for the full tally: four incidents, two characters, three
# detectors, and the system was right every time.

# A space is a thousands separator only when it is followed by EXACTLY three digits.
_SPACE_THOUSANDS = re.compile(r"(\d) (?=\d{3}(?!\d))")

# Sign, digits with optional , or _ groupings, optional decimal tail. The leading
# (?<![\w.]) keeps us off the tail of an identifier or a version string; the trailing
# (?!\d) stops a partial match inside a longer run of digits.
_NUMBER = re.compile(r"(?<![\w.])(-?\d[\d,_]*(?:\.\d+)?)(?!\d)")

# Scale words the model uses instead of writing the zeros. Observed on this stack:
# "AED 6.75 bn", "1.2 million transactions".
_SCALES: dict[str, int] = {
    "k": 10**3,
    "thousand": 10**3,
    "m": 10**6,
    "mn": 10**6,
    "million": 10**6,
    "bn": 10**9,
    "billion": 10**9,
}
_SCALE_SUFFIX = re.compile(
    r"^\s*(" + "|".join(sorted(_SCALES, key=len, reverse=True)) + r")\b", re.IGNORECASE
)


def extract_numbers(text: str) -> list[Decimal]:
    """Every numeric quantity in `text`, in the order it appears, duplicates kept.

    Order is preserved because `first_number` needs it and because a grader that reports
    "the truth appears somewhere in the answer" is making a weaker claim than one that
    reports "the answer leads with the truth". Both are reported; see `grading.py`.
    """
    if not text:
        return []
    text = _SPACE_THOUSANDS.sub(r"\1", normalise(text))
    found: list[Decimal] = []
    for match in _NUMBER.finditer(text):
        raw = match.group(1).replace(",", "").replace("_", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:  # pragma: no cover - the regex cannot produce this
            continue
        scale = _SCALE_SUFFIX.match(text[match.end() :])
        if scale:
            value *= _SCALES[scale.group(1).lower()]
        found.append(value)
    return found


def first_number(text: str) -> Decimal | None:
    """The figure the answer leads with, or None.

    Worth having as its own function because "contains the right number" and "asserts the
    right number" are different claims and a long answer can satisfy the first by
    accident. Neither is a perfect reading of intent — an answer may legitimately open
    with a row count before giving a median — which is why the harness reports the two
    rates side by side instead of choosing one and calling it accuracy.
    """
    numbers = extract_numbers(text)
    return numbers[0] if numbers else None


class Tolerance:
    """How close is close enough, and why the question decides rather than the harness.

    `exact`      integers: counts, row totals, years. Off by one is wrong.
    `rel:0.01`   money and medians: ±1%, the plan's figure. A median recomputed after a
                 reload moves; a median that is 4.6x out is a different fact.
    `abs:0.5`    percentages and ratios, where a relative tolerance on a value near zero
                 is meaningless.
    """

    __slots__ = ("kind", "amount")

    def __init__(self, kind: str, amount: Decimal | None = None) -> None:
        self.kind = kind
        self.amount = amount

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Tolerance({self.kind!r}, {self.amount!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Tolerance)
            and self.kind == other.kind
            and self.amount == other.amount
        )

    def describe(self) -> str:
        if self.kind == "exact":
            return "exact"
        if self.kind == "rel":
            return f"±{self.amount * 100:.4g}%"
        return f"±{self.amount:,.4g}"


def parse_tolerance(spec: str | float | int | None) -> Tolerance:
    """Read a fixture's `tolerance` field.

    A bare number means relative, because that is what every money question in the set
    wants and a fixture that has to spell out `rel:` forty times invites a typo that
    silently loosens a threshold.
    """
    if spec is None or spec == "exact":
        return Tolerance("exact")
    if isinstance(spec, (int, float)):
        return Tolerance("rel", Decimal(str(spec)))
    text = str(spec).strip()
    if ":" in text:
        kind, _, amount = text.partition(":")
        kind = kind.strip().lower()
        if kind not in ("rel", "abs"):
            raise ValueError(f"unknown tolerance kind {kind!r}; use exact, rel: or abs:")
        return Tolerance(kind, Decimal(amount.strip()))
    return Tolerance("rel", Decimal(text))


def matches(candidate: Decimal, truth: Decimal, tolerance: Tolerance) -> bool:
    """Is `candidate` the same quantity as `truth` under `tolerance`?

    Exact comparison rounds both sides to an integer first. The reason is that a COUNT(*)
    arrives from Postgres as `Decimal("11390")` and from the model's prose as
    `Decimal("11390")` — but a model that writes "11,390.0" is not wrong, and a fixture
    that fails it is measuring formatting.
    """
    if tolerance.kind == "exact":
        return candidate.quantize(Decimal(1)) == truth.quantize(Decimal(1))
    delta = abs(candidate - truth)
    if tolerance.kind == "abs":
        return delta <= tolerance.amount
    if truth == 0:
        # A relative tolerance around zero admits only zero. Say so rather than dividing.
        return candidate == 0
    return delta / abs(truth) <= tolerance.amount
