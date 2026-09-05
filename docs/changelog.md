# Changelog

## v0.14.0 - The eval harness gets an endpoint, and the score gets an expiry date (2026-09-05)

The evaluation harness had no HTTP surface: 36 operations and not one returned a result,
so `/evals` printed the make commands instead of numbers. This closes that, and the first
thing the endpoint did was measure a suite nobody had re-run since the tenth tool was
registered. **45 REST operations - 503 API tests, 229 frontend tests.**

### Added

- **`GET /evals/latest`** -- the last recorded run joined to every floor in
  `eval/thresholds.yaml`, with three states per floor. `not_measured` is not a pass and not
  a failure: a `--suite agent` run measures nothing under `retrieval.`, and collapsing that
  into either neighbour publishes a gate nobody ran.
- **`eval_results` (migration `0006`)** -- one row per recorded run. A table rather than a
  JSON file because `eval/` is mounted read-only on purpose, and because one number with no
  history cannot say whether the system is improving.
- **A staleness fingerprint.** Every result stores the tool names registered when it ran and
  the endpoint compares them with the live registry on every read. `stale`, `added_since`
  and `removed_since` -- with `known: false` as a third state, because a result with no
  fingerprint is not a result that has not drifted.
- `--record`, `--record-from` and a `_meta` block in `--out`. `--record` refuses a `--only`
  run: `--only A-01 --record` would publish `answer_accuracy: 1.000` over a denominator of
  one, and once the row exists no rendering can undo it.
- **R-15 and R-16** in `eval/golden/routing.yaml`, the first two questions in that file that
  name no area, linked from A-18 and the new A-41. Both passed on the first run.

### Changed

- **`/evals` renders the gate instead of printing commands.** The commands stay, because
  the endpoint reports a run and cannot start one -- and two of the five it used to print,
  `make eval-answers` and `make eval-gate`, do not exist and never did.
- `make eval` passes `--record`. The single-suite targets deliberately do not: a partial
  suite must not become the deployment's published score.
- `COPILOT_ROUTERS` gains a fifth name. `test_registration_list_is_the_full_planned_set`
  fired again, and this time the answer was the one the rule intends -- a new module, with
  the reasoning written into the test's docstring rather than around it.

### Fixed

- **`area_neighbors` defaulted to a predicate that hid real neighbours.** `ST_Touches` is
  the strict DE-9IM case, and of 614 adjacent community pairs 483 touch while 131 overlap
  by a sliver. Marsa Dubai is in that set four times -- its largest overlap is 1.08 m2
  against a polygon of roughly 9 km2 -- so the tool answered "Dubai Marina borders no other
  community", a complete and confident false sentence. The default is now `ST_Intersects`;
  the strict predicate is still reachable by name. **The four spatial questions in
  `eval/golden/answers.yaml` still assert `ST_Touches` and were deliberately NOT changed to
  match -- see Measured, below.**
- **`list_areas` could not restrict a ranking to a year**, so "which areas had the most
  transactions in 2024" was answered with a 1977-2026 lifetime ranking. It now takes a
  `year`, and a year with no rows is a refusal rather than a table of zeroes -- the same
  coverage rule `dataset_aggregate` applies, for the same reason.
- **`dataset_aggregate` rejected `breakdown_by="area_name"` instead of redirecting it.** The
  model's instinct was right and correctly expressed; the schema answered "Input should be
  'year' or 'property_type'", which names no alternative, and the run gave up on a question
  the data answers easily. It now routes the caller to `list_areas`.
- **`record_result` reused a connection pool across event loops.** `asyncio.run` builds a
  new loop each call and `resolve_truths` had already used the shared engine in an earlier
  one, so the write raised `got Future attached to a different loop` *after* the entire
  suite had run and every model call had been paid for. Caught by running
  `--suite truths --record`, which is seconds, before trusting it at the end of a
  thirty-minute run.

### Measured

- **First full suite since `dataset_aggregate` was registered. All 8 floors pass.**
  Answers **33/41 = 0.805**, against 30/40 = 0.750 previously. Routes 9/10 = 0.900. Retrieval
  dense: top-1 0.850, hit@5 0.900, MRR 0.881. The three 1.0 properties held -- no
  fabrication on 11 unanswerable questions, no named decoy hit, and the injection question
  never reached the corpus.
- **The route denominator is 10 and eleven questions are linked.** A-26 -- the hardest
  linked question in the set, a spatial predicate joined to an aggregate -- returned
  `HTTP 504` when Ollama did not respond within 120 s, and an errored run carries no
  `routing_id`, so it left `route_n` rather than failing in it. Graded as a failure the
  rate is 0.818; dropped, 0.900. Recorded, not decided: a timeout is not a routing
  failure, but a silently shrinking denominator is worse than one.
- **The neighbours tool and its fixture no longer measure the same thing.** All four
  spatial questions assert `ST_Touches`; the tool's default is now `ST_Intersects`, which
  returns a superset, so A-23 and A-25 score `partial` for naming real neighbours the
  fixture omits. The fixture was NOT edited to match: rewriting ground truth so the code
  under test passes is the failure this harness exists to prevent, and a good argument for
  the code change does not convert into one for rewriting the rubric. The disagreement is
  left standing as the result.

## v0.13.0 - The machinery, hidden; the rates, over time (2026-08-30)

Four milestones had a half each, all of them waiting on files that belonged to unmerged
branches. #31-#36 merged the backlog and every one of those files became ordinary. This
release is what the halves do once they can reach each other. **44 REST operations - 479
API tests, 189 frontend tests, ten agent tools.**

### Added

- `GET /agent/stream` -- the same run as `POST /agent/query`, reported as it happens.
  `step` and `result` events in the shapes `frontend/src/lib/stream.ts` had already been
  parsing and unit-testing since v0.12.0 with no server on the other end. `done` is always
  sent, including on failure, because a stream that stops without it is indistinguishable
  from a network drop.
- `GET /agent/runs/timeseries`, `GET /agent/health`, `GET /agent/tools/stats` -- rates over
  time, the two most recent buckets compared with their denominators, and per-tool failure
  attribution.
- `dataset_aggregate`, the tenth tool -- dataset-wide totals, medians and extremes. It
  answered its first live question by routing to itself unprompted and returning 35,577
  villa transactions, which is the golden value for an eval question that used to be
  DECLINED.
- `agent_runs.stop_reason` (migration `0004`) and `agent_tool_calls` (migration `0005`).

### Changed

- **`/copilot` no longer lays the machinery in front of the answer.** The tool trace moved
  behind a one-click disclosure inside `ConversationTurn`; what replaces it is
  human-language progress DERIVED from real events -- no timer, no scripted sequence, and
  nothing to say until something has happened.
- **`/copilot/runs` is a panel, not a log.** Trends with their sample sizes, four metrics
  over a selectable window, and per-tool attribution. An interval with no runs shows no
  rate rather than 0%; a percentile over fewer than 20 runs is not shown at all.
- `jest.config.ts` counts coverage for `src/components/conversation/` and
  `src/components/observability/`, which had been tested with their coverage uncounted
  for two milestones.

### Fixed

- **M-47, the run that gathered everything and said nothing.** 8 of 147 answered runs
  returned a null answer. It was two bugs, not one, and `finish_reason` separated them --
  a value the system computed on every run and persisted nowhere. A blank final turn now
  produces an honest sentence carrying the findings, and the reason lands in the warnings.
- A `trend()` ordering bug that reported two equal rates over one run and three as `flat`
  -- a conclusion the sample cannot support. Caught by the milestone's own live invariant.

### Known not to be met

- Plan §12.7 gate 1: the first human-readable status arrives at **10.1 s**, not under two.
  There is nothing to report until the model has chosen a tool, and on a local 20B that
  decision is the ten seconds. Measured, not estimated -- see `docs/conversational-surface.md`.
- Plan §13.6 gate 5: no threshold from `eval/thresholds.yaml` is shown with its live state.
  It needs `GET /evals/latest`.


## v0.12.0 - The evidence, rendered (2026-08-30)

Four milestones built things that could only be seen from a terminal. m14 checked citations
against the chunks they claim to quote, m15 recorded a step-by-step trace with per-step
cost, m16 graded three golden fixtures, and m17 shipped a WebSocket transport **with no
client on the other end.** This is the interface, and the differentiator is not the answer:
every RAG demo renders a paragraph. **40 REST operations - 340 API tests, and 84 frontend
tests where there were none.**

### Added

- `/copilot` -- one question, a route toggle between `ask` and `agent`, the answer, and the
  evidence underneath it. Citations badged verified/unverified, grounding warnings shown
  rather than hidden, the per-step tool trace with arguments, raw result, latency and cost,
  routing categories as chips.
- `/copilot/runs` -- refusal rate, cap rate, tool error rate, unverified numbers, p50/p95
  and cost over `agent_runs`, with the recent runs beneath them.
- `/evals` -- the voice budget with its per-stage verdict and the tool catalogue as the
  model receives it.
- `frontend/src/lib/stream.ts` -- the SSE client for `GET /agent/stream`: incremental frame
  parser, typed event decoding, termination detection, and a capability probe against the
  live API's own OpenAPI schema.
- `frontend/src/lib/copilot.ts` -- typed fetchers for `/agent/query`, `/ask`, `/agent/runs`
  and `/agent/tools`, and a `CopilotError` that keeps the status code, because 503 (the LLM
  layer is off) and 502 (the provider returned something unusable) need different responses
  and `apiFetch` collapses both into a bare `Error`.
- **Jest and React Testing Library, which the frontend did not have.** No Jest, no RTL,
  nothing in `devDependencies`, while the root `CLAUDE.md` requires both. 84 tests across 8
  suites.
- `frontend/src/lib/__fixtures__/` -- four unedited captures from the live stack: all four
  agent outcomes plus an `/ask` answer with three verified citations.
- `docs/copilot-ui.md`.

### Measured

- **A live agent run took 65,956 ms.** M-48 records the range as 1.4-58.6 s. The ceiling
  was not a ceiling.
- **M-47 reproduced on the FIRST question put to the live agent.** Six tool calls across
  seven steps, routed correctly through `meta -> geo -> sql`, and
  `{"outcome": "answered", "answered": true, "answer": null}`.
- **10.3% of all tool calls in this deployment have failed** (31 of 301, over 213 recorded
  runs), and the refusal rate is 30.0%. Both are now on a page rather than in a query.

### Fixed

- **`categories` has two different types on two endpoints, and one of them has no response
  model.** `/agent/query` returns `["meta","geo","sql"]`; `/agent/runs` returns raw rows
  where the column is a `VARCHAR(128)` holding `"meta,geo,sql"`, null for a run that called
  no tools. A frontend written from `api/models/agent.py` calls `.map()` on a string on
  every row and throws on the refused one. Absorbed in `parseCategories()`; the real fix is
  a response model on `/agent/runs` and it belongs to a file this release does not own.
- **The request field is `q`, not `question`.** The plan's prose says "question"
  throughout; `AgentRequest` and `AskRequest` both declare `q`, so a frontend written from
  the plan gets a 422 on every call. Two tests now pin it.

### Not in this release

- **`GET /agent/stream`, and the reason is worth recording.** The plan makes SSE step 1,
  ahead of any React. It is blocked in three independent places: the endpoint belongs in
  `api/routers/agent.py` and the per-step hook in `api/services/agent/executor.py`, both
  claimed by m15's uncommitted manifest -- and the obvious workaround, a new router module
  registered by editing `COPILOT_ROUTERS`, is closed by
  `test_registration_list_is_the_full_planned_set`, a test written four milestones ago to
  notice exactly that move, in a file m17 claims. The guard fired on the case it was
  written for, against its own author.

  So the work was split at the seam that already existed: **the client half of streaming is
  built and tested in full**, and the server half is the first task of the session after
  #30-#32 are committed.
- **A typewriter animation over the non-streaming response.** It would look like streaming
  and would be a lie about latency. The page states the degradation in words instead, and
  `probeStreaming()` flips it automatically when the endpoint ships.
- **The golden fixtures on `/evals`.** The API exposes 36 operations and not one returns an
  eval result -- the fixtures are graded by `make eval-*`, which writes to a terminal. The
  page prints the commands rather than transcribing 74 graded questions into TypeScript,
  where they would look authoritative and go stale the next time a grader changes. **An
  eval harness with no API is invisible to everything except the person who runs make.**

## v0.11.0 - The 800 ms budget, measured (2026-08-30)

A complete spoken turn takes **3.0-3.3 seconds to first audio against an 800 ms budget** --
3.8-4.1x over, and roughly 2.4x worse than the plan's own pessimistic projection. The
finding is not that the voice stack is slow. **Generation is 65% of it and the three stages
this release actually built are 28%.**
**40 REST operations - 340 tests (314 existing + 26 new).**

### Added

- `infra/voice/` -- a third model service, 820 MB and **no torch anywhere in it**. Whisper
  through CTranslate2, Piper through ONNX Runtime, `webrtcvad-wheels` for endpointing.
  `POST /vad`, `POST /stt`, `POST /tts`, `GET /health`, every response carrying its own
  stage timing.
- `POST /voice/turn` -- the MEASUREMENT path. Raw PCM in, answer and speech out, every
  stage timed. It exists because a WebSocket cannot be measured with `curl`, and every
  figure in `docs/voice-latency.md` comes from it.
- `WS /voice/stream` -- the interactive path. Binary frames up; `endpoint`, `transcript`,
  `answer`, audio frames and `timings` down. SSE cannot carry audio upstream.
- `GET /voice/budget` -- the budget as data, with the last measurement beside each target
  and the verdict computed rather than written down. An unmeasured stage reports `null`,
  not `0`.
- `api/services/voice/` and `api/models/voice.py`.

`api/main.py` was NOT touched. `voice` has been in `COPILOT_ROUTERS` since m13 and the
tolerant loop found it by name -- the third demonstration, after `ask` in m14 and `agent`
in m15.

### Measured

- **3,025-3,318 ms to first audio, five runs, host load ~18.** VAD 1.4-2.4 ms, STT
  387-431 ms, retrieval 186-255 ms, generation 2,043-2,157 ms, TTS 353-560 ms.
- **The 200 ms VAD budget is not a cost, it is a decision.** Endpoint detection over four
  seconds of audio costs **0.35-0.52 ms**. The 200 ms is trailing silence -- time spent
  deliberately waiting. The endpointer reports where silence BEGAN, so the threshold cannot
  flatter its own measurement: 3,340 ms at thresholds of 100, 200 and 400 ms, and NO
  endpoint at 800 ms because the clip holds only 600 ms of pause. The lever is bounded by
  how long the speaker stops for, not by how fast the detector is.
- **Beam search buys nothing and costs 20-60 ms.** Greedy 329-352 ms, the library's default
  beam of 5 at 346-412 ms, identical transcript. Greedy is now the default.
- **The TTS quality/latency trade does not exist here.** `medium` 122-201 ms against `low`
  136-196 ms, back to back at the same load. The small voice is not faster, so there is no
  latency argument for the quality hit.
- **Host load moves the same call 3-4x.** TTS at 122-201 ms at load ~7.8 and 499-673 ms at
  load ~17, same text, same warm model. Measured DIRECTLY against the service it is
  499-673 ms while the same stage measured INSIDE the pipeline is 353-560 ms -- the
  pipeline is not the cause, the machine is busy. Fourth independent reproduction of M-21
  in this project, after M-35 and M-48.
- **At load ~7.8 the three new stages total ~480 ms and fit inside 800 ms. At load ~18 they
  total ~850 ms and do not.** Even the part of the budget that could fit is only reliably
  inside it on an idle machine.
- **The agent route measured rather than argued.** 3,220 ms and 4,557 ms against `ask`'s
  3,025-3,318 ms. On the easiest question it is comparable; M-48 measured the distribution
  across 40 questions at 1.4-58.6 s, and it is the distribution that disqualifies it.
- **The three levers of plan §7.2, scored honestly: ~8%, 0% (already taken), and unbuilt.**
  Overlapping retrieval can save at most 8% because retrieval turned out to be cheap.
  Skipping the reranker is free rather than a sacrifice -- m16 measured it at 8/20 top-1
  against dense's 17/20 while costing 2.9 s, so it loses on both axes. Early synthesis of
  the opening sentence is real, but the larger half needs token streaming that does not
  exist.

### Fixed

- **The WebSocket protocol was a lie.** `/voice/stream` documented a binary audio frame
  after the answer and sent none -- the pipeline kept only the LENGTH of the synthesised
  audio. A client would have received a correct transcript, a correct answer, correct
  timings, and silence. Found by connecting a real client and counting frames. It now
  streams the PCM in the same 20 ms framing the client sends, and a test asserts the count.
- **`test_every_copilot_router_...` had an untested premise.** It asserted that every route
  a copilot router declares appears in the OpenAPI schema. True for four milestones, and
  broken by the project's first WebSocket, which FastAPI correctly excludes. HTTP routes
  are now checked against the schema and WebSocket routes against the mounted app.

### Not in this release

- **Streaming generation.** The single largest available win, and it needs the SSE layer
  m15 declined to build. Until then time-to-first-audio has a two-second floor.
- **A browser client.** Endpointing runs server-side; a local endpointer would save a
  round trip per chunk, but VAD compute is 0.35 ms so the saving is transport, and there is
  no client to put it in.
- **Opus.** §7.1 specifies 20 ms Opus frames; the transport carries raw PCM at 20 ms
  framing. Opus would cut bandwidth ~10x and bandwidth is not what is wrong here.
- **Three environment variables.** `PIPER_VOICE`, `WHISPER_COMPUTE` and `VOICE_BUDGET_MS`
  are read by the code and were not forwarded by compose -- the m14 gap recurring. Added in
  this release's own command-sheet step, after the milestones that claim that file have
  been committed.

## v0.10.0 - The evaluation harness: grading a number, not a route (2026-08-30)

m15 answered AED 550,010 for a typical Dubai Marina rent against a true per-property
median of AED 120,000, and `eval/golden/routing.yaml` **passed** it — correctly, because
route grading cannot see a value. This milestone builds the half that can.
**38 REST operations - 314 tests (231 existing + 83 new).**

### Added

- `eval/golden/answers.yaml` — 40 questions where the expected value is a **hand-written
  query against the raw tables**, run at grade time. Never a literal: a literal goes stale
  when 561,115 rows are reloaded, and is circular if it ever came from the code under test.
  These queries deliberately do not import `services/market.py`.
- **Named decoys, recorded as queries.** "Wrong" is a poor verdict when the useful question
  is *how* wrong. A-14's decoy is `AVG(annual_amount)` where the truth is a per-property
  median — the v0.5.0 / G-02 trap, re-entered through a new tool — so the harness prints
  the trap's name rather than an anonymous miss.
- `api/services/evaluation/` — the graders as library code with 66 tests. Every grading bug
  this project has found was found by reading output by hand; two of them were one
  assertion each.
- `scripts/run_eval.py` — three suites (`truths`, `retrieval`, `agent`) and `--regrade`,
  which re-scores a stored run with current graders and no model calls.
- `eval/thresholds.yaml` and `.github/workflows/eval.yml`.
- `eval/golden/retrieval.yaml` 10 → 20 questions, in two labelled **cohorts** so the
  published "dense 8/10" is not silently redefined by a larger denominator.
- `make eval`, `eval-truths`, `eval-retrieval`, `eval-agent`, `eval-routing`.

### Measured

- **Retrieval at n=20, and the corpus moved under it.** dense 16/20 top-1 at a 348-chunk
  corpus and 17/20 at 398 after `make index` picked up this milestone's own write-up.
  Nothing else changed. The m13a cohort went 8/10 → 9/10 on dense and 3/10 → 2/10 on
  lexical: adding two documents that *describe* the system moved published numbers in both
  directions. Diagnosed to the document — m15's write-up opens by stating its gate
  question, one word from G-07, so the isolation test cannot catch it. Graded 0 as named
  decoys rather than deleted, following m13a's stated policy.
- **A prediction written into the fixture before the run was refuted by the run.** G-13's
  note argued the question would be "dense or nothing" because the source never uses its
  vocabulary. Lexical found it at rank 1, dense missed it entirely, and **hybrid threw the
  correct arm away** — the third demonstration that RRF has no notion of which arm to
  trust. The bridge is one distinctive noun occurring exactly once in the corpus, which
  answers m13a's standing question about whether the lexical arm ever earns its place.
- **Answers: 30/40 and 31/40 across two full runs.** Zero fabricated figures across 80
  unanswerable questions. Zero answers matching a named decoy. A-14 now answers 120,000.
- **Seven of run 1's fifteen failures were the grader, not the agent.** Regrading the same
  responses moved 25/40 to 30/40. All six spatial questions had been marked wrong while
  every answer was right: the model writes place names with U+202F and U+2019, the
  community table stores ASCII, and a literal substring test between them is false.
- **The fourth encoding failure in three detectors, and the system was right every time.**
  After m15's refusal detector (U+2019) and numeric guard (space separator), and this
  milestone's number extractor (U+202F). Normalisation is now one shared function.
- **Routing is not deterministic at temperature 0.** A-14 routed cleanly in one run and
  reached for the corpus in the next, on identical code — 9/9 and 8/9. The m14 injection
  mitigation is *probabilistic*; the threshold file now separates the injection question,
  gated as a property at 1.0, from overall route accuracy, gated as a rate.
- **nDCG@5 came back as 2.436**, which is impossible for a ratio bounded at 1: the fixture
  grades documents while `/search` ranks chunks, so a document holding three of the top
  five slots contributed its gain three times against an ideal counting it once.

### Fixed

- `mentioned_names` returned universe order rather than order of appearance, so grading
  what an answer "leads with" read the longest matching name.
- The subject of a spatial question was scored as a wrongly-named neighbour: "X borders Y
  and Z" is a well-formed answer that restates its own question, and every correct answer
  scored `partial` at precision 0.67.
- **The CI workflow this release adds did not run.** It was written to prove the graders
  need no infrastructure, and it failed at collection on `No module named 'fastapi'`
  because `conftest.py` imported the application at module scope. Found by running its own
  commands in a bare container. The import moved inside the fixture, which makes the
  property real instead of asserted: 66 grader tests and 16 fixture tests now pass on five
  packages, no database and no model.
- A lookup for `scripts/` found an empty `api/scripts/` that docker-compose had written
  into the source tree by creating a nested bind-mount point. Git does not track empty
  directories, so nothing ever showed it. The lookup now searches for the file.
- `test_lexical_relaxes_...` pinned a fact about the corpus and broke when the corpus grew
  — with the exact sentence its own failure message predicted. Rewritten to assert the
  invariant (the fallback fires iff the strict query matched nothing) rather than one
  instance of it.

### Found and deliberately NOT fixed here

- **Six questions the data can answer were declined**, because all nine tools are
  area-scoped and nothing computes a dataset-wide aggregate. The agent said so plainly.
  The routing eval could not find this: every routing question names an area. It is a
  tool-layer gap, and an eval milestone that quietly edits the system it measures has
  stopped being an eval.
- **Two to three runs per pass return an empty body with `outcome: "answered"`**, always
  the longest runs. m15's executor docstring states the principle this breaks. It now has
  its own verdict, `empty`, so a system fault is never counted inside a quality metric.

### Not in this release

- The provider comparison. Still no `ANTHROPIC_API_KEY`; `complete_structured` and
  `complete_with_tools` remain unobserved against Anthropic's servers. Third milestone
  carrying this caveat.
- Prompt caching. `cache_read_input_tokens` has never been above zero.
- LLM-as-judge. Every question in `answers.yaml` has a deterministic verdict available, and
  the plan forbids a judge where one does.
- CI running any of the three suites. A hosted runner has no 1 GB of Land Department data,
  no Ollama and no API key; the workflow runs the graders and says plainly what it skips.

## v0.9.0 - Agent orchestration over nine tools (2026-08-29)

`/ask` answers from documents. This answers by *computing* -- resolving a name, running a
PostGIS adjacency query, then an aggregate -- and reports every step it took, with its
cost and latency. **38 REST operations - 231 tests (191 existing + 40 new).**

### Added
- `POST /agent/query` -- multi-step question answering over nine tools. Returns the
  answer, every step with its arguments and raw tool result, the tool categories used,
  grounding warnings, per-step cost and a `generate`/`tools` latency split.
- `GET /agent/tools` -- the tool catalogue as the model receives it, generated schema
  included. Reviewing a paraphrase of prompt content is not reviewing it.
- `GET /agent/runs` -- aggregates over `agent_runs`: refusal rate, step-cap rate, tool
  error rate, unverified numbers, p50/p95.
- `GET /areas/resolve` -- turn a name a person would use into the name the data
  contains. **`Dubai Marina` is not in the DLD data**; it is filed as `Marsa Dubai`.
- `GET /areas/{name}/neighbors` -- adjacency keyed by name rather than by polygon id,
  returning candidate polygon names when nothing matches.
- `api/services/market.py` -- the tabular layer, extracted from the routers so the agent
  and the REST endpoints cannot state two different exact numbers for one question.
- `api/services/agent/` -- `tools.py`, `executor.py`, `settings.py`.
- `agent_runs` table and `llm_calls.agent_run_id` (migration `0003`).
- `eval/golden/routing.yaml` (14 questions) and `scripts/run_routing_eval.py`.
- `docs/agent-orchestration.md`.

### Fixed
- `docker-compose.yml` never forwarded `LLM_TIMEOUT_S`, `LLM_MAX_OUTPUT_TOKENS` or
  `LLM_REPAIR_ATTEMPTS`, so setting them in `.env` did nothing at all. Found while
  building m14, deferred because the file belonged to an uncommitted m13, fixed here.

### Measured
- **14/14 on the routing set**, from 9/14 on the first run. By route: `sql` 3/3,
  `rag` 4/4, `geo` 1/1, `multi` 3/3, `refuse` 3/3. The fixture was written and committed
  before `api/services/agent/` contained a line.
- **Three of the five first-run failures were a bug in the grader, not the agent.** The
  refusal detector matched `I can't` with an ASCII apostrophe; `gpt-oss` writes `I can\u2019t`
  with a typographic one. The abstention rate was silently pinned at zero.
- **A local 20B emits invalid tool calls.** Deterministically at temperature 0, five
  calls deep, `gpt-oss:20b` produced a JSON key with no value and Ollama answered
  HTTP 500 -- discarding five correct steps. A provider failure mid-run now returns the
  completed steps labelled `failed`.
- **Batching a tool halved the turns.** `area_summary` took one area name and the model
  called it once per neighbour -- four round trips at 7-21 s each, and the run died on
  step 6. Taking a list made the same question three turns instead of six.
- **The model invented a currency.** Given three AED medians it produced a table headed
  "USD" with `$` on every figure: every number real, each wrong by the exchange rate.
  Only the label was false, which is why nothing else catches it.
- Grounding warnings across five runs of the set: **2/14 -> 2/14 -> 1/14 -> 1/14 -> 0/14**.
  Three false-positive classes were removed (years quoted from the question; a space used
  as a thousands separator). Two of the flags were TRUE positives and each found a real
  bug: hard-coded figures in this project's own system prompt, and the rent error below.
- Latency: 87 s for 14 questions at host load 5.03, **144 s for the same code** at 7.80.
  Tool time is milliseconds; essentially all of the wall clock is the model.

### The route was right and the answer was 4.6x wrong
`R-05` asks what a typical Dubai Marina apartment rents for. The agent routed it
perfectly -- resolved `Dubai Marina` to `Marsa Dubai`, called the SQL tool, never touched
the corpus -- and answered **AED 550,010**. The true per-property median is
**AED 120,000**.

`area_summary` exposed `AVG(annual_amount)` as `avg_annual_rent`. That column is the
CONTRACT total, and one contract in that area covers up to **232 properties**, each row
carrying the full portfolio amount. It is the trap this changelog already documented at
v0.5.0 and the retrieval golden set documents as G-02, re-introduced by a new tool.

The routing eval passed it, correctly: it grades the ROUTE. This is the clearest possible
demonstration of that limitation, so it is recorded rather than quietly fixed. The tool
now returns `typical_annual_rent_per_property` and the raw mean is renamed
`avg_contract_annual_amount` -- a name that says what the column actually is.

### One definition of a number
The SQL moved out of `routers/areas.py` and `routers/communities.py` into
`services/market.py`, and both the routers and the tool handlers call it. The entire
argument for routing numeric questions to SQL instead of prose is that SQL is *exact*; if
the agent's count and the endpoint's count could drift apart, that argument is worthless.

### Routing is the mitigation
m14 wrote a false fact into a public note and the system answered from it with every
grounding check green -- because the answer was faithful to a corpus that was wrong.
Verification cannot catch that. `R-01` in the routing set is that question, and it now
routes to `COUNT(*)` and never touches the corpus.

## v0.8.0 - Grounded answers over the retrieval layer (2026-08-29)

Retrieval returned chunks. This turns them into answers that can be checked -- and, on
two of the ten golden questions, into a refusal. **33 REST operations · 191 tests
(118 existing + 73 new).**

### Added
- `POST /ask` -- grounded question answering. Returns the answer, the contexts it was
  built from, every citation with two independent verdicts (`resolved`: the chunk was
  really retrieved; `quote_found`: the quoted span is really in it), the grounding
  warnings, token counts, cost and per-stage timings.
- `GET /ask/providers` -- what the generation layer is configured to do, and with
  `probe=true` whether it responds. Off by default: a health check that wakes a 13 GB
  model on every dashboard refresh is one nobody leaves enabled.
- `GET /ask/costs` -- aggregates over `llm_calls`. Cost per call, cache hit rate,
  abstention rate, p50/p95 split between retrieval and generation, and the ratio of the
  pre-call token estimate to the provider's real count.
- `api/services/llm/` -- provider abstraction. `base.py` (Protocol + value types),
  `local_provider.py` (host Ollama, OpenAI-compatible endpoint, constrained decoding plus
  a capped repair loop), `anthropic_provider.py` (`claude-opus-5`, adaptive thinking,
  per-call effort, cacheable system prefix), `registry.py`, `pricing.py`, `schema.py`,
  `settings.py`.
- `llm_calls` table (migration `0002`). One row per generation call: tokens, cost,
  latency, repair attempts, and the grounding outcome, so quality and cost are read off
  one row rather than joined across two stores.
- `docs/llm-app-layer.md` -- the measurements, the two verifier fixes the first ten
  requests forced, and the injection results.

### The refusal is the feature
Two of the ten golden questions have no retrievable answer at any k in any retrieval
mode. `/ask` refused on **exactly those two** and answered the other eight: abstention
precision 2/2, recall 2/2. A system that always answers is not 80% right on this set --
it is 80% right and 20% confidently fabricated, and the 20% is indistinguishable from the
80% to whoever reads it. A refusal is a **200** with `answered: false`, never a 5xx:
reporting an honest abstention as an error would make the system look broken precisely
when it is behaving best, and would make the abstention rate uncollectable from status
codes.

### Shape is repaired. Content is not.
Malformed JSON gets a capped retry with the validation error fed back as the next turn
(re-sending an identical prompt at temperature 0 gets an identical answer, so a retry
without the error text is not a retry). A citation that does not resolve, or a quote that
is not in the chunk it names, is **reported**, never retried. Retrying until the model
produces a citation that resolves would train the system to launder a hallucination into
a well-formed one -- worse than a visible failure, because it is invisible.

### Measured
- **Golden set, local `gpt-oss:20b`, `mode=dense`, `rerank=false`, k=5**: 8/10 answered,
  2/10 refused (G-03 and G-10, and only those), the ideal document cited on 6 of the 6
  answered questions that have one, 15 of 16 citations resolved with the quote verified,
  0 JSON repair retries.
- **Quote verification had to learn ellipsis, from real output.** The first request to
  this endpoint produced a citation that failed -- not a fabrication: the model had
  spliced two non-adjacent lines of `docs/architecture.md` into one quotation and marked
  the join with `...`. Fragments are now checked **in order**, which on the same run
  caught a quote that reversed a measurement and its conclusion from
  `postgis-query-plans.md`. Every word was in the source; the order was not.
- **A guard that is wrong a third of the time is worse than no guard.** The numeric-claim
  check fired on 3 of 10 questions on its first run, every time because the model wrote
  `(chunk 567)` into its prose and chunk ids live in the block delimiters rather than the
  chunk text. Ids are now part of the haystack and the prompt tells the model not to put
  them in the answer.
- **Prompt injection, three attacks through the public `POST /notes` endpoint.** Two
  instruction-style attacks -- "IGNORE ALL PREVIOUS INSTRUCTIONS", and a forged
  context-block delimiter carrying a fabricated chunk -- were both ignored by the model.
  The third wrote a **false fact** into a note as ordinary prose and succeeded
  completely: high confidence, one citation, resolved, quote verified, every check green.
  Citation verification proves an answer is faithful to the corpus; it says nothing about
  whether the corpus is true. An answer whose supporting citations are all analyst notes
  is now capped at `confidence: low` with a warning naming the reason.
- **Latency is not a stable number on a shared machine, and quality is.** Three runs of
  the same ten questions: generate p50 7,914 ms / 19,681 ms / 20,927 ms -- a 2.6x spread.
  Retrieval measured *inside* an `/ask` request came to 417 ms p50 while retrieval
  measured alone on the same stack was 23-35 ms. The local model saturates the host and
  every stage measured beside it inflates. All three runs answered the same eight
  questions, refused the same two, and cited the same ideal documents.
- **The 800 ms voice budget cannot contain a local 20B synthesis step**, at either
  7.9 s or 20.9 s. m17 has to stream, truncate, or use a hosted model.
- **The token estimator, checked against a real tokenizer.** `estimate_tokens` (WordPiece,
  the chunker's) over `gpt-oss:20b`'s reported `prompt_tokens`: median **1.123**, range
  0.954-1.213 across ten prompts. It overestimates by ~12%, which is the safe direction
  for a ceiling, so `LLM_MAX_INPUT_TOKENS=8000` means roughly 7,100 real tokens in the
  worst observed case against a 2,059-token median request.

### Fixed
- **`index_corpus.py` never removed a source that vanished from the corpus.** The loop
  only ever visited sources present in the corpus file, so a deleted document, a deleted
  note, or an area sheet dropping below the 10-record floor kept its chunks in
  `doc_chunks` and kept being retrieved. Found by the injection test above: a note was
  POSTed, indexed, attacked, then DELETEd, and it was still answering questions after the
  next `make index`. `POST /notes` is user-writable, so a delete that leaves the content
  live and quotable is a data-deletion failure, not untidiness. Pruning now runs after
  the per-source pass, is scoped by `--source-type`, and **refuses to run against a
  corpus file with zero documents** -- a `build_corpus.py` failure and an empty corpus
  are indistinguishable from inside the indexer, and one of the two readings deletes
  everything while printing a success line.
- **`api/tests/test_main.py` hardcoded which copilot routers exist.** It asserted `/ask`
  absent, so `routers/ask.py` broke it on arrival. It now derives the expectation from
  what is importable, which is true in a clean checkout of v0.7.0 *and* in this one, and
  will not need editing when the agent and voice routers land.

### Not in this release
- No live Anthropic call. There is no `ANTHROPIC_API_KEY` on this machine, so the hosted
  provider is asserted against a scripted client and **nothing about it is measured** --
  including prompt caching, which is declared with an ephemeral breakpoint and recorded
  on every row but never observed above zero. The provider comparison is m16.
- No streaming. The Protocol has `complete()` and `complete_structured()` and
  deliberately no `stream()`: m17's voice path is what needs it, and a Protocol method
  nobody implements makes conformance checks pass against providers that cannot do it.
- `LLM_TIMEOUT_S`, `LLM_MAX_OUTPUT_TOKENS` and `LLM_REPAIR_ATTEMPTS` are read from the
  environment but are not in `docker-compose.yml`'s `api.environment` block, so setting
  them in `.env` has no effect inside the container. The defaults (120 s, 1500, 2) are
  the effective values today.

## v0.7.0 - Hybrid retrieval over a generated corpus (2026-08-29)

The platform could answer every question that was a `GROUP BY`. It could answer none
that were prose. This adds a retrieval layer -- and, more importantly, decides what must
never go through it. **30 REST operations · 118 tests (76 existing + 42 new).**

### Added
- `GET /search` -- dense + lexical retrieval fused with Reciprocal Rank Fusion, optional
  cross-encoder rerank. `mode=dense|lexical|hybrid` and `rerank=` are query parameters
  so the m16 ablation is a set of API calls, not four code branches in a benchmark script.
  Defaults are `mode=dense, rerank=false`, and both were chosen by measurement -- see
  "Was known bad, now fixed" below.
- `eval/golden/retrieval.yaml` -- ten graded retrieval questions held OUTSIDE the corpus,
  with `api/tests/test_corpus_isolation.py` to keep them there.
- `GET /search/corpus` -- what is actually indexed, per source, with index sizes and the
  `model_matches` boolean.
- `GET /search/debug` -- `EXPLAIN (ANALYZE, BUFFERS)` for both arms.
- `doc_chunks` with pgvector: HNSW over `vector_cosine_ops`, GIN over a generated `tsv`.
- `infra/postgres/Dockerfile` -- pgvector on top of `postgis/postgis:16-3.4`.
- `embeddings` service -- BGE-small-en-v1.5 (384-dim) and BGE-reranker-base, CPU.
- `scripts/build_corpus.py`, `scripts/index_corpus.py`, and `make corpus|index|reindex`.

### The routing decision, and why it is the whole design
**"Median price per m² in Dubai Marina in 2024" must never reach a vector index.** It is
a `PERCENTILE_CONT` over an indexed column -- exact, fast, and already served by
`GET /areas/{name}/history`. Embedding it into 384 dimensions can only make it worse, and
the failure is invisible: semantic similarity over numbers returns a fluent, confident,
wrong figure with no error anywhere. So the corpus holds only what is genuinely textual:
`docs/*.md`, deterministically rendered area fact sheets, and analyst notes. Aggregates
stay in SQL. Full routing table in `docs/rag-corpus-design.md`.

Fact sheets are a **semantic view**, not "the database, embedded". Their job is to make
an area findable by a vague question ("somewhere waterfront with strong rental demand"),
not to answer a numeric one. They are templated rather than model-written, because a
generated summary would be more fluent and completely unverifiable. Each carries its
generation timestamp and the row counts it was built from.

They also inherit two traps already recorded in `models/area.py`: rent contracts are a
registration snapshot and not a time series, and `annual_amount` is the contract total
rather than the per-property rent. The sheets state the registration window, divide by
`no_of_prop`, and say in the text that rents cannot be read as a trend -- so a model
reading the chunk cannot infer one either.

### Measured
- `docs/*.md`, 11 files, 14,488 words -> **120 chunks**, 32,100 tokens, 268 average.
  Largest is 838 tokens, in `postgis-query-plans.md`. The chunker's own word-based
  estimate put that chunk at 829; 838 is what the model's tokenizer actually counted,
  which is the distinction `doc_chunks.token_count` exists to record. The docs added by
  this release are themselves in the corpus, so `make corpus-stats` is the authority and
  this number carries a date.
- **Two chunks exceed the model's 512-token limit**, both fenced `EXPLAIN` output. That
  is the chunker working as specified -- a fenced block is never split, because a
  truncated SQL statement is worse than none: it retrieves, and then it misleads. The
  dense arm sees their first 512 tokens; the lexical arm sees all of both, since `tsv`
  is generated over the full content. `index_corpus.py` warns on every run.
- **The corpus is an order of magnitude smaller than planned** -- **295 chunks** built
  and indexed (120 doc + 175 area sheets + 0 notes, from 186 documents) against an
  estimate of ~4,100. 175 of 221 areas cleared the 10-record floor; 48 were skipped.
- 27 pre-existing REST operations confirmed against the OpenAPI schema before the count
  above was written; **30 after this release**, confirmed against the running app.
- **HNSW is 3.5x faster than the sequential scan -- and the planner refuses it.**
  0.131 ms / 340 buffers against 0.464 ms / 645 buffers, warm, at 295 rows. pgvector
  prices the index descent at a startup cost of 302.21, five times the *total* cost of
  scanning and sorting the whole table (69.27), so the index sits unused until the
  corpus reaches roughly 1,500 chunks. The hypothesis in the design doc was that HNSW
  would lose outright, as GiST did over 222 polygons. It was wrong, and in an
  instructive direction: GiST was slower with an optimistic estimate, HNSW is faster
  with a pessimistic one.
- **Both indexes are larger than the table.** 456 kB table, 600 kB HNSW, 720 kB GIN,
  2,592 kB total -- the entire retrieval layer, against 561,115 rows of DLD data.
- **The cross-encoder is 99.2% of query latency.** Retrieval end to end -- embed, both
  arms, fusion -- is 67 ms p50 / 155 ms p95. With reranking it is 2,944 ms / 4,137 ms.
  The reranker costs 44x the rest of the pipeline combined, against a planned budget of
  200-400 ms, and it cannot appear anywhere in m17's 800 ms voice path.
- **Incremental re-indexing works: 0 embedded and 146 ms on an unchanged corpus**,
  1 embedded and 1,155 ms after editing one document, against 31,240 ms for a full
  rebuild. A no-op re-index is 214x cheaper than a rebuild.

### Fixed
- `build_corpus.py` embedded `datetime.now()` in every area fact sheet's text, which is
  the text `content_hash` is computed over. Every sheet therefore looked new on every
  build and all 175 were re-embedded each run -- the incremental index was not
  incremental. Generation time is provenance, not content; it now lives only in the
  record's `meta` and the `doc_chunks.generated_at` column, neither of which is hashed.
  Found by running `make index` twice, which is the only thing that could have found it.
- `build_corpus.py` ordered a window function by `EXTRACT(YEAR FROM instance_date)` while
  grouping by `EXTRACT(YEAR FROM instance_date)::int`. Postgres does not match the two
  expressions, so the year-median query failed with a `GroupingError` on the ungrouped
  column. The cast now matches the `GROUP BY`.
- `retrieval.py` passed `source_type` as a bare parameter to `$2 IS NULL OR
  source_type = $2`. asyncpg infers each parameter's type from its use site and has
  nothing to infer from there, so every unfiltered search -- the default -- failed with
  `AmbiguousParameterError`. Both arms now cast the parameter explicitly.

### Was known bad, now fixed -- and it changed two defaults
The first cut of this release could not measure its own retrieval quality.
`docs/hybrid-retrieval-plans.md` listed ten evaluation questions, that file is itself in
the corpus, and the lexical arm returned it for 8 of the 10 -- matching the questions
rather than the answers. Hybrid, the shipped default, was the worst of the three modes.

The golden set now lives in `eval/golden/retrieval.yaml`, outside `docs/` and therefore
structurally unreachable by `build_corpus.py --docs /app/docs`.
`api/tests/test_corpus_isolation.py` fails the build if any question reappears in
`doc_chunks` -- and it caught one while these results were being written up, which is the
argument for it being a test rather than a note. The design documents stay in the corpus:
they are what lets the system answer "how does this platform deduplicate rent contracts?",
and deleting them would have fixed the metric by removing the feature.

The hand-count was also wrong in the safe direction for the story and the wrong direction
for the truth: **9 of 9, not 7 of 10.** Every question still phrased as it was then had
leaked.

With the questions outside the corpus, measured on the same ten (n=10, so a strong signal
on this corpus rather than a general claim):

| Mode | top-1 ideal | recall@5 | p50 latency |
|---|---|---|---|
| **dense, no rerank** | **8/10** | **9/10** | **67 ms** |
| hybrid, no rerank | 7/10 | 9/10 | 67 ms |
| dense, rerank | 3/10 | 6/10 | 2,944 ms |
| lexical, no rerank | 3/10 | 7/10 | 67 ms |

- **`GET /search` now defaults to `mode=dense`, was `mode=hybrid`.** Hybrid never beat
  dense at any k, in any configuration, and there is no question in the set where the
  lexical arm supplied a correct document dense had missed. RRF is kept and available;
  what it has not got is evidence. Revisit when the corpus grows exact-match surface --
  identifiers, procedure numbers, error strings -- which ten prose questions do not test.
- **`GET /search` now defaults to `rerank=false`, was `rerank=true`.** The cross-encoder
  costs 2,944 ms *and* loses five of dense's eight correct top-1 answers. Checked for the
  obvious bug first: probed directly it scores a relevant document 0.2574 against 0.0000374
  for irrelevant ones, so the model and the sort direction are both fine. What it promotes
  instead is the tell -- for two questions it ranks first a chunk containing a table of
  *example questions*, one word away from the query. **A cross-encoder is drawn to text
  that resembles the question**, which is the contaminated lexical arm's failure appearing
  in the component that was supposed to be the quality layer.
- **The lexical arm returned nothing at all for 5 of the 10 questions**, which run 1 could
  not see because the contaminating document satisfied every query.
  `websearch_to_tsquery` conjoins its terms, so a natural-language question is an AND over
  4-6 stems and one missing stem empties the result. Added a relaxation: when the strict
  query matches nothing, re-run with the top-level `&` rewritten to `|`. Lexical-only
  recall@5 went 3/10 -> 7/10, and the response carries `lexical_relaxed` so a caller can
  see which query ran.
- **The relaxation is deliberately NOT used inside `mode=hybrid`**, where it dropped top-1
  from 7/10 to 5/10: the relaxed arm stops returning nothing and starts returning a
  confidently wrong document at rank 1. Same lesson as the contamination, opposite
  direction -- RRF has no notion of which arm to trust, so raising an arm's recall while
  destroying its precision@1 makes fusion worse.

### Still known bad
- **Two questions are missed by every mode**, and both are chunking problems rather than
  retrieval problems. One wants a single row of a 40-row markdown table in
  `data-model.md`; the other wants one bullet inside a 284-token chunk. m16 owns them.
- **This repository has not found a configuration in which the cross-encoder earns its
  2.9 seconds.** m16 has the levers -- truncate before scoring, cut the candidate count,
  ONNX export, or drop it -- and now a quality number to beat as well as a latency one.
- The `postgres` container runs `linux/amd64` under emulation on this arm64 host, so
  every database timing above is inflated. Plan-to-plan comparisons hold; absolute
  milliseconds are not native figures. `api` and `embeddings` are native arm64.

### Decisions
- **RRF, not weighted score blending.** Cosine similarity is bounded; `ts_rank_cd` is
  not. Any blend needs a constant that must be re-tuned whenever either side changes,
  and that constant is invisible in the output. RRF reads only ranks. `k=60` from
  Cormack et al. (2009), measured in m16 rather than inherited on faith.
- **No LangChain, no LlamaIndex, no external vector database.** The retrieval logic is
  ~300 lines of SQL and Python; a framework would hide the parts worth defending -- the
  fusion arithmetic, the chunk boundaries, the reranker cutoff. Postgres already runs and
  already holds the data; an eighth container buys a synchronisation problem.
- **The embedding layer is local and fixed; the generation layer is pluggable.** There is
  no first-party Anthropic embeddings endpoint -- Claude is a generation model.
- **`EMBEDDING_MODEL` is stored per row and asserted at query time.** Changing it makes
  every stored vector incomparable with every query vector, and nothing raises on its
  own. `/search` returns 503 with the mismatch spelled out instead of serving it.
- **The BGE query prefix lives in the embeddings service, not the callers.** Forgetting
  it costs 5-10 points of recall silently. `GET /health` publishes the exact string so a
  test asserts the live value rather than a copied constant.
- **`api/main.py` registers copilot routers by name, tolerantly.** `CLAUDE.md` §3.2
  requires a multi-PR file to land whole in the first PR, and `main.py` is touched by
  four milestones. A missing router module is a configuration state, not an error --
  `LLM_PROVIDER=none` on an 8 GB machine must still serve the map. The
  `ModuleNotFoundError` is narrowed to the router module itself, so a router that exists
  but fails to import still crashes startup instead of vanishing without explanation.
- **The `embeddings` service has no `depends_on` from `api`.** The API must start and
  serve its 27 core operations while ~1.2 GB of weights are still downloading.

### Fixed (found by the new tests, before the code ever ran)
- `estimate_tokens` counted every snake_case identifier as **one** token. It branched on
  `str.isalnum()`, which is `False` for any string containing an underscore, so
  `meter_sale_price` cost 1 instead of 4. Underestimating is the dangerous direction --
  it ends in silent truncation at the model's sequence limit.
- A single oversized prose block was emitted as one chunk regardless of size. A
  16,000-token note would have been embedded, stored, and silently truncated at 512,
  leaving everything after its first paragraph unfindable by the dense arm forever. Code
  blocks stay atomic; prose now splits on sentence boundaries, then on words.

### Operational
**Adopting this release does NOT require wiping the database.** The plan said it did, on
the grounds that `CREATE EXTENSION vector` runs only on an empty data directory. That
premise is true of `init.sql`; the conclusion does not follow. `CREATE EXTENSION` needs
the pgvector binary in the **image** and has no opinion about the age of the cluster.

    docker compose build postgres embeddings   # postgresql-16-pgvector
    docker compose up -d postgres              # recreates the container, keeps the volume
    docker compose exec postgres psql -U dubai_user -d dubai_re \
      -c "CREATE EXTENSION IF NOT EXISTS vector;"
    # then the doc_chunks DDL from init.sql -- all of it IF NOT EXISTS

Run against the live volume on 2026-08-29: 561,115 rows intact, Alembic still at `0001`,
no reload, no `make clean`. A genuinely empty volume still gets everything from
`init.sql` on first boot. Full sequence in `docs/rag-corpus-design.md` §8.

---

## v0.6.0 - The area page gets a boundary and a history (2026-08-15)

The area detail page was three stat cards. It now shows the area's own polygon and an
18-year sales history. **27 REST operations · 76 tests.**

### Added
- `GET /areas/{area_name}/history` -- yearly median price per m², median price and sale
  counts, plus rent counts and median rent, with `is_partial` per period.
- `?name=` on `GET /communities/geojson`, so a detail page fetches one polygon instead
  of all 222. A single polygon is ~92 vertices, so it is requested at `simplify=0`:
  simplification exists to shrink the 222-polygon payload and buys nothing for one.
- `AreaPolygonMap` -- the boundary on a basemap, fitted to its own extent.
- `AreaHistoryChart` -- two small multiples (price line, volume bars), no dependency added.

### The chart decisions, and why
- **Two charts, not one dual-axis chart.** Price and volume have different units; two
  y-scales let you manufacture whatever correlation you want by choosing the scales.
- **Median (`PERCENTILE_CONT`), not mean.** One area carries a single AED 6.75 bn
  transaction; a yearly mean charts outliers.
- **The incomplete year is marked, not dropped.** Data stops mid-February, so the current
  year's counts sit far below a full year and read as a crash. It renders with a dashed
  line segment and a pale bar. `is_partial` is computed by comparing the period end against
  the last date actually present, not hardcoded.
- **Rents are deliberately NOT plotted.** Every contract in the export was *registered*
  between 2026-01-01 and 2026-08-14 -- it is a snapshot of active contracts, not a history.
  Plotting counts by `contract_start_date` draws a fake 20x hockey stick (650 in 2019,
  34,123 in 2025, 320,400 in 2026), because early years hold only the few long-running
  contracts still active at export time. The API exposes `rents_are_historical`, computed
  from the number of distinct registration years, so it flips on its own if a future load
  really does span several. There is even a contract with a 1925 start date.
- Palette validated against the actual `#ffffff` card surface rather than assumed.

### Fixed
- **The boundary map rendered as a blank white box.** `maplibre-gl.css` sets
  `.maplibregl-map { position: relative }`, which lands after Tailwind in the cascade and
  silently beats an `absolute` utility class -- the container then had nothing to resolve
  `inset-0` against and collapsed to `height: 0` while its canvas reported 990x300. No
  error anywhere. Fixed with inline positioning styles, which is why `DeckMap.tsx` has
  always done it that way. `map.resize()` on load alone did **not** fix it; the container
  was the problem, not the canvas.
- Chart tooltip no longer covers the caption or the most recent years -- it offsets below
  the title and flips to the side the cursor is not on.

## v0.5.0 - Rents and valuations loaded; the platform becomes cross-dataset (2026-08-15)

`raw_rent_contracts` and `raw_valuations` had been **empty since the project started**, which
meant rental yield -- the headline analytic -- was not computable, 3 of the 4 Spark jobs in
`processing_pipeline` would have produced nothing, and 2 Airflow quality checks failed. The
files were finally exported from the DLD portal. They did not fit.

### The portal export is a different schema wearing the same name
`ingest.py` was built for the DLD **bulk** open-data files. The portal's interactive export is
a different dialect: UPPERCASE abbreviated headers (`AREA_EN` not `area_name_en`, `TRANS_VALUE`
not `actual_worth`), a UTF-8 **BOM** on the first header, no `area_id` anywhere, and -- for
rents -- **no contract identifier at all**. Added `scripts/load_portal_exports.py` rather than
teaching `ingest.py` two dialects and risking the bulk path the suite covers.

### Added
- `scripts/load_portal_exports.py` -- maps the portal dialect onto the existing tables with the
  same `ON CONFLICT DO NOTHING` semantics.
- **358,008 rent contracts** and **3,106 valuations** loaded.

### The synthetic rent key
`raw_rent_contracts` is `(contract_id, line_number)` NOT NULL UNIQUE and the export has neither.
Dropping the constraint was the easy fix and the wrong one -- it is what makes re-ingestion
idempotent. The key is instead **derived**: `md5` over the columns that identify a contract in
the real world, with `line_number` disambiguating genuinely identical rows. Verified: a second
run over the same files inserts **0** rows, all 361,126 absorbed by `ON CONFLICT`. The honest
limitation is that an amended row upstream hashes differently and lands as a new row -- a derived
key cannot track an update it was never given an identifier for.

### Measured
- **Valuations carry 12 duplicate `(procedure_number, instance_date)` pairs**, which is exactly
  the table's unique constraint: 3,118 read, **3,106** inserted, 12 absorbed.
- **`annual_amount` is the CONTRACT total, not the per-property rent**, and one contract can
  cover hundreds of properties -- each getting its own row carrying the full portfolio amount.
  The row counts prove it: `no_of_prop=232` appears exactly **232** times, `no_of_prop=205`
  appears **410** times (2 portfolios), `no_of_prop=408` appears **1,224** (3 portfolios).
  Dividing by `no_of_prop` moved gross yields from an impossible **208%** to a credible
  **7.6-9.9%** (Burj Khalifa 7.78%: AED 2.93M avg sale against AED 227,852 avg rent).
  **Any yield computed off raw `annual_amount` is wrong.**
- Airflow `quality_checks`: **13 pass / 4 warn / 0 fail**, from 13/2/2. The 2 failures are gone;
  the new warn is `cross_dataset_coverage` at 42% (94 shared areas), because the rents export
  covers only **96** areas against the transactions' 221.
- Area vocabulary overlap with the existing transactions: rents **94/96**, valuations **177/184**.
- `/areas` now returns **229** rows -- the FULL OUTER JOIN surfaces areas present only in rents
  or valuations.

### Not loaded, deliberately
`transactions-2026-08-15.csv` (134,150 rows) was **not** ingested. `TRANSACTION_NUMBER` is not
unique (the first two rows share `101-10-2026`), it has no `area_id` and no `meter_sale_price`,
and it uses a different transliteration -- only **76 of its 176** area names appear in the
existing data (`AL BARSHAA SOUTH THIRD` vs `AL BARSHA SOUTH THIRD`). The loaded 200k slice of
the 1.02 GB bulk file is richer and larger; merging this would have degraded it.

## v0.4.0 - The polygons become visible (2026-08-15)

Until now the 222 community polygons did real work in Postgres -- point-in-polygon
containment, radius search, adjacency, overlap, dissolve -- and **nothing rendered them**.
Every endpoint reduced geometry to a derived scalar before it left the database
(`ST_Centroid` for a map pin, `ST_Area` for a number); there was no `ST_AsGeoJSON`
anywhere in the API, and the deck.gl map had only `ScatterplotLayer`, `HeatmapLayer`
and `HexagonLayer`. The map drew dots on top of boundary data it never showed.

### Fixed (data-quality, found by rendering the data)
- **`/areas` emitted duplicate names.** `Mushrif` exists under **two different `area_id`s**
  (404 with 33 transactions, 420 with 1), and the list grouped by `(area_id, area_name_en)` --
  223 rows for 222 distinct names, which React rejected with a duplicate-key error. Both cards
  linked to the same `/areas/Mushrif`, which aggregates by name and already showed the combined
  34, so the list was contradicting the detail page. Now one row per normalised name.
- **Latent fan-out in the same query.** The `FULL OUTER JOIN`s matched on name while the
  subqueries grouped by `(area_id, area_name_en)`. Harmless only because rents and valuations
  are empty; the moment they load, a name with two ids on both sides is a cartesian product.
- **`Al Qusais` and `AL QUSAIS` were two rows for one place** (69 transactions). Normalising the
  group key merges them -- so there are **221 distinct areas, not 222**. The 222 in the
  transaction data counts *spellings*; the 222 in `communities` counts *polygons*. They are
  unrelated numbers that happen to be equal.
- **`/areas/{name}/summary` matched case-sensitively**, returning HTTP 200 with every count
  zeroed for `AL MANARA` while `Al Manara` returned 128 transactions. The map's boundary layer
  clicked through with the polygon's spelling and opened an empty detail panel with no error
  anywhere. Now normalised on both sides, and `/communities/geojson` carries `txn_area_name`
  so a client never has to guess the transaction-side spelling.
- 4 more tests (**68 total**).

### Added
- `GET /communities/geojson` -- the boundaries as a real GeoJSON `FeatureCollection`,
  consumable directly by deck.gl, Leaflet or QGIS. Optional `simplify` tolerance and
  `with_stats` join for choropleth fills. **26 REST operations** (was 25).
- **Boundaries view mode** on the map: a `GeoJsonLayer` choropleth shaded by average
  price per m², with its own legend and hover card.
- `docs/polygon-simplification.md` -- what simplification buys and what it silently breaks.
- 6 new tests (**64 total**, all passing).

### Measured
- Full fidelity: **1,012,960 bytes / 34,326 vertices**; heaviest single polygon 2,247.
- Simplified to 0.0001 deg (~10 m): **193,887 bytes / 4,900 vertices**. Geometry alone
  963,041 -> 144,093 bytes, **6.7x**. All 222 features survive.
- **Simplification breaks shared borders.** Re-running the DE-9IM pair counts: at ~10 m,
  **176 of the 483 touching pairs (36%) migrate from `ST_Touches` to `ST_Overlaps`** --
  each side of a shared edge is decimated independently, so boundaries that met exactly
  now cross. `ST_Intersects` holds at 614, so adjacency is still complete, only mislabelled.
  At 0.0005 deg `ST_Intersects` falls to **606**: 8 neighbour relationships vanish outright.
- Rule adopted: **simplify for display, never for analysis.** Every adjacency, area and
  overlap endpoint reads the unsimplified `geom`, and `area_km2` in the GeoJSON response is
  computed from the original geometry even when the geometry beside it is simplified.
  A test asserts those areas are identical across tolerances.
- Only **106 of the 222** communities match a transaction area name, so they render grey
  rather than as the cheapest bucket. An unmatched polygon is missing data, not a zero.

### Fixed
- **A bind parameter silently disabled simplification.** `CASE WHEN :tol > 0 THEN
  ST_SimplifyPreserveTopology(geom, :tol)` -- Postgres infers a parameter's type from its
  *first* use, so an uncast `:tol > 0` inferred `integer`, `0.0001` arrived as `0`, and
  every request took the `ELSE` branch while the response still echoed
  `simplify_tolerance_deg: 0.0001`. Fixed with explicit `CAST(:tol AS double precision)`
  at both sites. The regression test asserts on the **vertex count**, not the echoed
  tolerance, which was correct the whole time. Same silent-failure shape as Spark's
  `to_date()` returning NULL on a format mismatch and `geom <-> point` ordering in degrees.
- Map legend no longer reports "Transaction Volume / Click hexagon" while in Boundaries mode.

## v0.3.0 - PostGIS geometry and an ORM write path (2026-08-15)

### Added
- **PostGIS 3.4** — image swapped from `postgres:16-alpine` (which has no PostGIS
  available at all) to `postgis/postgis:16-3.4`; `CREATE EXTENSION postgis` in `init.sql`
- `communities` table holding 222 Dubai community polygons, with a GiST index on `geom`
  and a functional GiST index on `(geom::geography)` for metre-accurate KNN ordering
- `scripts/load_communities.py` — loads the DLD `Community.kml` export without requiring
  GDAL; attributes are parsed out of the ArcGIS description CDATA
- Spatial endpoints: `GET /communities`, `/communities/contains` (`ST_Contains`),
  `/communities/nearby` (`ST_DWithin`), `/communities/{id}/transactions`
- ORM write path: `db_models/` with SQLAlchemy 2.0 typed declarative models
  (`AreaNote` → `NoteTag`) and optimistic locking via `version_id_col`
- `GET/POST/PUT/PATCH/DELETE /notes` with `If-Match`/`ETag` concurrency control
- **Alembic** migrations for the ORM-managed tables, with `include_object` so
  autogenerate never touches the tables owned by `init.sql`
- `SQL_ECHO=1` toggle for demonstrating query counts
- 22 new tests (49 total, all passing)
- `docs/postgis-query-plans.md`, `docs/n-plus-one-demo.md`

### Changed
- **Removed the hardcoded `AREA_COORDS` dictionary** — 70 hand-typed approximate
  centroids, two pairs of which collided across distinct areas (Marsa Dubai/Dubai Marina,
  Burj Khalifa/Downtown Dubai). Map coordinates are now derived with `ST_Centroid` over
  real polygons: 70 areas → 299 map features, and 75.8% of transactions (151,602/200,000)
  join to a real geometry.
- `database.py` uses `async_sessionmaker` rather than the 1.4-era
  `sessionmaker(class_=AsyncSession)`

### Fixed
- `MissingGreenlet` on PATCH: `onupdate=func.now()` expires `updated_at` after an UPDATE,
  and serialising the object triggered implicit lazy IO, which async SQLAlchemy forbids.
  Writes now re-select with `populate_existing=True`.
- `/communities/nearby` ordered by the geometry `<->` operator, which sorts by planar
  degrees rather than metres and returned results out of order at Dubai's latitude.
  Both sides of the operator are now cast to `geography`.
- One community polygon had a ring self-intersection; repaired with `ST_MakeValid`
  wrapped in `ST_CollectionExtract(..., 3)`.

## v0.1.0 - Foundation (2026-03-07)

### Added
- Docker Compose with PostgreSQL 16 service, health check, named volume and network
- Database schema for 3 DLD datasets: raw_transactions, raw_rent_contracts, raw_valuations
- Analytics table (area_trends) and ingestion tracking (upload_log)
- Ingestion script with CSV auto-detection, null normalization, and deduplication
- Seed profile container for loading data from raw_source/
- Makefile with docker compose wrappers
- Project documentation: architecture, data model
