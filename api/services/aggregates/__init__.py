"""Dataset-wide aggregates: the coverage gap M-44 measured, and the one it hid.

M-44 recorded that SIX of the 40 graded answer questions were declined although the data
answers them -- totals and medians over the whole dataset rather than over one area. All
nine agent tools take an area name; nothing computes across the dataset. It is the largest
single block of eval failures and most of the distance between 31/40 and the 0.90 target.

Building the fix turned up why the missing tool was DANGEROUS rather than merely absent.
The three datasets have completely different time coverage and nothing in the system says
so: transactions run 1977-2026, rent contracts are 89.5% one year, and every one of the
3,106 valuations falls inside a seven-month window in 2026. A dataset-wide year filter
over a dataset nobody has stated the coverage of returns a number that is correct SQL and
a wrong answer -- 979 for "rent contracts signed in 2023", which is 0.27% of a snapshot
and reads as a market fact. See `docs/dataset-aggregates.md`.

FIVE RULES, and each one exists because the naive version returns a number instead.

1. An unrecognised filter value is a REFUSAL that names the alternatives, never a zero.
2. A year outside the dataset's coverage is a REFUSAL, never a zero.
3. A period that is not wholly inside the coverage says it is partial.
4. A median needs at least three rows, and that floor is arithmetic (`spec.MIN_ROWS_FOR_MEDIAN`).
5. Every result reports what its own filters excluded.

`spec.py` decides what a number is allowed to say; `queries.py` runs the one statement that
produces it. Same split as `services/observability/`, for the same reason: the rules are
worth unit-testing without a database in the way.
"""

from services.aggregates.queries import aggregate, breakdown, coverage
from services.aggregates.spec import (
    DATASETS,
    METRICS,
    MIN_ROWS_FOR_MEDIAN,
    Aggregate,
    AggregateRefused,
    Coverage,
    DatasetSpec,
    Group,
    Measure,
    canonical_filter_value,
    caveats_for,
    dataset_spec,
    measure_for,
    min_rows_for_median,
    period_state,
    share,
)

__all__ = [
    "DATASETS",
    "METRICS",
    "MIN_ROWS_FOR_MEDIAN",
    "Aggregate",
    "AggregateRefused",
    "Coverage",
    "DatasetSpec",
    "Group",
    "Measure",
    "aggregate",
    "breakdown",
    "canonical_filter_value",
    "caveats_for",
    "coverage",
    "dataset_spec",
    "measure_for",
    "min_rows_for_median",
    "period_state",
    "share",
]
