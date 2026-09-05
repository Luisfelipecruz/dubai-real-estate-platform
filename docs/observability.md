# Observability — the time dimension, and what it made visible

> **Status: FINISHED 2026-08-30 (five of six gates).**
> The producer writes one `agent_tool_calls` row per tool call, migration `0005` is
> applied, three endpoints are live, and `/copilot/runs` is a panel with a window
> selector. **Attribution was verified by forcing a tool error and watching the panel
> name it**: `resolve_area_name`, 1 call, 1 error, 100%. Gate 5 — a threshold from
> `eval/thresholds.yaml` shown with its live state — is the one still open. §5.

---

## 1. The two questions a log cannot answer

`GET /agent/runs` reports what happened. It cannot report:

- **Is it getting worse?** Every figure it returns is a lifetime aggregate over every run
  ever recorded. A refusal rate that doubled yesterday moves that number by a fraction of a
  point.
- **Which thing is broken?** The 10.3% tool error rate belongs to no tool, because the
  per-call records were never written down.

The first is fixed here. The second is *named* here and fixed by a producer that lives in
`api/services/agent/executor.py`, which m15 claims.

---

## 2. What was built

| file | what it is | tests |
|---|---|---|
| `api/services/observability/shaping.py` | the pure half: bucketing, gap filling, rates, trends, sample floors | 31, no database |
| `api/services/observability/queries.py` | the GROUP BY half: timeseries, lifetime, health, attribution, drill-in | 9, against the live table |
| `api/alembic/versions/0005_add_agent_tool_calls.py` | the per-call table the platform currently discards | applied + reversed |
| `frontend/src/lib/observability.ts` | the payload types and the formatting rules | 22 |
| `frontend/src/components/observability/TrendBadge.tsx` | one metric, this interval against the last | 11 |
| `frontend/src/components/observability/MetricSeries.tsx` | one metric over time, with gaps that stay gaps | 11 |
| `frontend/src/components/observability/AttributionNotice.tsx` | the tool error rate, and why it names no tool | 9 |

Measured 2026-08-30: **380 API tests** (was 340), **189 frontend tests** (was 136).
`tsc --noEmit` clean. `next build` clean, **still 12 routes** — the components are
deliberately not routed, because the pages that would route them are m18's files.

### 2.1 Five rules, and each one is a way the panel could lie

They live in the docstring of `api/services/observability/__init__.py` and each is pinned
by a test that needs no database.

1. **A lifetime average is not a current state.** §3 is this rule with the numbers in it.
2. **A gap is a gap.** An interval with no runs gets `runs = 0` and `null` for every rate,
   never `0%`. A zero error rate over zero calls is the most confident wrong number this
   table can produce.
3. **A percentile needs a sample.** See §2.2.
4. **An unattributable number says so.** See §2.5.
5. **A rate has a denominator and the denominator is an argument.** See §2.4.

### 2.2 The p95 floor is arithmetic, not a rule of thumb

`percentile_disc(q)` returns the `ceil(q·n)`-th ordered value, which is the largest one
while `ceil(q·n) = n` — that is, for every `n < 1/(1−q)`. For p95 the floor is **20 runs**,
and below it the "95th percentile" is the maximum wearing a percentile's name. One slow run
then reads as "the tail doubled".

The live table agrees at the boundary. The 2-run and 3-run hours report a p95 equal to
their own maximum (3474 and 65949); the 32-run and 40-run hours do not (38886 vs 39587,
43247 vs 56245).

So `min_sample_for(0.95) == 20` is derived, and anyone who wants to tune it has to argue
with the definition of the function.

### 2.3 The false alarms this caught in its own first draft

The first working version of `health()` compared the two most recent hours — three runs and
two — and reported:

```
refusal_rate       up   +33.3 pts
tool_error_rate    up   +12.5 pts
empty_answer_rate  up  +100.0 pts
cap_rate           up   +33.3 pts
```

Four alarms from five runs, on a panel whose whole purpose is being believed.

The fix is `resolution_of(n) = 1/n`: a rate over two runs moves in steps of 50 percentage
points, so it has no way to express a 33-point change, and a 33-point change read off it is
an artefact of the denominator. A movement smaller than the coarser of the two samples'
resolutions is reported as **`indistinguishable`** — a direction of its own, not a boolean
beside a red arrow.

```
refusal_rate       indistinguishable  +33.3 pts  (3 vs 2 runs)
tool_error_rate    indistinguishable  +12.5 pts  (8 vs 2 calls)
empty_answer_rate  up                +100.0 pts  (1 vs 2 runs)
cap_rate           indistinguishable  +33.3 pts  (3 vs 2 runs)
```

The one that survives is real: both runs that claimed to answer returned nothing, which
clears its own resolution. The delta is still returned in every case — **the number is
real; it is the conclusion that is unavailable.**

`indistinguishable` is a `TrendDirection` rather than a flag for the same reason m19's
tone is chosen from `event.ok` in one expression: there is no branch in `trendTone()` that
can reach `alarm` from it. A caveat next to a red arrow is not read; the arrow is.

### 2.4 The empty-answer rate has a denominator, and it is not `runs`

Ten of the 213 recorded runs have a blank answer. Two of them are a `max_steps` run and a
`failed` run, which are blank because they did not finish.

**The M-47 population is 8 of the 147 runs that reported `answered`: 5.4%, not 4.7%.**
The correct denominator makes the bug *bigger*, which is exactly why it matters which one
the panel shows. This is the before-number plan §12.7 gate 5 asks for, and it can be
re-taken at any time:

```sql
SELECT COUNT(*) FILTER (WHERE outcome = 'answered')                       AS answered,
       COUNT(*) FILTER (WHERE outcome = 'answered'
                          AND (answer IS NULL OR btrim(answer) = ''))     AS answered_empty
  FROM agent_runs;
```

### 2.5 Migration 0005, and why nothing is backfilled

`agent_tool_calls` keyed on `agent_run_id`: step, tool name, category, arguments as JSONB,
`ok`, error, `duration_ms`, `repeated`. Three indexes, one of them partial on `NOT ok`
because failures are the minority and the interesting set.

Applied against the live database and reversed, on 2026-08-30. The table shape and all
three indexes were read back from `\d agent_tool_calls`; the full suite passes at `0005`
and at `0003`. The database was left at **0003**, so it still matches what the four
uncommitted milestones expect.

**Not stored: the tool result.** A result can be a truncated 8 KB SQL payload; 301 of them
is a table growing faster than the runs it describes, answering no question the panel asks.
The arguments *are* stored, because "`resolve_area_name` failed on which name?" is the
first question after "which tool failed".

**Not backfilled, because there is nothing to backfill from.** The per-call records for the
213 existing runs are gone. Distributing the 31 known failures across tools by frequency
would produce a chart that looks like evidence and is fiction. Attribution starts at the
migration, and `tool_error_attribution()` distinguishes three states rather than two:

| state | what it returns |
|---|---|
| table absent | the rate, `attributable: false`, and the migration that would fix it |
| table present, no rows | the rate, `attributable: false`, and *"covers runs recorded after 0005 only"* |
| table present with rows | the rate and the per-tool breakdown |

The middle row is the one worth having. "The table exists and is empty" is not "no errors",
and a per-tool chart fed by it would render as a healthy system.

---

## 3. What the panel makes visible that `/copilot/runs` does not

Read out of the live table through the query layer, 2026-08-30:

```
bucket  runs  refusal  toolerr  empty(ans)     p50     p95
 17:00    49    18.4%    12.3%       0.0%    6.0 s   22.1 s
 18:00    32    18.8%     9.1%       0.0%    8.3 s   38.9 s
 19:00     0        —        —          —        —        —
 20:00    87    36.8%    10.1%       9.1%    7.4 s   46.6 s
 21:00    40    40.0%     9.1%       8.3%    7.7 s   43.2 s
 22:00     2     0.0%     0.0%       0.0%    2.1 s        —
 23:00     3    33.3%    12.5%     100.0%   13.8 s        —
```

Four things the lifetime figures cannot show, and one they actively hide:

1. **The refusal rate more than doubled inside one session** — 18.4% → 18.8% → 36.8% →
   40.0%. The lifetime number is **30.0%**, which is the mean of a rising line and was true
   at no point in the session. This is the single strongest argument that the existing page
   is a log.
2. **An hour with no runs at all.** A chart drawn as one continuous path joins 18:00 to
   20:00 with a straight line indistinguishable from an hour of steady performance — it
   would invent its most reassuring data point. `segments()` makes that undrawable.
3. **Four of the seven hours cannot state a p95**, and two cannot state one at all. The
   lifetime p95 of 38.9 s is real; three of the per-hour ones would have been the maximum.
4. **The tail is thin, and nothing in it is worth paging over** (§2.3).
5. **The tool error rate is flat** — 12.3%, 9.1%, 10.1%, 9.1%, 12.5% — while the refusal
   rate doubles. Two numbers that sit next to each other on the current page as a pair of
   integers, moving completely differently.

Also worth recording, from the same read: `llm_calls` holds 699 rows of which **515 are
attributed to an agent run**; the other 184 are direct `/ask` traffic. The `endpoint` and
`agent_run_id` columns migration 0003 added are doing the job they were added for.

**And the thing it does NOT make visible:** which of the nine tools owns the 10.3%. Plan
§13.6 gate 6 expected that to be the headline. It is not available, and no amount of
frontend work substitutes for data that was never written down.

---

## 4. What is missing, and it is one blocker

`git status` at the time of writing: four uncommitted milestones, m19's seven files, and
now these ten. Every path m20's remaining work needs is claimed by one of them.

| path | needed for | claimed by |
|---|---|---|
| `api/services/agent/executor.py` | **the producer** — one insert per tool call | m15 |
| `api/routers/agent.py` | `/agent/runs/timeseries`, `/agent/runs/{id}`, `/agent/tools/stats` | m15 |
| `api/main.py` + `api/tests/test_main.py` | a fifth name in `COPILOT_ROUTERS` for a new `routers/evals.py` | m17 — `test_registration_list_is_the_full_planned_set` asserts the tuple exactly |
| `frontend/src/app/copilot/runs/` | the panel page | m18 — staged as a **directory** |
| `frontend/src/app/evals/` | thresholds beside live measurements | m18 — staged as a **directory** |
| `frontend/jest.config.ts` | `collectCoverageFrom` covers `src/components/copilot` only | m18 |
| `docs/changelog.md` | the release note | m15 |

The last one is worth naming: the new component directories are **not** in
`collectCoverageFrom`, so their tests run and their coverage is not counted. `jest.config.ts`
is m18's file. One line, in #35.

So the milestone stops at the seam: `api/services/observability/`, `api/models/`-adjacent
free paths, `frontend/src/lib/observability*.ts` and
`frontend/src/components/observability/` are claimed by no manifest and swept by no `git
add` argument in §A.3–§A.7 — verified with `git add --dry-run`, not assumed.

---

## 5. Gate status — five of six

| # | gate | |
|---|---|---|
| 1 | migration applies, and a new run writes one row per tool call | ✅ verified live — one run, one row |
| 2 | the panel names the failing tool | ✅ **forced a tool error**: `resolve_area_name`, 1/1, 100% |
| 3 | every figure traceable to an API response; no arithmetic in the browser | ✅ `observability.ts` has no function that divides |
| 4 | a window selector changes the numbers | ✅ 24 h hourly / 7 d daily / 30 d daily |
| 5 | a threshold from `eval/thresholds.yaml` with its live pass/fail state | ❌ needs `GET /evals/latest` — a new router and a fifth `COPILOT_ROUTERS` name |
| 6 | the write-up records what the panel made visible | ✅ §3, and it was not what §13.6 predicted |

**Gate 6 did not go the way it was written.** §13.6 assumed the headline would be which of
the nine tools owns the 10.3%. Two things changed that. The tool count is ten now, not
nine — m21 added `dataset_aggregate`. And attribution starts at migration `0005`, so the
answer for the 213 historical runs is *permanently unavailable*: those per-call records
were never written and cannot be reconstructed. What the panel says instead is the honest
version — `attributable: true`, covering runs since the migration, currently two of them.

What it made visible on the way there was better: the lifetime page reports a **11.3%**
tool error rate while the most recent hour ran **40%**, and the most recent hour's
`empty_answer_rate` reports `indistinguishable` rather than a direction because it is
three runs against one.


## 6. For whoever finishes this

- **The producer is the first task, not the endpoint.** Until `executor.py` writes to
  `agent_tool_calls`, gates 1, 2 and 6's headline are all blocked on the same missing insert.
  It belongs inside the same transaction that writes the run — losing a tool row must never
  cost a caller their answer, which is why there is no foreign key.
- **`_INSERT_RUN` writes at the END of the loop.** The tool rows are produced before it, so
  the insert order is tool calls first, run last — the opposite of what a foreign key would
  require, and the reason `agent_tool_calls.agent_run_id` has none.
- **Do not relax the sample floors to make the panel look busier.** They are the difference
  between a panel and a decoration, and both are derived rather than chosen (§2.2, §2.3).
- **Keep `PERCENTILE_DISC`.** `/agent/runs` uses `PERCENTILE_CONT`, which interpolates and
  returns a latency no run ever had. Beside a drill-in list, a p95 that matches no row costs
  an afternoon.
- **The panel says "since migration 0005"** wherever it shows per-tool data, and means it.
