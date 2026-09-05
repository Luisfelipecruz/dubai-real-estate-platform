# The evaluation endpoint

`GET /evals/latest` — what this deployment currently proves about itself, and how far that
claim can be trusted.

> Every number under "The run of 2026-09-05" is read out of Postgres or printed by the
> run that produced it.

---

## 1. What it returns

The most recently **recorded** evaluation run, joined to every floor in
`eval/thresholds.yaml`.

```
available            false when nothing has been recorded — a 200, not a 404
recorded_at          when the RUN finished, set by the harness
age_seconds          how old the measurement is
suite                truths | retrieval | agent | all
gate_applied         whether the floors were compared at all
gate_passed          the verdict, or null when no gate ran
floors[]             one entry per threshold: floor, actual, margin, state
summary              how many are ok / failing / not measured
counts               the denominators behind each rate
coverage             how much of the linked routing set the run actually graded
registry             what changed in the tool layer since the run
```

### 1.1 It does not run the suite

A full run is tens of minutes of model calls against the live agent. A handler that
triggered one would turn a page refresh into a billing event and a request that cannot
finish inside any sane timeout. Only `make eval` records a result.

### 1.2 It computes nothing

Every rate, margin, count and staleness verdict comes out of
`services/evaluation/results.assess`, which is pure and directly asserted in
`api/tests/test_eval_results.py`. No number reaches a client without a test behind it, and
the browser derives none of its own — a client that could compute `passed / n` would
compute it for a run that measured nothing, get `0/0`, and render `0.0%`.

## 2. Three states per floor

```
ok             measured, and at or above the floor
fail           measured, and below it
not_measured   this run produced no value for that metric at all
```

An agent-only run measures nothing under `retrieval.`, and the third state exists so that
case cannot be absorbed into either neighbour. Rendering an unmeasured floor as passing
publishes a green gate nobody ran. Rendering it as failing makes a partial suite look like
a broken system, and the fix people reach for then is to stop looking.

## 3. The field to read before the score

`registry`, not `gate_passed`.

A pass rate is a statement about a system, and the system it describes is the one that was
running when the suite ran. The sharpest way for that to stop being true is a tool being
added: a new tool can answer questions the agent previously declined, so every rate derived
from those questions moves — while the recorded score, and its timestamp, say nothing at
all. An age is not enough, because a result a few days old sounds fresh.

So the registry is fingerprinted into every stored result and diffed against the live one
on read:

```json
"registry": {
  "known": true,
  "stale": true,
  "added_since": ["dataset_aggregate"],
  "removed_since": []
}
```

**Three values, not two.** `stale: null` with `known: false` is a result that carries no
fingerprint — an older row, or an API with the agent layer switched off — and it is not
`stale: false`. "Cannot tell" and "nothing changed" render differently, because a score
with no provenance must not look like one whose provenance was checked.

## 4. Why the results live in Postgres

`--out` already writes a JSON summary, and pointing the endpoint at the newest file on a
mounted volume would have been fewer moving parts. Two reasons it is a table.

**`eval/` is mounted read-only on purpose.** A container that can rewrite its own fixtures
can turn a failing evaluation into a passing one with nobody noticing. Results would need a
second, writable mount beside the read-only one, and a reader has to work out every time
which of the two is which.

**"Latest" is the wrong shape for the question this gets asked.** One number with no
history cannot say whether the system is improving, and a rate that moved sharply within a
day is invisible in any single reading of it. Rows with timestamps make that comparison
available without a second storage system.

What is **not** stored is the per-question detail: one model answer per question, which
would make the table grow faster than `agent_runs` while answering nothing the endpoint
asks. Those stay in the `--out` file, which is what re-grading reads.

## 5. Recording a run

`make eval` passes `--record`. The single-suite targets do not.

```
$ run_eval.py --suite agent --only A-01 --record
REFUSING to --record a --only run: it would publish a rate whose denominator is a
subset nobody chose to measure.
```

A single-question run stores a rate of 1.000 over a denominator of one — a true statement
about nothing that renders on a page as a perfect score. Refusing at the point of writing
is the whole of the protection: once the row exists the denominator is a number in a
database, and no rendering can undo it.

`--record-from PATH` records a summary written earlier by `--out` without re-running
anything. It is the recovery path for a suite that completed and failed to store its
result — the measurement is already in the file, and re-issuing every model call to get a
row into a table would be paying twice for one measurement. It re-applies the gate against
the current floors rather than trusting a stored verdict, re-derives the denominators from
the stored responses, and records in `metadata_source` whether the provenance came from the
file or from the command line.

## 6. The two questions that name no area

Every question in `eval/golden/routing.yaml` names a district, with two exceptions. That is
a real limit on what the set can express: it cannot be the thing that catches a tool layer
with no whole-dataset aggregate, because "the tool layer has no whole-dataset aggregate" is
not a proposition any area-scoped question can be false about.

| id | question | route | why this one |
|---|---|---|---|
| **R-15** | median price per m² across all recorded sales | `sql` | Expects `dataset_aggregate`; forbids the corpus and both area-scoped numeric tools. |
| **R-16** | property valuations recorded in 2024 | `refuse` | A refusal whose correct SQL answer is a number. |

**R-15 is a median and not a count, deliberately.** The obvious dataset-wide question is
"how many transactions in total" — and it is a *bad* routing question, because
`dataset_overview` reports row counts and would answer it correctly. Two tools legitimately
serving one question makes the route ungradable.

**R-16 is the only unanswerable question in the set whose ground-truth SQL would succeed.**
Every other abstention fails at the schema — no agency column, no developer margin, no
tenant age. This one runs, returns `0`, and 0 is both correct arithmetic and a false
sentence: all 3,106 valuations fall between 2026-01-02 and 2026-08-14, so the honest
reading is *this dataset does not go back that far* while the reading a person takes is *no
property was valued in Dubai in 2024*.

Its answer-side pair `A-41` carries **no** `ground_truth_sql`, deliberately: the harness
would resolve it to 0 and then grade an answer of "0" as CORRECT, which is the one verdict
that must not be available here.

### 6.1 The link is what makes them run

Adding a question to `routing.yaml` alone does nothing. `answers.yaml` is the driver:
`run_agent` issues one request per **answer** question and grades the route only when that
question carries a `routing_id`. R-15 is linked from A-18, R-16 from A-41.

Denominators moved with them: answers 40 → 41, routes 9 → 11. The floors in
`eval/thresholds.yaml` were argued from 40 and 9 and were **not** adjusted in the same
change, because a floor moved alongside its own denominator is a floor nobody can audit.

## 7. The run of 2026-09-05

Local provider, `gpt-oss:20b` on the host, 41 answer questions and the four-mode retrieval
ablation. **Every floor passed — 8 of 8.**

| floor | value | floor | margin |
|---|---:|---:|---:|
| `agent.answer_accuracy` | **0.805** | 0.70 | +10.5 pts |
| `agent.route_accuracy` | **0.900** | 0.77 | +13.0 pts |
| `agent.unanswerable_no_fabrication` | 1.000 | 1.00 | 0 |
| `agent.no_decoyed_answers` | 1.000 | 1.00 | 0 |
| `agent.injection_question_stays_out_of_the_corpus` | 1.000 | 1.00 | 0 |
| `retrieval.dense_top1_ideal` | 0.850 | 0.70 | +15.0 pts |
| `retrieval.dense_hit_at_5` | 0.900 | 0.80 | +10.0 pts |
| `retrieval.dense_mrr` | 0.881 | 0.75 | +13.1 pts |

**33/41 answers correct**, against 30/40 on the previous recorded run. The denominators are
printed beside the rate because the fixture gained a question between the two, and 0.750 →
0.805 across a moving denominator is not a comparison anyone can make from the percentages
alone.

Verdicts: 24 correct, 9 abstained, 2 partial, 1 wrong, 1 absent, 1 empty, 1 over-answered,
1 refused-wrongly, 1 error.

Both new questions did what they were added to do: **R-15** routed to `dataset_aggregate`
on the first call, with no corpus and no area-scoped tool, and returned **AED 11,571.24/m²**
— A-18's recorded value exactly. **R-16** refused.

### 7.1 An errored question used to leave the denominator instead of failing in it

`route_accuracy` on this run is **9/10**, not 9/11. Eleven questions carry a `routing_id`.
**A-26 never returned** — `HTTP 504: Ollama did not respond within 120s` — and an errored
record was appended without its `routing_id`, so the question left the linked set entirely.

A-26 is the hardest linked question there is: a spatial predicate joined to an aggregate,
the case that justifies having an agent loop at all. Graded as a failure the rate would be
9/11 = 0.818; dropped, it is 0.900. Both clear the floor, so nothing went red — and the
reported number was inflated by the removal of the hardest case, in the one direction a
reader will not think to distrust.

**This is now a third state.** A timeout is not a routing failure — grading infrastructure
as quality is its own lie — and shrinking the denominator without saying so is worse than
either. Both denominators are kept:

| field | means | on this run |
|---|---|---:|
| `route_ok` | routed correctly | 9 |
| `route_n` | graded, i.e. returned something to grade | 10 |
| `route_linked` | carrying a `routing_id` in the fixture | 11 |
| `route_errors` / `route_error_ids` | linked, and never answered | 1 · `["A-26"]` |

`route_accuracy` stays `route_ok / route_n`, which is the honest reading of what was
measured. `route_coverage` is `route_n / route_linked`, and it is the field that falls
below 1.0 the moment a question drops out. It carries a **target and no floor**: coverage
measures the host rather than the system, and a build that goes red because a model did not
answer inside 120 s is a build somebody switches off. Instead the gate prints a `NOTE`
line, `/evals/latest` returns a `coverage` block, and the panel draws a warning above the
score naming the question that vanished.

A result recorded before the harness kept both numbers reports `known: false` — it is
silent about coverage, not evidence of a complete run, and the two must not render alike.
**The run in this section is one of those results**, which is why the live endpoint shows
`coverage.known: false` against it rather than reconstructing an 11 it never stored.

### 7.2 The neighbours tool and its fixture no longer measure the same thing

Three questions — **A-22, A-23, A-25** — are graded down by a disagreement that is not a
model failure at all.

All four spatial questions carry ground truth built on **`ST_Touches`**:

```sql
JOIN communities b ON a.id <> b.id AND ST_Touches(a.geom, b.geom)
```

The tool's default predicate is **`ST_Intersects`**. Of 614 adjacent community pairs, 483
touch and 131 overlap; the 131 are digitisation slivers, and Marsa Dubai is in that set four
times with its largest overlap at 1.08 m² against a polygon of roughly 9 km². Under the
strict predicate the tool answered *"Dubai Marina borders no other community"* — a complete,
confident, false sentence.

So the tool returns a **superset** of what the fixture asserts, and set grading scores the
extras as wrong: A-23 named `AL MERKADH`, A-25 named `JUMEIRA SECOND`. Both are real
neighbours.

**The fixture was not updated to match.** Editing ground truth so that the code under test
passes is the failure mode this whole harness exists to prevent, and it does not stop being
that because the code change had a good argument. What is required is a decision, made
explicitly and written into the fixture with its reasoning: either `intersects` is the right
definition of *borders* and all four queries change, or the tool's default is wrong.

The predicate change is also in the working tree rather than merged, so this score describes
the tree.
