"""The half of observability that has no database, no network and no clock.

Everything here is a pure function over counts. That is not fastidiousness: each of these
functions exists to stop the panel stating a number the data does not support, and a rule
that cannot be unit-tested is a rule that survives exactly until someone is in a hurry.

`queries.py` counts rows. This module decides what those counts are allowed to say.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

# Only two buckets, and both are `date_trunc` units so the SQL stays one GROUP BY.
# Minutes were considered and dropped: at 213 runs over six hours, a minute bucket is
# 360 buckets of which 340 are empty, which is a chart of rule 2 and nothing else.
BUCKETS: dict[str, timedelta] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
}

# Reported percentiles. p50 says what a normal run costs the person waiting; p95 says what
# the bad ones cost. The mean is deliberately absent -- a 66-second outlier drags it, and
# nobody waits for the mean.
QUANTILES: tuple[float, ...] = (0.5, 0.95)


def min_sample_for(quantile: float) -> int:
    """The smallest n at which `percentile_disc(q)` is not simply the maximum.

    Postgres' `percentile_disc` returns the first ordered value whose cumulative fraction
    reaches `q`. With n rows that is the `ceil(q * n)`-th value, so the answer is the
    maximum exactly while `ceil(q * n) == n`, which holds for every `n < 1 / (1 - q)`.

    For p95 that is n < 20, and it is not a rule of thumb -- it is arithmetic, and the live
    table agrees with it at the boundary: the 3-run and 2-run hours report a p95 equal to
    their own maximum, and the 32-run and 40-run hours do not.

    Reporting the maximum under the name "p95" is the specific lie this guards against: it
    reads as a tail statistic, so a single slow run becomes "the 95th percentile doubled".
    Above this floor the percentile is at least a percentile. It is not thereby a good
    estimate, which is why the bucket keeps `runs` beside it.
    """
    if not 0.0 < quantile < 1.0:
        raise ValueError(f"quantile must be strictly between 0 and 1, got {quantile!r}")
    return math.ceil(1.0 / (1.0 - quantile))


def rate(numerator: int | None, denominator: int | None) -> float | None:
    """A ratio, or `None` when there is nothing to divide.

    Returning `None` rather than `0.0` is rule 2 in one line. Zero errors out of zero calls
    is not a zero error rate; it is the absence of a measurement, and the two render very
    differently once someone is deciding whether to page.
    """
    if not denominator:
        return None
    return (numerator or 0) / denominator


def split_categories(value: str | list[str] | None) -> list[str]:
    """The routing categories of a run, always as a list.

    `agent_runs.categories` is a comma-joined string because that is what `executor.py`
    inserts, while `POST /agent/query` returns the same field as a list. M-63: two shapes
    for one field, and the consumer that guesses wrong gets `['m','e','t','a']` from
    iterating a string rather than a crash. Normalising here means the panel never has to
    know which side of the divide its data came from.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [c for c in (str(v).strip() for v in value) if c]
    return [c for c in (part.strip() for part in value.split(",")) if c]


@dataclass(frozen=True)
class Bucket:
    """One time bucket of agent runs, with its counts and its derived rates.

    Counts are integers straight out of the GROUP BY. Rates are properties, so a bucket
    cannot be constructed with a rate that disagrees with its own counts.
    """

    start: datetime
    runs: int = 0
    answered: int = 0
    refused: int = 0
    max_steps: int = 0
    failed: int = 0
    # Runs whose outcome is `answered` and whose answer is blank. Rule 5: this is the
    # M-47 population, and it is not the same as "runs with no answer text" -- a
    # `max_steps` or `failed` run is blank for a reason that is not a bug.
    answered_empty: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    unverified_numbers: int = 0
    p50_ms: int | None = None
    p95_ms: int | None = None
    cost_usd: float | None = None
    cost_priced_runs: int = 0

    @property
    def empty(self) -> bool:
        return self.runs == 0

    @property
    def refusal_rate(self) -> float | None:
        return rate(self.refused, self.runs)

    @property
    def cap_rate(self) -> float | None:
        return rate(self.max_steps, self.runs)

    @property
    def failure_rate(self) -> float | None:
        return rate(self.failed, self.runs)

    @property
    def tool_error_rate(self) -> float | None:
        return rate(self.tool_errors, self.tool_calls)

    @property
    def empty_answer_rate(self) -> float | None:
        """Blank answers as a share of the runs that CLAIM to have answered."""
        return rate(self.answered_empty, self.answered)

    @property
    def cost_complete(self) -> bool:
        """Whether every run in the bucket was priced.

        `$0.00` and `null` are different facts, and so is a total summed over a bucket
        where some runs could not be priced at all. A partial total is presented as
        partial or not presented.
        """
        return self.runs > 0 and self.cost_priced_runs == self.runs


def bucket_span(bucket: str) -> timedelta:
    """The width of one bucket. Raises on an unknown name rather than defaulting."""
    try:
        return BUCKETS[bucket]
    except KeyError:
        raise ValueError(
            f"unknown bucket {bucket!r}; expected one of {', '.join(sorted(BUCKETS))}"
        ) from None


def bucket_floor(moment: datetime, bucket: str) -> datetime:
    """Floor a moment to the start of its bucket, in UTC.

    Flooring happens in UTC because that is what the column stores and what `date_trunc`
    is given. Doing it in a local zone would make the two sides of `fill_gaps` disagree
    twice a year, and the resulting hole would look like an outage.
    """
    span = bucket_span(bucket)
    moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
    if span == timedelta(days=1):
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return moment.replace(minute=0, second=0, microsecond=0)


def fill_gaps(
    buckets: list[Bucket], *, bucket: str, since: datetime, until: datetime
) -> list[Bucket]:
    """Return one bucket per interval in `[since, until]`, inserting empty ones.

    Rule 2. The GROUP BY cannot emit a row for an interval with no runs, so a chart drawn
    from its output silently joins 18:00 to 20:00 and the hour with no traffic at all
    disappears. Every metric on an inserted bucket is `None` rather than zero, because
    nothing was measured there.

    Both ends are inclusive of their bucket: `until` is floored like everything else, so
    asking for "up to now" includes the partial bucket in progress. That bucket is real but
    incomplete, which is a caveat for the renderer, not a reason to drop the newest data.
    """
    span = bucket_span(bucket)
    start = bucket_floor(since, bucket)
    end = bucket_floor(until, bucket)
    if end < start:
        return []

    seen = {b.start: b for b in buckets}
    out: list[Bucket] = []
    cursor = start
    while cursor <= end:
        out.append(seen.get(cursor, Bucket(start=cursor)))
        cursor += span
    return out


def suppress_thin_percentiles(bucket: Bucket) -> Bucket:
    """Blank any percentile the bucket does not have the sample size to support.

    Rule 3. Applied after the query rather than inside it so the floor is one testable
    number in one place, instead of a `CASE WHEN count(*) >= 20` repeated in every
    statement that ever reports a latency.
    """
    p50 = bucket.p50_ms if bucket.runs >= min_sample_for(0.5) else None
    p95 = bucket.p95_ms if bucket.runs >= min_sample_for(0.95) else None
    return replace(bucket, p50_ms=p50, p95_ms=p95)


@dataclass(frozen=True)
class Trend:
    """One metric compared against the same metric one bucket earlier.

    Carries the denominators that produced it, because a movement is only as real as the
    sample under it. The live table makes the point better than any argument: the two most
    recent hours hold three runs and two runs, and comparing them naively reports "the
    refusal rate rose 33 points, the empty-answer rate rose 100 points, the step cap rate
    rose 33 points" -- four alarms from five runs.
    """

    metric: str
    current: float | None
    previous: float | None
    delta: float | None
    direction: str  # "up" | "down" | "flat" | "indistinguishable" | "unknown"
    current_n: int | None = None
    previous_n: int | None = None
    resolution: float | None = None

    @property
    def conclusive(self) -> bool:
        return self.direction in {"up", "down", "flat"}


def resolution_of(n: int | None) -> float | None:
    """The smallest change a rate over `n` observations can express: 1/n.

    A rate measured over two runs moves in steps of 50 percentage points. It has no way to
    represent a 10-point change, so a 10-point change read off it is an artefact of the
    denominator rather than a fact about the system.
    """
    if not n:
        return None
    return 1.0 / n


def trend(
    metric: str,
    current: float | None,
    previous: float | None,
    *,
    current_n: int | None = None,
    previous_n: int | None = None,
) -> Trend:
    """Compare two values of one metric without inventing a comparison.

    Four things this deliberately does not do: no smoothing, no percentage-of-a-percentage,
    no threshold for "flat" other than exact equality WITH NO KNOWN RESOLUTION, and no
    direction claimed for a movement smaller than the coarser of the two samples' own
    resolution -- and a movement of exactly zero is one of those. That case is
    `indistinguishable`, which is a value the renderer has to handle rather than a boolean
    beside a red arrow it can ignore. `delta` is still returned: the number is real, it is
    the CONCLUSION that is unavailable.

    Passing no denominators means resolution is unknown, and the direction is reported as
    measured. That is correct for a metric that already guards its own sample size -- p95
    is blank below 20 runs, so a p95 that exists at all has the runs behind it.
    """
    if current is None or previous is None:
        return Trend(metric, current, previous, None, "unknown", current_n, previous_n)

    delta = current - previous
    resolutions = [r for r in (resolution_of(current_n), resolution_of(previous_n)) if r]
    resolution = max(resolutions) if resolutions else None

    # THE RESOLUTION CHECK COMES FIRST, AND THE ORDER IS THE WHOLE RULE.
    #
    # It did not, until 2026-08-30, and `test_health_compares_two_buckets...` caught it on
    # live data: `empty_answer_rate` 1.0 -> 1.0 over one run and three came back
    # `direction='flat'`, which reads as "the empty-answer rate is stable at 100%". Zero is
    # a movement, and it is a movement of less than one step. A rate over ONE observation
    # can only be 0.0 or 1.0; two such readings agreeing is not evidence that a rate is
    # steady, and `flat` is a conclusion just as much as `up` is.
    #
    # So with known denominators, equality is `indistinguishable`, not `flat`. `flat`
    # survives where resolution is unknown -- p95 and any metric that guards its own sample
    # size -- which is where "these two numbers are the same" really is the finding.
    if resolution is not None and abs(delta) < resolution:
        direction = "indistinguishable"
    elif delta == 0:
        direction = "flat"
    elif delta > 0:
        direction = "up"
    else:
        direction = "down"

    return Trend(
        metric, current, previous, delta, direction, current_n, previous_n, resolution
    )
