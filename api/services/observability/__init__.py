"""Observability over `agent_runs`: the time dimension the runs page does not have.

`GET /agent/runs` answers *what happened*. It cannot answer *is it getting worse*, because
every figure it returns is a lifetime aggregate over every run ever recorded, and it cannot
answer *which thing is broken*, because the per-tool records are thrown away when the
request ends. Those are the two questions that separate a panel from a log.

The split here follows what can be tested without a database:

    shaping.py   pure functions -- bucketing, gap filling, rates, trends, and the rule
                 that decides when a percentile is allowed to be reported at all.
                 No SQL, no connection, no clock. Unit-tested exhaustively.
    queries.py   the GROUP BY. One statement per question, `text()` over
                 `engine.connect()`, the same shape `/agent/runs` and `/ask/costs` use.

The arithmetic is deliberately NOT in the browser and deliberately NOT in the SQL. Postgres
counts; Python decides what may be shown. Keeping the second half pure is what makes the
five rules below assertable rather than aspirational, and every one of them exists because
the live table can produce a number that looks fine and means nothing:

1.  A LIFETIME AVERAGE IS NOT A CURRENT STATE. The 213 recorded runs give a 30.0% refusal
    rate. Bucketed by hour that is 18.4%, 18.8%, 36.8%, 40.0% -- a line that doubled, whose
    average is a number that was never true at any point in the session.

2.  A GAP IS A GAP. There are no runs at all in the 19:00 hour. A bucket with no runs gets
    `runs = 0` and `None` for every rate, never `0%` -- a zero error rate over zero calls is
    the most confident wrong number this table can produce.

3.  A PERCENTILE NEEDS A SAMPLE. `percentile_disc(0.95)` returns the maximum whenever
    `n < 20` (see `min_sample_for`). Below that it is the largest value wearing a
    percentile's name, so it is reported as `None`.

4.  AN UNATTRIBUTABLE NUMBER SAYS SO. The 10.3% tool error rate cannot be split by tool:
    `agent_runs` stores `tool_calls` and `tool_errors` as integers and the individual
    `ToolInvocation` records are never persisted. `tool_error_attribution` returns that
    fact and the migration that would fix it, not an empty chart.

5.  A RATE HAS A DENOMINATOR AND THE DENOMINATOR IS AN ARGUMENT. Ten of 213 runs have a
    blank answer, but two of them are a `max_steps` run and a `failed` run, which have no
    answer for honest reasons. The bug is 8 of the 147 runs that claim to have ANSWERED:
    5.4%, not 4.7%.
"""

from services.observability.shaping import (  # noqa: F401
    BUCKETS,
    Bucket,
    bucket_floor,
    bucket_span,
    fill_gaps,
    min_sample_for,
    rate,
    resolution_of,
    split_categories,
    suppress_thin_percentiles,
    trend,
)
