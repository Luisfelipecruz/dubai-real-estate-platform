"""Normalise before you parse. This project has now paid for that rule four times.

THE FOUR
---------
1. m15, the refusal detector. `gpt-oss` writes `I can’t` with U+2019 RIGHT SINGLE
   QUOTATION MARK; the marker list contained ASCII `i can't`. Three correct refusals
   scored zero and the abstention rate — a number this project publishes — sat silently
   at zero for a whole eval run.
2. m15, the numeric guard. The model wrote `AED 550 010`, separating thousands with a
   space, and the number regex saw 550 and 010.
3. m16, the answer grader, first run. `AED 120 000` with U+202F NARROW NO-BREAK SPACE.
   The answer was correct and the harness reported `saw [120, 0]`.
4. m16, the answer grader, first FULL run, and this one was the most expensive. Every one
   of the six spatial questions failed with "never named [...]" — and every one of the six
   answers was perfect. The model writes `Burj Khalifa` and `Zaa’beel Second`; the
   community table stores `BURJ KHALIFA` and `ZAA'BEEL SECOND`. A literal substring match
   between those two strings is false.

Four incidents, two characters, three separate detectors, and in every case the SYSTEM was
right and the MEASUREMENT was wrong. That is the failure mode worth designing against,
because it moves a metric in the flattering direction as easily as the other one — a
grader that cannot see a correct answer is one refactor away from being a grader that
cannot see a wrong one.

So normalisation stops being something each detector remembers and becomes one function
that every comparison in this package calls first.

WHAT IS NOT NORMALISED, AND WHY
--------------------------------
Case is left alone here; callers that want it fold it themselves, because
`mentioned_names` needs the original casing to report what it matched. Accents are left
alone: `Zaa'beel` and `Za'abeel` are different transliterations of the same place and
collapsing them would be a data decision disguised as a string operation. Hyphens are left
alone for the same reason — `Al-Barsha` and `Al Barsha` differ in the source data, and
that difference is a real finding rather than noise to launder.
"""

from __future__ import annotations

__all__ = ["normalise"]

# Space-like characters a model reaches for when setting type well. Every one of these is
# a plausible digit-group separator or a non-breaking join inside a proper noun.
_SPACES = {
    " ": " ",  # NO-BREAK SPACE
    " ": " ",  # NARROW NO-BREAK SPACE   <- observed twice on this stack
    " ": " ",  # THIN SPACE
    " ": " ",  # FIGURE SPACE
    " ": " ",  # PUNCTUATION SPACE
    " ": " ",  # FOUR-PER-EM SPACE
    "　": " ",  # IDEOGRAPHIC SPACE
}

# Zero-width characters, deleted rather than spaced: they join, they do not separate.
_ZERO_WIDTH = {
    "​": "",  # ZERO WIDTH SPACE
    "‌": "",  # ZERO WIDTH NON-JOINER
    "‍": "",  # ZERO WIDTH JOINER
    "⁠": "",  # WORD JOINER
    "﻿": "",  # ZERO WIDTH NO-BREAK SPACE / BOM
}

# Quotation marks. U+2019 is the one that cost m15 an eval run; the others are here
# because a model that reaches for one reaches for all of them.
_QUOTES = {
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "’": "'",  # RIGHT SINGLE QUOTATION MARK  <- `I can’t`, `Zaa’beel`
    "‛": "'",  # SINGLE HIGH-REVERSED-9
    "ʼ": "'",  # MODIFIER LETTER APOSTROPHE — common in Arabic transliteration
    "ʻ": "'",  # MODIFIER LETTER TURNED COMMA — likewise
    "“": '"',  # LEFT DOUBLE QUOTATION MARK
    "”": '"',  # RIGHT DOUBLE QUOTATION MARK
    "″": '"',  # DOUBLE PRIME
}

_TABLE = str.maketrans({**_SPACES, **_ZERO_WIDTH, **_QUOTES})


def normalise(text: str | None) -> str:
    """Fold typographic characters onto their ASCII equivalents.

    Called by `extract_numbers` and `mentioned_names` before either looks at anything, so
    that neither can be defeated by a character choice. Returns "" for None so callers do
    not each write the same guard.
    """
    if not text:
        return ""
    return text.translate(_TABLE)
