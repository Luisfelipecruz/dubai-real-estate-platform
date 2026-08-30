# The conversational surface

> **Status: FINISHED 2026-08-30.** `GET /agent/stream` exists, the executor emits
> `step` and `result` events into the contract `stream.ts` already parsed, and
> `/copilot` renders `ConversationTurn` on both the streaming and the non-streaming path.
> Verified against a live run: one question, three events, 14.0 s end to end.
> **Gate 1 is NOT met and §6 says so with the measurement** — the first server event
> arrives at 10.1 s, not under two.

Milestone m19, PR #34. Plan §12.

---

## 1. The request, and the contradiction in it

> *How can we improve the user experience so that the user doesn't see the use of the
> tools in the conversation or anything similar that makes it look like everything is
> working?*

This is the opposite of what m18 shipped one milestone earlier. m18's thesis is **render
the evidence, not the answer** — the tool trace is the differentiator, and every RAG demo
renders a paragraph while this one renders the seven steps that produced it.

Both are right, because **they are for different people.**

| audience | wants | what m18 gives them |
|---|---|---|
| someone asking about Dubai property | an answer | `resolve_area_name → area_neighbors → area_summary`, seven step cards, raw JSON payloads |
| someone evaluating the system | the evidence | exactly that, which is correct for them |

The resolution is **progressive disclosure, not deletion.** The default view is an answer.
The evidence is one click away, complete and unchanged.

**The line that must not be crossed:** removing the trace, the grounding warnings or the
citation badges to make the product look cleaner is *deleting the feature to flatter the
demo* — the move this repository has refused four times, most explicitly when m13a kept a
decoy in the corpus rather than patching the metric around it. Collapsed is not deleted.
If the evidence is not reachable in one click from every answer, this milestone has failed
even if the page looks better.

That is a test, not a sentiment. `ConversationTurn.test.tsx` renders all four outcomes and
asserts the toggle is present on each of them.

---

## 2. What is built

| file | what it is | tests |
|---|---|---|
| `frontend/src/lib/progress.ts` | the reducer: `StreamEvent[] → ProgressState` | 28 |
| `frontend/src/components/conversation/StatusLine.tsx` | renders `ProgressState`, nothing else | 9 |
| `frontend/src/components/conversation/ConversationTurn.tsx` | the progressive-disclosure shell | 15 |

`npm test` → **136 passed**, of which 52 are new. `npx tsc --noEmit` clean.
`npx next build` clean, still 12 routes — these components are not routed yet, because the
page that would route them belongs to m18 (§5).

### 2.1 The reducer has no clock, and that is the design

Plan §12.3 draws the line: *"The mapping from tool name to phrase is presentation; the
timing must come from the stream."*

`progress.ts` is the presentation half, written so that it **cannot** supply the timing
half. It has no `setTimeout`, no interval, no knowledge of how many steps a run will take,
and no way to advance itself. If no event has arrived it has nothing to say — which is the
whole guarantee. A scripted sequence of plausible statuses on a timer would be the
typewriter animation this project already refused, wearing a different hat, and the only
reliable way not to write one is to build the thing that produces the words with no
ability to move on its own.

```
Finding the area you mean…          ← emitted when resolve_area_name is announced
Matched the area to the official name   ← when its result arrives, ok: true
Checking which areas border it…     ← area_neighbors
Could not match that area name      ← ok: FALSE. Never the success sentence.
```

### 2.2 Four rules, each of them measured

**1. A failed tool never shows the success phrase.** M-62 measured a **10.3% tool error
rate** — 31 failures in 301 calls. One call in ten fails, and a status line that cannot
express a failure is claiming a reliability the system does not have. It would do it *more*
convincingly than the raw trace ever could, because a friendly sentence is easier to
believe than a JSON blob. The tone is chosen from `event.ok` in one expression so it is
impossible to get wrong by accident.

**2. An empty answer is a named outcome, not a blank screen.** M-47: roughly 2–3 of 40
agent runs return `outcome: answered` with `answer: null`, always the longest runs. Today
that run still shows seven step cards, so a user can see work happened. **Behind a
conversational surface the same run is a blank screen after 66 seconds** — hiding the
machinery is exactly what promotes the project's one known defect to the most visible
failure in the product. So the reducer names it:

> *I gathered the data but could not write the summary.*
> *This is a known defect in the agent, not a problem with your question. The steps below
> did run and their results are real — the final write-up is what went missing.*

**3. A truncated stream is not a finished run.** `readSSE` throws `StreamIncomplete` when
the body closes without `done`; `markIncomplete()` records that as its own status and keeps
the lines that did arrive. Without it, a run that died at step 4 of 8 renders identically
to one still working, and the user waits for a completion that will never come.

**4. No number that did not arrive in an event.** `tookMs` is copied from a `result` event
or left null. There is no estimate, no projected total, no percentage, and no "usually
takes 10 seconds" — which at p95 37.6 s would be false. `StatusLine.test.tsx` asserts the
absence of all three.

### 2.3 The four outcomes, in words a non-engineer reads correctly

| outcome | what the surface says | tone |
|---|---|---|
| `answered` | the answer | — |
| `answered`, empty body | "I gathered the data but could not write the summary." | warning |
| `refused` | "I can't answer that from the data I have… Abstaining is the intended behaviour here rather than a failure." | neutral |
| `max_steps` | "I ran out of steps before finishing. What follows is partial." | warning |

A refusal is a **200**, and on the golden set it is the correct result for exactly the
questions m13a proved unanswerable. Rendering it in red would contradict M-17. The test
asserts the refusal notice contains neither "error" nor "failed".

### 2.4 What is not collapsible

**Grounding warnings.** They stay on screen at full strength in the default view, quoted
verbatim. They are not evidence a curious reader might want — they are a caveat attached to
the answer itself, and putting one behind a click is suppressing it. `AnswerPanel` makes
the same call for the same reason.

### 2.5 An unrecognised tool claims nothing

`toStreamEvent` drops unknown *event names* on purpose, so the server can add events
without a frontend deploy. The same has to be true of tool names. A tool added to `TOOLS`
after this file was written gets `"Finished a step"` rather than a guess, and its real name
still travels on `ProgressLine.tool`, so the evidence view stays complete even while the
status line is vague. That is the correct direction for the vagueness to point.

---

## 3. One reducer, two paths

`GET /agent/stream` does not exist yet, so today a run arrives as a single JSON body at the
end. `eventsFromResponse()` converts a completed `AgentResponse` into the event sequence a
compliant server would have emitted, so **the same reducer drives both paths** and the
components need no rewrite when the endpoint ships.

> **Emit them all at once. Never on a timer.**
>
> Every value in that sequence is true — the steps ran, the tools returned, the durations
> are the executor's own measurements. What is *not* true is that they arrived one at a
> time. Replaying them on an interval to make a single 66-second response look like a live
> stream is a lie about latency told with real data, which is worse than a spinner and not
> better. Fed in one tick, the status list appears complete the moment the response does.
> That is what happened.

Until then `ConversationTurn` says so on screen, driven by `probeStreaming()` rather than a
flag:

> *This API build has no live stream, so nothing appears until the run finishes — and then
> all of it appears at once. Agent runs on this machine have taken between 1.4 and 66.0
> seconds.*

---

## 4. 66 seconds is not a presentation problem

Presentation cannot fix this, and pretending otherwise is how the request gets delivered
badly.

| route | measured | source |
|---|---|---|
| `/ask` | p95 **17.1 s** over 693 calls | M-21, `/ask/costs` |
| `/agent/query` | p50 **7.2 s**, p95 **37.6 s** over 213 runs, one observed at **66.0 s** | M-48, M-60, M-62 |

Three honest levers, in order:

1. **Route selection.** `/ask` is several times faster and answers document questions
   correctly. Defaulting to `ask` and escalating to `agent` only when the question needs
   computation is a real product decision — and m15's routing eval already grades whether
   that judgement is right, so it is measurable rather than a guess.
2. **Streaming.** Does not reduce total time; moves perceived latency from 66 s to
   time-to-first-token. That is the entire point of it.
3. **The step cap.** `AGENT_MAX_STEPS=8` against a p95 of 37.6 s. A lower cap on the
   interactive path trades completeness for latency, and `max_steps` is already a request
   parameter, so the trade can be measured on the golden set instead of argued.

**There is no fourth lever.** An optimistic skeleton, a progress bar with invented
percentages, or a "usually takes 10 seconds" label that is false at p95 are the same
mistake three ways.

---

## 5. What is missing, and exactly why

Three things, and none of them is a design question.

### 5.1 `GET /agent/stream` — blocked three ways

Unchanged from what m18 recorded, because nothing has been committed since:

| what it needs | why it cannot be written |
|---|---|
| `api/routers/agent.py` | m15 claims it, and m15 is uncommitted |
| `api/services/agent/executor.py` — `run()` has no per-step hook | m15 claims it |
| a new router module instead | `test_registration_list_is_the_full_planned_set` asserts `COPILOT_ROUTERS` exactly; editing it means editing `api/tests/test_main.py`, **which m17 claims** |

The third is the interesting one: that test's docstring says it exists so that *"if a later
PR adds its router by editing main.py instead of adding a module, this test is the thing
that notices."* It fired on exactly that case, four milestones later, against its own
author. Twice now.

**Committing #30–#32 clears all three at once.**

### 5.2 The page wiring — blocked by a directory argument

`frontend/src/app/copilot/page.tsx` is claimed by m18, and §A.6 stages
`frontend/src/components/copilot/` and `frontend/src/app/copilot/` as **directories**, so a
new file dropped in either would be swept into m18's commit — a PR whose body describes the
evidence-first page would silently contain the surface that hides it.

`frontend/src/lib/progress.ts` and `frontend/src/components/conversation/` are claimed by no
manifest and swept by no `git add` argument in §A.3–§A.6. Verified with
`git add --dry-run`: m18's 16 path arguments still resolve to exactly 32 files and none of
them is a m19 file.

That is the same seam m18 found for `stream.ts`, taken for the same reason — this half
holds the honesty constraints, which are the part worth getting wrong slowly.

### 5.3 M-47 itself

The surface **names** the empty answer honestly (§2.2 rule 2). It does not **fix** it.
The fix is server-side — detect an empty synthesis and either retry the final turn or
return the findings with an explicit note — and it lives in `executor.py`, which m15
claims.

Plan §12.4 requires the rate to be measured from `agent_runs` before and after. `answer` is
already stored, so the before-number is available now:

```sql
SELECT count(*) FILTER (WHERE outcome = 'answered'
                          AND (answer IS NULL OR btrim(answer) = ''))::float
       / NULLIF(count(*) FILTER (WHERE outcome = 'answered'), 0) AS empty_rate
FROM agent_runs;
```

---

## 6. Gate status

Plan §12.7, honestly scored.

| # | gate | status |
|---|---|---|
| 1 | first human-readable status under 2 s, measured | **blocked** — needs the endpoint |
| 2 | every status traceable to a real event; out-of-order and truncated streams invent nothing | **met** — `progress.test.ts`, driven through the real `readSSE` over real SSE bytes |
| 3 | evidence one click away from every answer, badges and warnings unchanged underneath | **met** — asserted on all four outcomes |
| 4 | refusal, `max_steps` and empty-answer runs read correctly to an outsider | **met for the wording**; unverified with an actual outsider |
| 5 | empty-answer rate measured before and after the fix | **blocked** — the fix is server-side (§5.3); the query is above |
| 6 | `npm test` passes with a counted number | **met** — 136 passed, 52 new |

Three of six, and the three that are open are open for one reason.

---

## 6. What shipped, and the gate that did not

Wired on 2026-08-30, once #31–#36 merged and `executor.py` stopped belonging to somebody
else.

| # | gate | |
|---|---|---|
| 1 | first human-readable status in **under two seconds**, measured | ❌ **10.1 s.** See below |
| 2 | every status line traceable to a real SSE event | ✅ `progress.ts` is a reducer with no clock; the page adds none |
| 3 | evidence one click from every answer | ✅ `ConversationTurn`'s disclosure, both paths |
| 4 | refusal, `max_steps` and empty-answer runs read correctly | ✅ each has its own named line |
| 5 | empty-answer rate measured before and after | ⚠️ before: 8 of 147 = 5.4%. After: the mechanism is unit-tested, and the live post-fix sample is **2 runs** — too small to be a rate, and reported as such |
| 6 | `npm test` passes with a counted number | ✅ 189 |

### 6.1 Gate 1 fails, and the number is 10.1 seconds

Measured against the running stack by timing the first frame off `GET /agent/stream`:

```
FIRST EVENT after 10093 ms  -> event: step
   10.53s event: result     resolve_area_name  ok=false
   14.04s event: done
TOTAL 14.04s
```

**The gate asked for under two seconds and the honest answer is ten.** The cause is not
the transport. A `step` event names the tool the model chose, and the model has not chosen
anything until its first turn returns — on a local 20B that turn *is* the ten seconds.
There is no event to send before it because there is no fact to report.

The page is not blank for those ten seconds: `ConversationTurn` renders its waiting state
the moment the question is submitted. But that state comes from the client knowing it
issued a request, not from the server knowing anything, and calling that a "status" would
be the scripted-sequence failure this milestone was written to avoid (§11.9.2).

**The two honest fixes both cost something.** A `start` event would be a real event and
would arrive in milliseconds — but it would say only "the run began", which the client
already knows. Streaming the model's tokens would fill the gap with the model's own
reasoning, and §2.1 of `docs/empty-answers.md` explains why that text must not be shown:
it has not been through `verify_numbers`. Neither was taken, so the gate is recorded as
failed with its measurement rather than redefined to something reachable.
