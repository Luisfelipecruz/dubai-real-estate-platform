# Agent orchestration

`POST /agent/query` answers a question by planning over nine tools, and reports every step
it took: which tool, with what arguments, what came back, how long it took and what it
cost.

It exists for questions the other two copilot endpoints cannot reach at all. *"Of the
areas bordering Business Bay, which has the highest transaction volume?"* is a spatial
predicate joined to an aggregate. It is in no document at any `k` in any retrieval mode,
so `/search` and `/ask` are structurally incapable of answering it — it has to be
computed.

    GET  /search        which passages match this query
    POST /ask           what the documents say, with citations that were checked
    POST /agent/query   work it out, using whichever tools are needed

---

## 1. Why this milestone exists: the injection that verification could not catch

m14 pushed three prompt injections through `POST /notes`, a public write endpoint. Two
were instruction-style attacks and both were ignored. The third simply wrote a **false
fact** as ordinary prose — a sentence about transaction volume — and it **succeeded
completely**: high confidence, one citation, chunk resolved, quote verified, every
grounding check green.

That is not a bug in the checks. Citation verification proves an answer is *faithful to
the corpus*; it says nothing about whether the corpus is *true*, and nothing at that layer
ever can.

The mitigation is upstream. "How many transactions were recorded in Business Bay" is a
`COUNT(*)` over an indexed column — exact, fast, and already served by
`GET /areas/{name}/summary`. It should never have reached a 384-dimensional vector index
in the first place. **Routing is the fix, and `eval/golden/routing.yaml` is how the fix
gets measured rather than asserted.**

---

## 2. Nine tools, not thirty-three

The platform serves 38 REST operations. Exposing all of them would be wrong twice: every
tool description is input tokens on *every* turn of *every* run, and a model choosing
between thirty-three near-identical options chooses badly.

| Tool | Category | What it is for |
|---|---|---|
| `resolve_area_name` | meta | Turn a name a person would use into the name the data contains |
| `area_summary` | sql | Exact counts and averages for **one or more** areas |
| `area_price_history` | sql | Year-by-year medians for one area |
| `list_areas` | sql | Rank areas by activity |
| `area_neighbors` | geo | PostGIS adjacency, keyed by name |
| `ask_documents` | rag | Grounded answer with checked citations — `/ask`, as a tool |
| `search_documents` | rag | Raw passages, no synthesis |
| `corpus_stats` | meta | Size of the search index |
| `dataset_overview` | meta | Row counts, date range, and **what this data does not have** |

**Routing is enforced in the descriptions, not the system prompt.** The sentence *"prefer
this over retrieved text for any number"* sits on the tools that produce numbers, which is
the moment the model is deciding. A system prompt that describes all nine at once is read
before the question is understood.

`dataset_overview` earns its place by making refusals *specific*. It returns an explicit
`fields_not_available` list — no agency or broker column, no buyer identity, no asking
price, no forecasts — so the agent can say what is missing instead of just declining.

---

## 3. What the eval measured

14 questions, graded on **route** rather than prose: which tools must be called, which
tools are a failure even if the answer reads correctly, and whether the run answered or
refused. The fixture was written and committed **before `api/services/agent/` contained a
single line**.

| Run | Result | Warnings | Wall clock | Host load | What changed |
|---|---|---|---|---|---|
| 1 | **9/14** | 2/14 | 86 s | 22.2 | first run, no changes |
| 2 | **14/14** | 2/14 | 87 s | 5.03 | the four fixes below |
| 3 | 14/14 | 1/14 | 144 s | 7.80 | years no longer flagged as unverified numbers |
| 4 | 14/14 | 1/14 | 233 s | 10.5 | hard-coded figures removed from the system prompt |
| 5 | 14/14 | **0/14** | 240 s | 20.1 | per-property rent; space as a thousands separator |

Passing by route at 14/14: `sql` 3/3, `rag` 4/4, `geo` 1/1, `multi` 3/3, `refuse` 3/3.

Runs 4 and 5 ran while an unrelated `create-next-app` build saturated the machine — load
peaked above 100 — so **their wall clocks are contaminated and only runs 2 and 3 should be
compared.** That is the same discipline m14's M-21 established, applied to its own data.

**R-01, the injection question, routes to `sql` and never touches the corpus.** That is
the mitigation working, and it is the one result this milestone was for.

### What run 1 actually found

Five failures, and **only one of them was the agent's fault**.

**Three "failures" were a bug in the grader.** R-12, R-13 and R-14 all scored 0, and the
agent had been right every time — it declined the 2027 forecast, declined the agency
question, and declined a direct prompt injection. The refusal *detector* was wrong:
`gpt-oss` writes `I can’t` with a **typographic apostrophe** (U+2019) and the marker list
used an ASCII one, so no refusal ever matched. The abstention rate — a number this project
claims — was silently pinned at zero.

**One failure was a naming mismatch.** The fixture, written before the code, expected a
tool called `community_neighbors`; the tool that got built is `area_neighbors`. Same
query, same category. The fixture was corrected and the correction is recorded in its own
header.

**One failure was real, and it took two fixes.** R-10 asked which communities border Palm
Jumeirah:

1. The boundary polygon for Palm Jumeirah is filed as **`NAKHLAT JUMEIRA`** — *nakhlat* is
   Arabic for palm, and the KML was transliterated rather than translated. Name resolution
   built for the *transaction* tables does not help, because the polygon table has its own
   vocabulary. Fuzzy matching does not rescue it either: `palm jumeirah` and
   `nakhlat jumeira` share no token, so the correct answer scores below several wrong
   ones. The tool now returns the closest polygon names instead of a flat failure.
2. Given those candidates the agent **recovered on its own**, called the tool again with
   the right name, succeeded — and still reported that no polygon existed. Palm Jumeirah is
   an artificial island: it borders nothing, so the successful result was an empty list,
   and **an empty list read as a failure**. Zero now says in words that it is an answer.

The second one is the more general lesson. A tool result has to describe its own shape,
because whatever reads it cannot see the query that produced it. It is the same reasoning
as the truncation marker.

---

## 4. What running it changed

### 4.1 A tool that must be called N times is N−1 avoidable round trips

The first `area_summary` took one `area_name`. On the gate question the model called it
**once per neighbour** — four separate turns, each a full round trip at 7–21 s. The run
reached step 6 and died.

`area_summary` now takes a list. The same question is three turns instead of six. This is
the "collapse operations that differ only by a parameter" rule applied to the parameter
itself, and on a local model a round trip is the dominant cost of the entire system.

### 4.2 A local 20B emits invalid tool calls, and the provider returns 500

Deterministically, at temperature 0, five tool calls deep, `gpt-oss:20b` emitted a
structurally invalid tool call — Ollama's error was
`error parsing tool call: raw='{"area_…"}', err=invalid character '}' after object key`,
a JSON key with no value — and answered **HTTP 500**.

Five correct steps had already run: the area resolved, the neighbours computed via PostGIS,
three of four transaction counts retrieved. The first version of the loop re-raised and
threw all of it away.

**A provider failure mid-run no longer discards the run.** It returns the completed steps
labelled `failed`, with a warning naming the step that broke. Same judgement m14 made when
`GenerationFailed` started carrying its retrieved contexts. If *nothing* has succeeded
yet, the error is still raised — a 200 with an empty answer would make an outage look like
a hard question.

### 4.3 The model invented a currency

The very first probe of tool calling, before any of this layer was written, returned three
AED medians. The model formatted them as a table headed **"Median sale price per m² (USD)"**
with `$` on every figure.

No arithmetic was wrong. Every number was real. Only the unit was invented — which makes
each of them wrong by a factor of about 3.67, and it is the most dangerous kind of fluent
mistake, because it survives every other check. The numbers verify, the citations resolve,
the arithmetic holds; only the label is false.

Every tool that returns money now returns `"currency": "AED"` beside it, and
`verify_currency` flags any currency in the answer that appears in no tool result.

### 4.4 The numeric guard, in the form §4.4 originally asked for

m14 could only check a number against the retrieved *text*, because there were no tools to
check it against. Now a number in the answer is checked against **the raw result of the
tool that produced it**.

It warns rather than fails, because arithmetic is legitimate: a model reporting a 19%
year-on-year rise from two medians the tool *did* return has produced a number that appears
nowhere and has done nothing wrong. The count goes into `agent_runs.unverified_numbers`,
where a rise in it is visible.

**The question is part of the haystack.** Run 1 flagged `2027` in the answer to *"what will
prices be in 2027?"* — the model was quoting the question back while refusing to answer it.
m14 learned the same lesson from chunk ids: a number the model read in the prompt is not a
fabrication.

### 4.5 The guard caught the prompt

The last remaining warning was `2026`, in *"as of the latest data in February 2026"*. The
model got that from the **system prompt**, where the first draft had hard-coded
`200,001 transactions`, `358,008 rent contracts` and that date.

In a system whose entire thesis is *numbers come from tools*, baking figures into the
prompt is the exact failure the tool descriptions warn about — a figure that was true when
someone wrote it. They are gone; the prompt points at `dataset_overview` instead. Warnings
went 1/14 → 0/14.

### 4.6 The route was right and the answer was 4.6× wrong

The single most important result in this milestone, and it is a failure.

`R-05` asks what a typical Dubai Marina apartment rents for. The agent routed it
**perfectly** — resolved `Dubai Marina` to `Marsa Dubai`, called the SQL tool, never
touched the corpus — and answered **AED 550,010**. The true per-property median is
**AED 120,000**. It was wrong by 4.6×, and the routing eval **passed it**, correctly,
because that eval grades the route and this was the right route.

The cause is a trap this repository has already documented twice — changelog v0.5.0, and
G-02 in the retrieval golden set. `annual_amount` is the **contract** total, and one
contract can cover hundreds of properties; in this very area, up to **232** of them, each
getting a row carrying the full portfolio amount. `AVG(annual_amount)` is therefore not a
rent. `area_summary` exposed it to the agent under the name `avg_annual_rent`, and the
agent — reasonably — quoted it.

**A number documented as dangerous in two places still reached an answer.** That is not a
documentation problem. The division now lives in the query
(`typical_annual_rent_per_property`), and the raw mean is renamed
`avg_contract_annual_amount` — a name that says what the column actually is.

It is kept in this write-up rather than quietly fixed because it is the cleanest available
demonstration of what this eval does *not* measure, and therefore of what m16 is for.

---

## 5. `Dubai Marina` does not exist

The single most likely question this platform will ever be asked is about Dubai Marina.
There is no such area in the DLD data — it is filed as **`Marsa Dubai`**, and it is the
largest area in the dataset at 16,379 transactions. Before m15 the honest answer to *"how
many transactions in Dubai Marina"* was a confident **zero** with an HTTP 200, which is
indistinguishable from a real area with no activity.

`resolve_area_name` tries three strategies **in this order**, and the order is the finding:

| Strategy | How | Example |
|---|---|---|
| `exact` | normalised name match | `business bay` → `Business Bay` |
| `project_alias` | dominant area for a `master_project_en` | `Dubai Marina` → `Marsa Dubai` |
| `fuzzy` | token overlap blended with character similarity | `Bussiness Bay` → `Business Bay` (0.58) |

**Fuzzy is last because it is measurably poor at the case that matters.** Scored against
all 221 area names, `Dubai Marina` ranks the correct answer `Marsa Dubai` first at **0.37**
— and second is `Madinat Dubai Almelaheyah` at **0.34**. The right answer wins by 0.03, on
the strength of sharing the word "Dubai", which a third of the emirate also contains. Any
threshold that accepts it also accepts the wrong one. `Downtown Dubai` is worse: fuzzy
ranks `Marsa Dubai` first, which is simply wrong.

The alias table is **derived, not hand-written**. Every transaction carries
`master_project_en` beside `area_name_en`, so the mapping is a `GROUP BY`: the area where a
master project's transactions actually sit. A hand-maintained constant would encode one
developer's knowledge of Dubai geography as fact and go stale on the first rename. This
encodes the data's own answer.

Below `FUZZY_FLOOR = 0.55` nothing is accepted and the candidates are returned instead. A
tool that guesses an area name produces a confident answer about the wrong place, and
nothing downstream can detect it.

---

## 6. The loop

    resolve budget → turn → record → execute tools → recover → repeat → verify

**Hand-written, not `client.beta.messages.tool_runner()`,** which `IMPLEMENTATION-PLAN.md`
§5.2 specifies. The runner exists only on the Anthropic SDK. The local provider — the
default, and the only one with a key on this machine — has no equivalent, so taking it
would mean the two providers ran *different loops*: different step accounting, different
caps, different recovery. m16's whole job is to compare those two providers on one golden
set, and a comparison across two orchestrations measures the orchestrations.

Instead the provider interface **grew a third method**. `base.py` said an interface is
better grown than lied to, and set the condition: `stream()` was left out because it had no
implementation. `complete_with_tools` has two on the day it is declared.

### Recovery

| Failure | Detection | Recovery |
|---|---|---|
| Tool raises | exception in handler | `tool_result` with `is_error: true` and a message written *for the model*. Never dropped — a `tool_use` with no result is a malformed request that fails the whole turn |
| Unknown area | resolution miss | closest existing names returned as candidates |
| Empty result | zero rows | says **in words** that the query succeeded and the answer is none |
| Oversized result | char count | truncated with a marker saying it is incomplete |
| Repeated call | `(tool, args)` seen before | **not executed again**; the cached result is returned with a note |
| Provider fails | `LLMError` mid-run | completed steps returned, labelled `failed` |
| Non-termination | step counter | hard cap; partial findings labelled `max_steps` |

**The repeat guard is the structural half of "abstention has to survive orchestration".** A
prompt can *ask* a model not to retry a refusal until it gets a different answer. Only the
executor can guarantee it. It also terminates the commonest non-termination mode, which is
not an infinite loop but a two-step cycle.

### Accounting

One `agent_runs` row per run, one `llm_calls` row per **turn**, linked by `agent_run_id`.
Written per turn rather than at the end: a run that dies on step six has already committed
five rows, and those are the rows worth reading.

The run cost ceiling is read back **from the rows**, not from a counter in memory. A
counter and a table are two accounts that can disagree, and the one that gets audited is
the table. On the local provider every row prices at `$0.00` and the ceiling never binds —
which is exactly why it is exercised there, rather than first discovered on a hosted run.

This also closed an accounting hole that would have opened the moment the agent shipped.
`ask_documents` calls the same `services.ask.answer` that `POST /ask` calls, so without
`endpoint` and `agent_run_id` on the row, `GET /ask/costs` would have silently started
reporting the agent's traffic as its own. The **abstention rate** would have been corrupted
worst: the agent asks sub-questions that are *meant* to be refused.

---

## 7. Latency

Run 2 took **87 s** for 14 questions. Run 3, on identical code, took **144 s**. Host load
average was 5.03 before run 2 and 7.80 before run 3.

That 1.7× spread on unchanged code is the same finding as m14's M-21, and it is why every
latency number in this project is quoted with the host load beside it. Runs 4 and 5 took
233 s and 240 s while an unrelated build saturated the machine (load above 100), which is
a 2.8× spread on the same code — those two are recorded but not compared.

Per-question times in run 4 ranged from 1.3 s (a refusal: one turn, no tools) to 36 s (a
documentation question, which nests a full `/ask` call inside a tool call).

`timings_ms` splits `generate` from `tools` so the two are never confused. Tool time is
milliseconds — a `COUNT(*)` on an indexed column, a PostGIS self-join over 222 polygons.
**Essentially all of the wall clock is the model.**

The consequence for m17 is unchanged and now firmer: a multi-step agent cannot be in an
800 ms voice path on this hardware.

---

## 8. Known warts, stated rather than fixed

- **`area_summary` reports means; `area_price_history` reports medians.** That
  inconsistency predates m15. Changing what `GET /areas/{name}/summary` returns is an API
  change, not a refactor, and a refactor that quietly alters a number is the worst kind.
  The tool's `note` field warns the model to prefer the history tool for a typical price.
- **The Anthropic tool path has never run.** There is no `ANTHROPIC_API_KEY` on this
  machine. `complete_with_tools` is asserted against a scripted client and nothing about it
  has been observed against Anthropic's servers — the same caveat m14 recorded, unchanged.
  m16 is where it gets exercised.
- **`_reads_as_refusal` is a heuristic over prose** and is labelled one. The honest
  alternative — a second structured call asking "was that a refusal?" — costs another
  7–21 s per run to classify text the caller can read, and would be a model judging a
  model. `outcome` is reported next to the full answer and every step, so a
  misclassification is visible rather than load-bearing.
- **n=14, hand-written, by the author of the tools.** It detects a regression and
  demonstrates a mechanism. It does not establish a routing accuracy rate, and
  `run_routing_eval.py` prints that caveat on every run so the number cannot be lifted out
  of context later.
