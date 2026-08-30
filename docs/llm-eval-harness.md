# The evaluation harness — grading a number, and what happened when it ran

> **A note on how this document is written.** Evaluation questions are referred to by
> **id** and never quoted. This file is inside the retrieval corpus it describes, and
> m13a's most expensive lesson was that a document containing the eval questions gets
> retrieved *for* those questions and poisons the measurement. Writing up a retrieval
> result is one of the ways to destroy it. One finding below could not be stated in full
> for exactly that reason, and the omission is marked where it occurs.

---

## 1. Why this milestone exists

m15 asked `POST /agent/query` what a typical Dubai Marina apartment rents for. It resolved
the name, called SQL, never touched the corpus, and answered **AED 550,010**. The true
per-property median is **AED 120,000**.

`eval/golden/routing.yaml` **passed** that question, and it was right to. It grades the
*route* — which tools were called, which were forbidden — and the route was perfect. Route
grading cannot see a value, by construction.

So the centre of this milestone is answer grading, and the first job was working out what a
rubric for a *numeric* answer even is. The retrieval fixture grades documents, which is a
solved shape: a fixed set of source ids, a 0–3 scale, rank metrics on top. Grading a
quantity is not that.

---

## 2. What a rubric for a numeric answer is

Four things, and the fourth had to be earned.

### 2.1 The expected value is a **query**, not a number

Every question in `eval/golden/answers.yaml` carries `ground_truth_sql`, hand-written
against the raw tables, and the harness runs it at grade time.

A literal goes stale — these are properties of 561,115 rows, a reload moves them, the
fixture fails for the wrong reason, and the standard repair is to re-baseline it to
whatever the system currently says. That is the m13a G-03 mistake wearing a new hat.

And a literal is **circular** if it ever came from the code under test. The whole claim of
the routing work is that SQL is exact. An eval whose expected value was produced by calling
`area_summary` proves only that `area_summary` agrees with itself. So these queries do not
import `api/services/market.py`; they hit `raw_transactions`, `raw_rent_contracts`,
`raw_valuations` and `communities` directly. Where the two disagree, the disagreement is
the result.

`recorded_value` travels beside each query as a **dated reading**, and the harness reports
drift between the two without ever failing on it. A data reload is not a regression.

### 2.2 A tolerance, chosen by the question

`exact` for counts — off by one is wrong. `rel:0.01` for money and medians. `abs:` for
ratios, where a relative tolerance near zero is meaningless.

The drift check does **not** use the question's tolerance, and the distinction matters: a
rent median that moves 0.8% is still the right answer, but drift at 1% would hide a reload
that shifted every median in the file. Drift is compared at `rel:1e-9` — tight enough to
catch a real move, loose enough for the fact that `PERCENTILE_CONT` over a division returns
`double precision`, so one value comes back as `166765.08000000002`.

### 2.3 A unit

Because the model invented one. Given three AED medians in m15 it produced a table headed
**USD** with `$` on every figure: every number real, the arithmetic sound, only the label
false — an error that survives every other check because nothing else looks at the label.

Absence of a unit is not a failure; naming a *different* one is.

### 2.4 A decoy, and it is a query too

This is the new idea, and it is R-05 turned into a field.

"Wrong" is a poor verdict when the useful question is *how* wrong. A figure 0.3% out is a
reload. A figure that is exactly `AVG(annual_amount)` where the truth is a per-property
median is the v0.5.0 / G-02 trap re-entering through a new tool under a friendly name — a
regression with a name, and the harness should print the name.

Nobody recognised AED 550,010 by eye the first time. It took a grounding warning, a
hand-written percentile query and an afternoon. A named decoy makes that recognition free.

```
A-14   decoyed   answered 550,010 — the known decoy 'contract_total_not_per_property'
                 (550,009.53), not the true 120,000
```

### 2.5 What is deliberately absent

**No LLM-as-judge.** §6.2 of the plan reserves a judge for narrative answers and forbids it
anywhere a deterministic check will do. A judge is a measurement instrument with its own
bias, and a bias inside a regression gate is a bias nobody sees again. Every verdict in this
harness is arithmetic or set membership.

---

## 3. Retrieval at n=20, in two cohorts

`eval/golden/retrieval.yaml` went from 10 questions to 20. The new ten were graded from the
documents before any of them was run, and they are **reported separately**.

That separation is not bookkeeping. "dense 8/10 top-1" is a published figure — it is in
M-12, in the m13a write-up, in changelog v0.7.0 and in a PR body. Reporting `16/20` after
adding ten questions would silently redefine it, because a different question set is a
different measurement and nothing establishes that the new ten are of equal difficulty.

### 3.1 The corpus this was measured on is a moving target, and it moved during the run

The ablation was run twice: once at **348 chunks**, and again at **398** after
`make index` picked up this document and m15's write-up. Nothing else changed. Host load
7.07 and 6.58; 85 s and 62 s for all four modes.

| mode | 348 chunks | 398 chunks |
|---|---|---|
| dense · m13a top-1 | 8/10 | **9/10** |
| lexical · m13a top-1 | 3/10 | **2/10** |
| hybrid+rerank · m13a top-1 | 3/10 | **2/10** |
| every m16 figure | — | unchanged |

**Adding two documents that describe this system moved the published m13a numbers in both
directions.** That is the m13a self-reference finding, measured rather than argued, and
this time it made the headline metric look *better*: dense picked up G-10, whose decoy had
outranked the answer at 348 chunks.

The lexical losses are diagnosable to the document. m15's write-up opens by stating the m15
gate question, which is **one word** from G-07 — so the isolation test does not catch it,
exactly as m13a predicted of that species — and the lexical arm went straight to it the
moment it was indexed. It also took rank 1 from G-06 and G-08.

Both are now graded `0` in the fixture as named decoys, following m13a's stated policy:
*record them, do not delete them.* The honest reading is "near-duplicate question text
still beats the answer", which is a result, not a leak to patch out of the corpus after the
fact. And grading them made the leak **visible**: the runner now prints `DECOY AT RANK 1`,
a signal that did not exist before because the previous metric only counted decoys ranked
*above a relevant result* — and when nothing relevant is retrieved at all, there is nothing
for a decoy to be above. The worst case was the invisible one.

There is no fixed point to chase here. This document is in the corpus it measures, so
publishing these numbers changes them. What is reproducible is the *procedure* and the
corpus size beside each figure.

Final table, at 398 chunks:

| mode | top-1 ideal | hit@1 | hit@5 | MRR | nDCG@5 |
|---|---|---|---|---|---|
| **dense** | **17/20** | 17/20 | **18/20** | **0.881** | 0.845 |
| dense · m13a | 9/10 | 9/10 | 9/10 | 0.900 | 0.822 |
| dense · m16 | 8/10 | 8/10 | 9/10 | 0.863 | 0.868 |
| lexical | 7/20 | 7/20 | 15/20 | 0.501 | 0.595 |
| lexical · m13a | 2/10 | 2/10 | 5/10 | 0.358 | 0.466 |
| lexical · m16 | 5/10 | 5/10 | **10/10** | 0.643 | 0.724 |
| hybrid | 15/20 | 15/20 | 18/20 | 0.823 | 0.831 |
| hybrid · m13a | 7/10 | 7/10 | 9/10 | 0.783 | 0.795 |
| hybrid · m16 | 8/10 | 8/10 | 9/10 | 0.863 | 0.868 |
| hybrid+rerank | 8/20 | 9/20 | 17/20 | 0.645 | 0.697 |
| hybrid+rerank · m13a | 2/10 | 3/10 | 7/10 | 0.489 | 0.552 |
| hybrid+rerank · m16 | 6/10 | 6/10 | 10/10 | 0.800 | 0.842 |

Five of the twenty questions have a document the fixture explicitly graded 0 sitting at
rank 1 in at least one mode.

**Dense still wins, and hybrid still does not beat it.** That is the m13a conclusion, now
at n=20 and on a corpus 31% larger. Reranking has not earned its 2.9 s in either cohort.

### 3.2 The prediction I wrote into the fixture was wrong

G-13 was built to be the hardest of the new ten. Its note, written **before** the run, says
the answer has to be found semantically because the source document never uses the
question's vocabulary — and concludes: *"this one is dense or nothing."*

The run refuted it.

| mode | G-13 |
|---|---|
| dense | **MISS** — returns the wrong document, MRR 0.125 |
| lexical | **ideal at rank 1**, MRR 1.000 |
| hybrid | **MISS** |
| hybrid+rerank | hit@5, MRR 0.500 |

The bridge is a single distinctive noun that occurs **exactly once in the entire corpus**,
in the one document that answers the question. *(The word itself is not written here. This
document is in the corpus, and naming it would create a second occurrence and destroy the
finding on the next `make index` — the m13a re-contamination trap, live.)*

Two things follow.

**The standing open question is answered.** m13a asked whether the lexical arm ever earns
its place on a query type ten prose questions do not contain — identifiers, procedure
numbers, exact strings. It does, and a rare proper noun behaves exactly like an identifier:
one occurrence, no semantic neighbours, and a `tsvector` that finds it instantly while a
384-dimension embedding does not.

**Hybrid threw the answer away.** Lexical had it at rank 1 and hybrid still missed. That is
the third demonstration, from a third direction, that **RRF has no notion of which arm to
trust** — after m13a showed that fusing a contaminated arm dropped hybrid below dense, and
that *fixing* that arm's recall dropped hybrid further.

### 3.3 What else moved

The lexical arm is materially stronger on the m16 cohort: **5/10 top-1 against 2/10, and
10/10 hit@5 against 5/10.** The new questions were written to be answerable rather than
prose-like, and several name a document's subject in the words that document uses.

Reranking still loses, but by less on the newer questions: 6/10 against dense's 8/10 on the
m16 cohort, versus 2/10 against 9/10 on m13a. It has not earned 2.9 s per query in either.

G-03 misses in every mode, as it did in m13a. It remains one of the two questions with no
retrievable answer at any *k*, and a chunking change that makes it retrievable without
breaking the other nineteen is a measured win.

---

## 4. The agent suite: route and answer, graded on one response

`eval/golden/answers.yaml` is 40 questions — 13 counts, 8 money, 4 spatial sets, 5
multi-hop, 10 unanswerable. Nine of them are linked by id to a question in
`routing.yaml` with byte-identical text, and `--suite agent` issues **one** request per
question and applies **both** graders to it.

That join is the milestone. "The route was right and the answer was wrong" is a claim about
a single response, and a local 20B does not answer the same question the same way twice.
Two scripts issuing two requests can only report two rates that happen to disagree.

### 4.1 Two full runs

| | run 1, as graded | run 1, regraded | run 2 | run 3 (`make eval`) |
|---|---|---|---|---|
| answers | 25/40 | **30/40** | **31/40** | **31/40** |
| routes (of 9 linked) | 9/9 | 9/9 | **8/9** | **8/9** |
| correct | 17 | 22 | 22 | 22 |
| abstained | 8 | 8 | 9 | 9 |
| refused wrongly | 6 | 6 | 7 | 7 |
| empty body | — | 3 | 2 | 2 |
| wrong | 7 | 1 | 0 | 0 |
| grounding warnings | 3/40 | 3/40 | 3/40 | 3/40 |
| wall clock | 556 s | — | 520 s | 706 s |

Runs 2 and 3 are **verdict-for-verdict identical**, down to which two questions returned an
empty body. Run 3 was `make eval` — the documented entry point, all three suites and the
gate — and it exited 0 with all eight floors passing. The quality numbers on this stack are
stable; the wall clock is not, and moved 520 s to 706 s on identical code.

Host load 4.61 at the start of run 1 and 12.30 at the start of run 2, with the model's own
`llama-server` the top consumer throughout at ~240% CPU. Per-question range 1.4 s to 58.6 s.
Same discipline as M-21 and M-35: a latency number from this stack means nothing without the
load beside it.

### 4.2 Seven of run 1's fifteen failures were the grader

The regrade column above is the same responses scored by fixed graders — no new model calls.
That column exists because it was needed twice in one afternoon, and doing it by hand makes
the attribution impossible: if the responses also change, "we fixed the grader and the score
went up" is unreadable.

| verdict change | count | what it was |
|---|---|---|
| `wrong` → `correct` | 4 | every spatial answer was right and the matcher could not see it |
| `wrong` → `correct` | 1 | a superlative question graded on the wrong property |
| `wrong`/`over_answered` → `empty` | 3 | a real defect, previously mislabelled |

**All six spatial questions failed while the agent was right every time.** The model writes
place names with U+202F between the words and U+2019 for the apostrophe; the community table
stores ASCII. A literal substring test between those two strings is false, so the harness
reported "never named [...]" for four perfectly listed neighbours.

That is the **fourth** time this project has been defeated by a character it did not expect:

1. m15's refusal detector matched `I can't` with an ASCII apostrophe while the model writes
   U+2019 — three correct refusals scored zero and the abstention rate sat silently at zero.
2. m15's numeric guard split a figure written with a space as a thousands separator.
3. m16's number extractor, first run — U+202F, again as a thousands separator. The answer
   was correct and the harness printed `saw [120, 0]`.
4. m16's name matcher, first full run — U+202F and U+2019 inside proper nouns.

Four incidents, two characters, three separate detectors, and **in every case the system was
right and the measurement was wrong.** Normalisation is now one function that every
comparison in `services/evaluation/` calls first, and the rule is written where the next
detector will read it: *normalise before you parse, and build the character class from
observed output rather than from what sounds right.*

The other grader bug is subtler. A superlative question — "of these, which is the highest?" —
was answered correctly and then shown its working: the right name first, followed by the
other candidates with their counts. Set grading scored that `partial` for naming areas that
are not the maximum. Those areas *do* border the subject; they are simply not the answer.
Requiring an answer to mention nothing else measured verbosity. Those questions now grade
what the answer **leads with**, which is the same containment-versus-assertion distinction
the numeric grader already draws.

### 4.3 Three real defects, none of them fixed here

**Six questions were declined that the data can answer.** The agent said so plainly: *"I
don't have a tool that can return..."*. It is right. All nine tools are area-scoped, and
there is no dataset-wide aggregate beyond `dataset_overview` — so a question about the whole
dataset has nowhere to go. The routing eval could not find this, because every routing
question names an area.

This is a **tool-layer coverage gap**, and m16 records it rather than fixing it: the fix
belongs with the tool layer, and an eval milestone that quietly edits the system it is
measuring has stopped being an eval. Six of the forty, and the largest single block of
failures.

**Two to three questions per run come back with an empty body and `outcome: "answered"`.**
Always the longest runs — 29 s to 63 s. m15's executor docstring states the principle this
breaks: *"a 200 with an empty answer would make an outage look like a hard question."* It
now has its own verdict, `empty`, so a system fault is never counted inside a quality metric.

**Routing is not deterministic at temperature 0.** A-14 routed cleanly in run 1 and reached
for `search_documents` in run 2, on identical code, on a question whose fixture forbids the
corpus. Routes went 9/9 and 8/9.

That has a consequence for how m15's headline should be read. Routing is the mitigation for
the m14 injection finding, and this says the mitigation is **probabilistic**. It is worth
having and it is not a guarantee. `eval/thresholds.yaml` now separates the two: the
injection question itself is gated as a property at 1.0, and overall route accuracy is gated
as a rate below it.

### 4.4 What went right

Abstention is the strongest part. **Zero fabricated figures across 80 unanswerable
questions** — two runs of ten, including a real place with no rows in this database, another
jurisdiction, and a direct prompt injection. That is the failure this set exists to catch
and the one most projects never measure.

`A-22` passes: asked for the neighbours of an artificial island the agent resolves a
transliterated polygon name, queries it, receives an empty set, and **says so in words**
rather than reporting missing data. m15 needed two fixes to get there.

`A-14` — the R-05 question — now answers AED 120,000 in both runs, and the harness confirms
it is the truth rather than the decoy.

---

## 5. The gate

`eval/thresholds.yaml`, applied with `make eval`. Every floor carries its argument.

There is a real distinction the file is built around. Changing what counts as a right answer
so a wrong one passes is the m13a G-03 mistake, and widening a tolerance until a decoyed
answer fits is the same move. Placing a floor **below** current behaviour so the build fails
if the system gets worse is not that — it is what a regression gate is.

Two rules produce every number:

- **Properties get 1.0.** "Never fabricates a figure for a question the data cannot answer"
  is true or false, not a measurement that drifts. Three floors are properties: no
  fabrication, no answer matching a named decoy, and the injection question never reaching
  the corpus.
- **Rates get observed-minus-two-questions.** Never *at* the observed value — a gate that is
  exactly satisfied fails on noise and gets switched off within a fortnight.

Latency is reported, never gated: it moved 1.7× between two runs of identical m15 code on
host load alone, and a gate that noisy trains people to re-run until it passes.

### 5.1 What CI can actually check

`.github/workflows/eval.yml` runs the graders and the fixtures. It does **not** run any of
the three suites, and does not pretend to: a hosted runner has no 1 GB of Land Department
data, no Ollama, and no API key.

The tempting alternative — a ~2,000-row snapshot, which §6.3 of the plan proposes — was
rejected for a specific reason. Every `recorded_value` is a property of the full dataset, so
the same fixture against a sample reports forty drifts and one true value, and a check that
is red on a healthy system is a check somebody turns off. Making it green would mean
maintaining a second set of expected values for the sample: a second fixture to keep honest,
for no additional signal about the system that ships.

What CI *can* prove is that the measuring equipment is sound — and given that four of this
project's grading bugs were character-encoding failures that each moved a metric in the
flattering direction, that is not a small claim. Every one of them is now one assertion.

---

## 6. Known gaps, stated rather than fixed

- **The provider comparison still has not run.** There is no `ANTHROPIC_API_KEY` on this
  machine, so `complete_structured` (m14) and `complete_with_tools` (m15) remain asserted
  against scripted clients and unobserved against Anthropic's servers. Third milestone
  carrying this caveat.
- **Prompt caching has never been above zero.** `cache_read_input_tokens` is recorded on
  every row and the breakpoint is declared. A zero could mean "under the minimum cacheable
  length" or "silently invalidated", and those are different problems. Same blocker.
- **n=74 across three fixtures, hand-written, by the author of the code they grade.** The
  runner prints that caveat on every run. It detects a regression and demonstrates a
  mechanism; it establishes an accuracy rate for nothing.
- **The judged-answer half of §6.2 is not built.** No narrative answer is scored for
  faithfulness or completeness, because every question in `answers.yaml` has a deterministic
  verdict available and the plan forbids a judge where one does. The day a question needs
  prose graded, the judge needs its own agreement measurement against human labels first.
- **`verify_numbers` in the agent layer still normalises only ASCII spaces.** It is a
  provenance check with a lenient substring test, so the gap has not produced a false
  warning — but it is the same latent bug the grader had, in m15's file, and it is recorded
  here rather than patched across a milestone boundary.
- **The six dataset-wide questions and the empty-body defect are both agent-layer work.**
  They are the whole distance between 31/40 and the 0.90 target.
