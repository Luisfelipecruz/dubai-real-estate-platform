# The Copilot UI

**Milestone:** m18 · **PR:** #33 · **Built:** 2026-08-30

Three routes on the existing Next.js frontend that render what the copilot layer knows,
and 84 frontend tests where there were none.

---

## 1. What this milestone was for

Every milestone since m14 built something that could only be seen from a terminal. m14
added citations that are checked against the chunks they claim to quote. m15 added a
step-by-step tool trace with per-step cost. m16 added three golden fixtures and a
regression gate. m17 added a WebSocket transport **with no client on the other end.**

The plan's §8.3 carried the interface as "a decision rather than an omission" for four
milestones. This is that decision, taken.

The differentiator is not the answer. Every RAG demo renders a paragraph. This renders the
evidence: citations badged verified or unverified, grounding warnings shown rather than
hidden, the per-step tool trace with latency and cost, routing categories as chips, and
`$0.00` kept distinct from "unpriced".

---

## 2. What was built

| path | what it renders | source |
|---|---|---|
| `/copilot` | question box, route toggle, answer, evidence, trace | `POST /ask`, `POST /agent/query` |
| `/copilot/runs` | refusal rate, cap rate, tool error rate, p50/p95, cost, recent runs | `GET /agent/runs` |
| `/evals` | voice budget with per-stage verdict, tool catalogue, and the eval gap | `GET /voice/budget`, `GET /agent/tools` |

Six components under `frontend/src/components/copilot/`, two library modules under
`frontend/src/lib/`, and the test infrastructure the frontend did not have.

---

## 3. What was NOT built, and why

**`GET /agent/stream` — the SSE endpoint — is not in this milestone.** The plan makes it
step 1, ahead of any React, and that ordering could not be followed. It is blocked in three
independent places, and the third one is the interesting one:

1. `api/routers/agent.py` would hold the endpoint. **m15's uncommitted manifest claims it.**
2. `api/services/agent/executor.py` holds `run()`, which returns an `AgentResponse` and has
   no per-step callback or generator. Streaming requires changing it. **m15 claims it too.**
3. The obvious workaround — a new `api/routers/agent_stream.py`, registered by adding a
   name to `COPILOT_ROUTERS` in `api/main.py` — is closed by a test written to close it:

   ```python
   def test_registration_list_is_the_full_planned_set():
       """Guards the rule-3.2 decision itself: if a later PR adds its router by editing
       main.py instead of adding a module, this test is the thing that notices."""
       assert COPILOT_ROUTERS == ("search", "ask", "agent", "voice")
   ```

   Editing that test means editing `api/tests/test_main.py`, **which m17 claims.** The
   guard fired on exactly the case it was written for, four milestones after it was
   written, and against its own author.

So the work was split at the seam that already existed. **The client half of streaming is
built and tested in full** — framing, decoding, ordering, termination, the capability
probe — because it is pure TypeScript that no milestone claims, and because it is the half
with the interesting failure modes. The server half is the first task of the session after
#30–#32 are committed.

### The temptation that was refused

A typewriter animation over a response that arrived in one chunk would look like
streaming and would be a lie about latency. In a project whose entire thesis is honest
measurement, on the one page a reader actually sees, that is the worst available choice.

The page says instead:

> **No live trace:** this API build has no `/agent/stream`, so the whole run arrives in one
> response when it finishes. Agent runs on this machine have taken between 1.4 and 66.0
> seconds.

`probeStreaming()` reads the live API's own OpenAPI schema. When the endpoint ships, the
page streams with no change to the page.

---

## 4. Four requirements that came from measurements

**1. A refusal looks like a success.** `/ask` returns `answered: false` with a 200 and
`/agent/query` has four outcomes of which two are successes. `OUTCOME_STYLE.refused` is the
neutral `secondary` variant, and a test asserts it is not `destructive`. Rendering a
refusal in red would contradict M-17, where the refusals were correct on exactly the two
questions m13a proved unanswerable.

**2. The empty answer is visible.** M-47: 2–3 of 40 agent runs return `outcome: answered`
with an empty body, always the longest runs. It has its own amber panel naming it as a
known defect. See §5 — it reproduced on the first run captured for this milestone.

**3. No latency without saying it is one machine.** Every timing on the page carries the
caveat, and a test enforces it. M-21, M-35, M-48 and M-55 recorded this independently, and
M-55 measured a 3–4× swing on host load alone.

**4. No number the API does not return.** There is no arithmetic in the frontend. A page
that recomputed a median would re-introduce the drift `api/services/market.py` exists to
prevent, somewhere nobody grades.

---

## 5. What building it found

### 5.1 The request field is `q`, not `question`

The plan's prose says "question" throughout. `AgentRequest` and `AskRequest` both declare
`q`. A frontend written from the plan gets a 422 on every call. Found on the first live
capture; two tests now pin it.

### 5.2 `categories` has two different types on two endpoints

`/agent/query` returns `categories: ["meta", "geo", "sql"]` through its response model.
`/agent/runs` returns raw rows from `agent_runs`, where the column is a `VARCHAR(128)`
holding `"meta,geo,sql"` — **and that endpoint declares no response model at all**, so
nothing converts it. It is `null` for a run that called no tools.

A frontend written from `api/models/agent.py` calls `.map()` on a string on every row and
throws on the refused one. `parseCategories()` absorbs both shapes.

The real fix is a response model on `/agent/runs`. That is in `api/routers/agent.py`, which
m15 claims, so it is recorded here and deferred rather than patched in place.

### 5.3 M-47 reproduced on the first capture, and is worse than recorded

The first question put to the live agent — *"Of the areas bordering Business Bay, which had
the highest transaction count in 2024?"* — ran for **65,956 ms**, executed six tool calls
across seven steps, routed correctly through `meta → geo → sql`, and returned:

```json
{ "outcome": "answered", "answered": true, "answer": null }
```

Two corrections to the record:

- **M-48 gives the agent range as 1.4–58.6 s. This run took 66.0 s**, which is outside it.
  The ceiling was not a ceiling.
- **M-47 describes "an empty body". The value is `null`, not `""`.** True in substance,
  imprecise in type, and the difference matters to a renderer: `null.trim()` throws where
  `"".trim()` does not. The component uses `(answer ?? "").trim()` and a fixture test pins
  the real value.

### 5.4 The eval harness has no HTTP surface

The API exposes 36 operations and not one returns an eval result. The three golden fixtures
are graded by `make eval-*`, which writes to a terminal, and `eval/thresholds.yaml` is a
file the container never reads.

So `/evals` renders what the API genuinely reports and **prints the commands for the rest**
rather than transcribing 74 graded questions into TypeScript, where they would look
authoritative and go stale the next time a grader changes — the exact failure `--regrade`
exists to prevent.

That gap is a result of this milestone. An eval harness with no API is invisible to
everything except the person who runs `make`.

### 5.5 `npm run lint` has never been runnable

The script is in `package.json`, and running it prompts interactively to configure ESLint,
because no ESLint config exists. Pre-existing, unrelated to m18, and left alone — it is not
this milestone's to fix, but it should stop being described as a working command.

---

## 6. Testing

**The frontend had no test setup at all.** No Jest, no React Testing Library, nothing in
`devDependencies`, while the root `CLAUDE.md` requires both. m18 adds the infrastructure and
**84 tests**.

```
npm test          # 84 tests, 8 suites
npm run build     # production build, 12 routes (3 of them new)
npx tsc --noEmit  # clean
```

### The jsdom problem, and why the fix is an environment

jsdom implements no `fetch`, no `Response` and no `ReadableStream`. The SSE client is built
on all three, so without a polyfill the tests that matter — a frame split across chunk
boundaries, a stream that ends mid-run — could not be written, and the client would ship
with only its pure parser covered.

The polyfill cannot live in `jest.setup.ts`: that file already runs **inside** the jsdom
context, where there is nothing to copy from. `jest.environment.ts` is loaded by Jest in the
Node realm, outside the sandbox it is about to build, so the real implementations are in
scope there. Node's own are used rather than a stub — a hand-written fake would be testing
the fake.

### Fixtures from real responses

`frontend/src/lib/__fixtures__/` holds four unedited captures from the live stack on
2026-08-30 — all four agent outcomes plus an `/ask` answer with three verified citations —
with long tool payloads truncated and nothing else changed. `RealRuns.test.tsx` renders the
components against them.

Hand-built fixtures prove the components handle the shapes their author believed the API
produces. These prove they handle the shapes it produces, which is where both defects in
§5.1 and §5.2 were actually found.

---

## 7. What m18 deliberately does not do

- **No chat history, no sessions, no persistence.** One question, one answer, one trace.
- **No auth.** Local demo.
- **No rebuild of `/map`, `/areas`, `/transactions`.** They work.
- **No answer logic in TypeScript.**
- **No hiding the model.** `local · gpt-oss:20b` is on every result.

---

## 8. Next

1. **`GET /agent/stream`.** Unblocked once #30–#32 are committed. The client is written and
   tested; the server needs a per-step hook on `executor.run()` and an endpoint. `readSSE`
   and `probeStreaming` are the consumer contract it must satisfy.
2. **A response model on `/agent/runs`,** which fixes §5.2 at the source.
3. **An endpoint for the eval harness,** which fixes §5.4 and is what would let `/evals`
   render the fixtures it was specified to render.
