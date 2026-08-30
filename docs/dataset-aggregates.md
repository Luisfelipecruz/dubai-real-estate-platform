# Dataset-wide aggregates — the M-44 gap, and the one it was hiding

> **Status: BUILT, UNCOMMITTED, NOT YET REGISTERED. 2026-08-30.**
> The service, the argument schema and the handler exist and are tested — 6 files,
> 61 tests, 441 API tests passing overall. **The tool is not in `TOOLS` yet**, because
> `api/services/agent/tools.py` is claimed by an uncommitted milestone. The registration is
> three lines and they are printed in §5.

---

## 1. What M-44 recorded

`eval/golden/answers.yaml` grades 40 questions. Six of them were **declined although the
data answers them** — the agent said, in as many words, *"I don't have a tool that can
return..."* — because all nine tools are area-scoped and nothing computes across the
dataset. M-44 called it the largest single block of failures and most of the distance
between 31/40 and the 0.90 target, and recorded it rather than fixing it: an eval milestone
that quietly edits the system it measures has stopped being an eval.

| id | question | what it needs |
|---|---|---|
| A-06 | How many property transactions were recorded in 2024? | count + year |
| A-11 | How many villa transactions are in the dataset? | count + property type |
| A-12 | How many transactions were recorded in 2025? | count + year |
| A-18 | What is the median price per square metre across all recorded sales? | median of a second measure |
| A-19 | What is the median sale price of a villa? | median + property type |
| A-21 | What is the largest single transaction value in the dataset? | an extreme |

All six are the same operation with different arguments. That is the whole design.

---

## 2. One tool, not six

`SESSION-HANDOFF.md` raised the objection before the work started: *adding one tool would
close it — is that the right fix, or the first step toward the thirty-three-tool design m15
rejected on purpose?*

The answer is the rule m15 already wrote down. *Operations that differ only by filter
parameters collapse into one tool.* Six questions are one operation over a closed product:

```
metric x dataset x measure x {year, property_type} x breakdown_by
  5    x    3     x   ≤3    x  int, closed-set    x  3 (incl. none)
```

Every dimension except `property_type` is an enum in the JSON Schema, so constrained
decoding cannot emit a value that does not exist. `property_type` is deliberately open —
its values are a property of the loaded data, not of this code — and that is precisely the
case rule 1 below exists for. The tool count goes from nine to ten and stops there; adding
a seventh question adds no tool and no tokens.

`area_name` is deliberately **not** a dimension. `area_summary` and `area_price_history`
already take one, and a second tool answering the same question is exactly the routing
failure `eval/golden/routing.yaml` grades. The description says so and names the other
tool, because routing in this repository is enforced in the descriptions.

### 2.1 What was built

| file | what it is | tests |
|---|---|---|
| `api/services/aggregates/spec.py` | pure: the closed universe, the five rules, the refusal wording | 40, no database |
| `api/services/aggregates/queries.py` | one statement per question, over the RAW tables | — |
| `api/services/aggregates/tool.py` | argument model, description, handler, registration | — |
| `api/tests/test_aggregates.py` | the rules, then the six questions against their own golden SQL | 21 against the live tables |
| `api/services/aggregates/__init__.py` | the five rules stated where they will be read | — |
| `docs/dataset-aggregates.md` | this file | — |

**61 tests: 40 pure, 21 live.** The API suite goes from 380 to 441.

### 2.2 Five rules, and each one is a way a number can lie

1. **An unrecognised filter value is a refusal that names the alternatives, never a zero.**
2. **A year outside the dataset's coverage is a refusal, never a zero.**
3. **A period that is not wholly inside the coverage says it is partial.**
4. **A median needs at least three rows, and that floor is arithmetic.**
5. **Every result reports what its own filters excluded.**

Rules 1 and 2 are the same idea seen twice, and it is the idea the whole module exists for:
`WHERE property_type_en = 'Apartment'` is valid SQL over `raw_transactions` and returns
zero rows. **Zero is a number.** It renders as *"there are no apartment sales in Dubai"*,
which is false, and nothing in the response distinguishes it from a genuine absence. So the
value is matched against the live universe first and a miss is refused with the four values
that exist:

```
property_type_en='Apartment' does not exist in transactions. The recorded values are:
'Unit', 'Villa', 'Land', 'Building'. Nothing matches 'Apartment', so this is not a count
of zero -- it is a filter that cannot be applied.
```

A difference of case or surrounding space is *not* a different question, so `villa`,
`VILLA` and ` Villa ` all resolve to `Villa`, and the canonical spelling the table returned
is what gets bound as the parameter. No code path here puts caller text into SQL text.

### 2.3 The median floor is arithmetic, not a rule of thumb

`PERCENTILE_CONT(0.5)` interpolates. Below three rows it is not reporting a middle value:

- **n = 1** — the median is the only value, which is also the minimum and the maximum. An
  extreme wearing the name of a centre.
- **n = 2** — it returns `(lo + hi) / 2`, the **midrange**: a value no row has, and the most
  outlier-sensitive statistic there is.
- **n = 3** — the middle row, which is what "median" means.

`raw_transactions` demonstrates all three, and the live tests read them rather than assuming
them:

| year | n | min | max | reported median | what it actually is |
|---|---|---|---|---|---|
| 1977 | 1 | 1,500,000 | 1,500,000 | 1,500,000 | the minimum, the maximum, and the median |
| 1989 | 2 | 4,500,000 | 7,002,461 | 5,751,230.50 | `(lo+hi)/2`, belonging to neither sale |
| 1991 | 3 | 750,000 | 7,000,000 | **800,000** | a real row — the midrange would be 3,875,000, **4.8× too high** |

Below the floor the value is `null` and the reason travels with it. It is **not** rounded up
to a comfortable number: three is where the definition starts holding, and anything above
it is taste dressed as arithmetic. This is the same shape of argument as
`observability.shaping.min_sample_for`, arrived at independently and for a different
aggregate.

### 2.4 There is no mean, and the reason is a number

`METRICS` is `count, median, maximum, minimum, total`. Over all 200,001 transactions:

```
mean   actual_worth = AED 3,881,668
median actual_worth = AED 1,356,000      -- the mean is 2.9x the median
max    actual_worth = AED 13,786,936,424 -- 1.78% of the value of all 200,001 rows
```

Omitting the metric is not enough on its own. The reason ships to the model inside the
metric's field description, which is where the decision is actually made:

> *"There is NO mean: over all 200,001 sales the mean is 2.9× the median because one row is
> AED 13.79 bn, so use median for anything described as typical or average."*

---

## 3. What building the fix turned up

### 3.1 The three datasets do not cover the same time, and nothing said so

This is the finding. It was not what the milestone set out to do.

| dataset | rows | coverage | heaviest year | share |
|---|---|---|---|---|
| `raw_transactions` | 200,001 | 1977-04-25 → 2026-02-17 | 2025 | 16.0% |
| `raw_rent_contracts` | 358,008 | 1925-08-04 → 2031-05-08 | 2026 | **89.5%** |
| `raw_valuations` | 3,106 | 2026-01-02 → 2026-08-14 | 2026 | **100%** |

Only the first is a history. The rent contracts are a **snapshot of what is registered
now** — 89.5% start in 2026, another 9.5% in 2025, and 190 rows start in the *future*, out
to 2031-05-08. The valuations are a single seven-month window.

`dataset_overview`, the tool that exists so the agent can refuse well, reports three row
counts and the **transaction** date range. Nothing tells a model that the other two datasets
are shaped differently. So:

- *"How many rent contracts were signed in 2023?"* → **979**. Correct SQL. It is 0.27% of a
  snapshot, and it reads as a market fact about Dubai.
- *"How many valuations were recorded in 2024?"* → **0**. Correct SQL. It means *this
  dataset does not go back that far*, and it renders as *no property was valued in Dubai in
  2024*.

The second is now a refusal:

```
valuations holds no rows dated 2024: it covers 2026 only (2026-01-02 to 2026-08-14).
This is a gap in coverage, NOT a count of zero -- do not report it as 'no recorded
valuations in 2024'.
```

The first is answered, with the shape of the dataset attached to the answer:

```
rent_contracts is a snapshot, not a history: 89.5% of its rows fall in 2026. A per-year
figure from it describes what is registered, not what happened. 2023 holds 0.27% of the
dataset.
```

A dataset-wide filter over a dataset whose coverage nobody has stated is not a missing
feature. It is a confident wrong answer waiting for the feature to arrive — which is why
M-44's six declined questions were, in a narrow sense, the system behaving better than the
naive fix would have.

### 3.2 The median sale price and the median price per m² disagree, and both are true

`price_per_sqm` is a measure and not a footnote because of this:

| year | median sale price | median AED/m² | median floor area |
|---|---|---|---|
| 2022 | 1,550,000 | 11,735 | 118.5 m² |
| 2023 | 1,476,888 | 13,179 | 103.4 m² |
| 2024 | 1,488,350 | 15,180 | 94.1 m² |
| 2025 | 1,529,409 | 16,794 | 90.1 m² |
| **2022 → 2025** | **−1.3%** | **+43.1%** | **−24.0%** |

*"The median Dubai property price has been flat since 2022"* and *"Dubai property prices are
up 43% since 2022"* are both true, from the same table, and the difference is entirely that
the median unit got smaller. A tool offering only `sale_price` answers **flat** to a
question about prices and is not wrong about anything except which question it answered.

That is the same failure mode as M-44 itself, one level down: the missing measure does not
merely decline, it changes which true statement gets made.

### 3.3 The row that is in `COUNT(*)` and in no year

`raw_transactions` has exactly one row with a null `instance_date`. `COUNT(*)` is 200,001
and the year buckets sum to 200,000. Any panel showing both without saying so looks like it
lost a row, so every year-filtered result carries the line — and a live test asserts the two
numbers reconcile through `Coverage.undated_rows` rather than trusting that they do.

Two rows have no usable `meter_sale_price`, so A-18's median is taken over 199,999 of the
200,001 the question matched. Both counts are reported. The exclusion is an aggregate
`FILTER`, not a `WHERE`, precisely so that the rows stay countable and the result can say
which denominator it used.

---

## 4. Verification — the six answers, against their own golden SQL

The live tests do **not** assert a literal. Each runs the question's own `ground_truth_sql`
from `eval/golden/answers.yaml` — hand-written against the raw tables so an expected value
can never come out of the code under test — and compares it to what `aggregate()` returns.
A reload moves both sides together, which is the property that file was designed around.

| id | `aggregate(...)` | value | golden |
|---|---|---|---|
| A-06 | `transactions, count, year=2024` | 26,889 | ✅ exact |
| A-11 | `transactions, count, property_type='Villa'` | 35,577 | ✅ exact |
| A-12 | `transactions, count, year=2025` | 32,065 | ✅ exact |
| A-18 | `transactions, median, price_per_sqm` | 11,571.24 | ✅ exact |
| A-19 | `transactions, median, sale_price, property_type='villa'` | 2,400,000.00 | ✅ exact |
| A-21 | `transactions, maximum, sale_price` | 13,786,936,424.00 | ✅ exact |

Note A-19: the argument was the lower-case `'villa'`, resolved to `'Villa'` before it
reached SQL.

**This is not the same as the eval passing.** These six are answerable *by the service*.
Whether the agent *routes* to it is a question only `make eval` can answer, and it cannot be
asked until the tool is registered — which is §5.

---

## 5. What is missing, and it is one file

`api/services/agent/tools.py` is claimed by an uncommitted milestone (m15), so the tool
cannot be added to `TOOLS` yet. Everything the registration would carry lives in
`tool.py` and is tested there, so the blocked edit is three lines and none of them is a
decision:

```python
from services.aggregates.tool import DatasetAggregateArgs, dataset_aggregate, DESCRIPTION

# ... in TOOLS, alongside the other four `sql` tools:
    Tool(
        name="dataset_aggregate",
        description=DESCRIPTION,
        category="sql",
        arguments=DatasetAggregateArgs,
        handler=dataset_aggregate,
    ),
```

**One deviation from house style, and it is forced by that blockage.** `tools.ToolFailed`
is the repository's mechanism for a decline, and `tools.run` catches it *by name*; anything
else is logged with a traceback as a bug. Raising `ToolFailed` from here would make this
tool depend on a second one-line change inside a file this milestone must not touch, and a
handler that is only correct if someone remembers that change is a handler that will be
wired wrong. So a refusal comes back as `{"refused": true, "reason": ..., "note": ...}` and
the payload carries the recovery path either way.

Whoever finishes this may prefer the other shape. It is one line in `tools.run`:

```python
    except AggregateRefused as exc:
        return str(exc), True
```

and then `tool.py` raises instead of catching. Both are defensible; only one of them is safe
to ship half-wired.

**Also blocked, and deliberately not worked around:**

| what | needs | claimed by |
|---|---|---|
| registering the tool | `api/services/agent/tools.py` | m15 |
| re-running the answer eval to see 31/40 move | the registration above | m15 |
| a response model on `/agent/runs` (M-63) | `api/routers/agent.py` | m15 |
| the release note | `docs/changelog.md` | m15 |

There is no fifth deferred changelog block. m21 is unregistered, so there is no version to
write.

---

## 6. For whoever finishes this

1. **Register the tool. Then run `make eval` and read the result before believing anything
   in §4.** Six questions being answerable by a service is not six questions passing. The
   routing eval has no dataset-wide question in it at all — every question in
   `eval/golden/routing.yaml` names an area, which is why M-44 was invisible to it — so
   **`routing.yaml` needs a dataset-wide case too**, or the next coverage gap will be
   invisible for the same reason.
2. **Do not add an `area_name` filter to this tool.** Two tools that answer one question is
   the failure the routing eval exists to catch.
3. **Do not tune the median floor.** §2.3 is arithmetic; tuning it means arguing with
   `PERCENTILE_CONT`.
4. **`dataset_overview` should probably report per-dataset coverage** — §3.1 is a gap in
   *that* tool, and `queries.coverage()` already computes exactly what it is missing. It is
   one field on a tool m15 claims, and it is the highest-value line in this document.
