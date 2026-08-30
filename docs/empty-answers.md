# M-47 — the run that gathers everything and says nothing

> **Status: DIAGNOSED AND GUARDED, UNCOMMITTED, NOT YET WIRED. 2026-08-30.**
> The classification, the census and migration `0004` exist and are tested — 6 files,
> 29 tests. **Nothing calls `assess()` yet**: the repair belongs in
> `api/services/agent/executor.py`, which is m15's file. §5 prints the four lines.
> Migration `0004` was applied, verified and reversed; the database is back at `0003`.

---

## 1. The open question, and why it stood for three milestones

`SESSION-HANDOFF.md` has carried this since m16:

> *2-3 runs per pass return an empty body with `outcome='answered'` (M-47), always the
> longest. **Is it a max-token truncation, a final-turn parse failure, or the provider
> returning an empty message? Nothing here distinguishes them.***

Plan §12.4 escalated it: hide the machinery, and the one defect the project already knows
about becomes a completely blank screen after 66 seconds, on the longest and most expensive
runs. It is the worst bug on the page.

**Something did distinguish them, and it was being thrown away.** `finish_reason` arrives on
every provider response. It is carried as `LLMResponse.stop_reason`, copied onto
`AgentStep.stop_reason` for the HTTP response, and persisted nowhere — `llm_calls` has no
column for it and neither does `agent_runs`. It lived in memory for the length of one
request. That is the whole reason the question survived three milestones: the discriminator
was computed on every single run and never written down.

---

## 2. What it actually is: two causes, not one

Measured on 2026-08-30 by wrapping the provider and replaying both populations against the
running stack.

**Group A — the model ran out of room while thinking.**

```
turn 1: content=0  reasoning=1403  out= 332  finish='tool_calls'  tools=['dataset_overview']
turn 2: content=0  reasoning=3329  out= 817  finish='tool_calls'  tools=['list_areas']
turn 3: content=0  reasoning=4654  out=1200  finish='length'      tools=[]
        -> outcome='answered', answer=None
```

The entire 1,200-token per-turn budget was spent in the **reasoning** channel. The model
never emitted a single content token. `finish_reason='length'` says so unambiguously.

**Group B — the model stopped and said nothing.**

```
turn 5: content=0  reasoning=0  out=14  finish='stop'  tools=[]
        -> outcome='answered', answer=None
```

Fourteen tokens, no reasoning, no content, no tool call, and a normal stop.

**Neither is a parse failure.** In both cases there was nothing to parse. The third
hypothesis is simply absent from this data.

### 2.1 Why `content` is empty on every turn

gpt-oss puts chain-of-thought in a separate `reasoning` field, and `local_provider._unpack`
deliberately does not concatenate it into `text`:

> *"a reasoning trace prepended to a JSON body is the single most common cause of a
> 'constrained decoding produced invalid JSON' report that is not actually that."*

That is correct for `complete_structured`, where the body must parse as JSON. It is applied
unchanged to `complete_with_tools`, where there is no JSON to protect — so a turn that
produced 4,906 characters of reasoning and no content is indistinguishable, downstream, from
a turn that produced nothing at all. The Anthropic provider's `_text_of` filters
`ThinkingBlock`s for the same reason, so this is a property of the interface rather than of
one backend.

**This document does not propose pasting reasoning into the answer.** The reasoning channel
is a draft: it has not been through `executor.verify_numbers`, and publishing it would ship
unverified figures under the same field name as verified ones. `FinalTurn` therefore carries
the *length* of the reasoning and never the reasoning itself — the length is evidence about
what happened, the content is not evidence about Dubai.

---

## 3. The census, and the denominator

`services/synthesis/census.py` counts the population from `agent_runs` joined to each run's
last `llm_calls` row. It is deliberately runnable on data recorded long before any of this
existed.

**Historically — the figure to quote (M-68):**

| | |
|---|---|
| answered runs | 147 |
| blank | **8 — 5.4%** |
| truncated (`out == 1200`) | 4 |
| stopped (`out` ∈ {13, 13, 13, 20}) | 4 |

Blank runs as a share of **answered** runs, not of all runs. The naive 10-of-213 figure
(4.7%) sweeps in a `max_steps` run and a `failed` run that are blank for honest reasons; the
correct denominator makes the bug bigger.

**As the table stands now: 11 of 150 = 7.3%, 6 truncated and 5 stopped — and three of those
eleven are mine.** Reproducing the bug three times to diagnose it added three blank runs.
The increase is not a regression, and a census that did not say so would be reporting my own
experiment as a trend.

The split is **inferred** for every row on disk: `finish_reason` is not stored, so the only
surviving signal is the last turn's `output_tokens`. It is a sound inference on this data —
truncated runs sit at *exactly* 1,200 and stopped runs at 13–20, with no boundary case
anywhere near the middle — and it is still an inference, which `Census.caveat` says in
words. `stop_reason_is_persisted()` checks for the column at query time, so the census stops
inferring the moment `0004` is applied, without a code change. Same move
`observability.queries` makes for `agent_tool_calls`, and for the same reason.

**And this is why it is the worst bug rather than a curiosity.** Every blank run made at
least two steps and at least two successful tool calls. These are not runs that gave up
early; they are the ones that did all the work.

---

## 4. Five rules

1. **A run with no answer is not an answered run — and the fix is to GIVE it an answer, not
   to relabel the outcome.** A fifth `agent_runs` outcome would move these rows out of
   `answered`, and `observability.queries` counts `answered_empty` precisely to watch this
   population. Relabelling would zero that metric by moving the rows rather than by fixing
   the bug. `Verdict` has no `outcome` field, and a test asserts it.
2. **The discriminator must be persisted.** Migration `0004`.
3. **A retry only helps where the input changes.** Plan §12.4 offers "retry the final
   synthesis turn". Temperature is 0: re-issuing the same call with an unchanged context
   returns the identical empty message and spends another 30 seconds arriving back where it
   started. `retry_would_help()` returns `False` for group B and `True` for a truncation —
   because raising the cap makes it a *different* call, not a second attempt at the same
   one.
4. **The salvage message reports the evidence and never draws the conclusion.** A function
   that read four `area_price_history` payloads and wrote *"Al Wasl grew fastest"* would be
   inventing an answer the model never gave — indistinguishable, in the response, from a
   real one, and worse than a blank. The structural guarantee is that the payloads never
   arrive: `Finding` carries a tool name, a category and `ok`, and nothing a conclusion
   could be drawn from.
5. **The two causes get different words**, because they tell an operator to do different
   things.

### 4.1 The obvious fix was tried, and it is not free

Group A is a budget problem, so the obvious repair is a bigger budget. Replaying the same
question at `AGENT_MAX_OUTPUT_TOKENS=3000`:

```
turn 1: out= 332  finish='tool_calls'   (identical to the 1200 run — temperature 0)
turn 2: out= 817  finish='tool_calls'   (identical)
turn 3: Ollama did not respond within 120s
        -> outcome='failed', partial findings returned
```

**Raising the cap on this stack trades a blank answer for a provider timeout.** The
executor handles that honestly — two successful steps are returned as partial findings
rather than discarded — but the question still goes unanswered. The experiment is
inconclusive about whether more room would eventually produce an answer, and conclusive that
3,000 is not the number. So the `remedy` text names both levers and commits to neither, and
a test asserts that it says what the attempt cost.

*(Latency caveat, per the standing rule: the reproduction runs took 85 s, 102 s and 146 s
against a historical 53–66 s for the same questions. The host was running the test suite and
psql concurrently. These are not comparable timings and are not offered as any.)*

---

## 5. What is missing, and it is four lines

`api/services/agent/executor.py` currently ends the loop like this:

```python
        if not response.wants_tools:
            steps.append(record)
            answer_text = response.text or None      # <- the blank answer is born here
            outcome = "answered"
            break
```

The repair:

```python
        if not response.wants_tools:
            steps.append(record)
            verdict = assess(
                FinalTurn(
                    text=response.text,
                    output_tokens=response.usage.output_tokens,
                    max_output_tokens=settings.AGENT_MAX_OUTPUT_TOKENS,
                    stop_reason=response.stop_reason,
                    reasoning_chars=len((response.raw or {}).get("reasoning") or ""),
                ),
                findings=[Finding(i.tool, i.category, i.ok) for i in all_invocations],
            )
            answer_text = verdict.answer
            outcome = "answered"
            break
```

and `_finalise` gains `response.stop_reason` to fill the column `0004` adds.

`executor.py` is m15's file. Everything the repair needs is in `services/synthesis/` and is
tested there, so the blocked edit contains no decision.

**Also blocked, and deliberately not worked around:**

| what | needs | claimed by |
|---|---|---|
| calling `assess()` at all | `api/services/agent/executor.py` | m15 |
| storing `stop_reason` on the run | `executor._finalise` | m15 |
| surfacing the diagnosis in the UI | `frontend/src/app/copilot/` | m18 (directory-staged) |
| the release note | `docs/changelog.md` | m15 |

There is no deferred changelog block. m22 is unwired, so there is no version to write.

---

## 6. For whoever finishes this

1. **Wire `assess()` first, then re-run the census.** The number to move is 8 of 147; the
   number to expect afterwards is zero, because `answer` is never null again. If
   `observability`'s `answered_empty` does not fall to zero, the wiring is wrong.
2. **Do not add a fifth outcome.** §4 rule 1.
3. **Do not paste the reasoning channel into `answer`.** §2.1. It has not been through the
   number verification, and it would ship unverified figures in the field the UI trusts.
4. **The budget question is still open.** §4.1 rules out 3,000 on this host and rules out
   nothing else. The most promising untried lever is a *different* cap for the synthesis
   turn than for the tool-selection turns, which `settings.py` does not currently express.
5. **Group B may not be fixable from this side at all.** Fourteen tokens, nothing anywhere,
   a clean stop, deterministic across four occurrences on three distinct questions — all of
   them multi-hop spatial+SQL. It may be a property of the model at this context length. The
   salvage message is the floor, not the repair.
