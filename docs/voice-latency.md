# The 800 ms budget, measured

> **On how this document is written.** The spoken test utterance is question **A-01 /
> R-01** and it is referred to by id, never quoted. This file is inside the retrieval
> corpus and inside the corpus the answer fixtures are checked against; writing the
> sentence here would put an eval question into the data it grades, which
> `test_no_answer_question_appears_verbatim_in_the_corpus` exists to prevent and which
> m13a paid for once already.

---

## 1. The answer, first

**A complete spoken turn takes 3.0–3.3 seconds to first audio against an 800 ms budget.
That is 3.8–4.1× over.**

The plan predicted ~1,320 ms and called it over budget. The real figure is roughly 2.4×
worse than the pessimistic prediction, and the reason is not the speech stack:

| | measured | share of time-to-first-audio |
|---|---|---|
| the three stages m17 built (VAD + STT + TTS) | ~0.8–1.0 s | ~28% |
| the two it inherited (retrieval + generation) | ~2.3 s | ~72% |
| **generation alone** | **2.04–2.16 s** | **~65%** |

**The voice interface is not what breaks the budget.** A 20B model generating a sentence
is. Everything m17 added would fit inside 800 ms on an idle machine — and does not on a
busy one, which is the second finding.

---

## 2. What was built

```
infra/voice/                820 MB, and NO torch anywhere in it
  POST /vad                 webrtcvad-wheels, endpointing
  POST /stt                 faster-whisper base.en int8 (CTranslate2)
  POST /tts                 Piper, ONNX Runtime
api/routers/voice.py
  POST /voice/turn          the MEASUREMENT path — raw PCM in, every stage timed
  WS   /voice/stream        the INTERACTIVE path — frames up, events and audio down
  GET  /voice/budget        targets, last measurements, computed verdict
```

Two design choices are worth defending before the numbers.

**`POST /voice/turn` exists because a WebSocket cannot be measured with `curl`.** Every
figure below comes from it. A number nobody can reproduce from a shell is a number that
quietly rots, and this project has a standing rule that claims are counted rather than
recalled.

**`GET /voice/budget` returns the budget as data.** §7.2 states the target in prose and
concludes the pipeline misses it. That conclusion was right and prose is the wrong place
for it — nothing checks a paragraph. The endpoint computes the verdict from whatever last
ran, and a stage that has never run reports `null` rather than `0`, because "instant" and
"unmeasured" are different facts.

`api/main.py` was not touched. `voice` has been in `COPILOT_ROUTERS` since m13 and the
tolerant loop found it by name — the third time that design has paid off, after `ask` in
m14 and `agent` in m15. 38 → **40 REST operations**, 314 → **340 tests**.

---

## 3. Stage by stage

Five runs of `POST /voice/turn`, `route=ask`, host load ~18.

| stage | target | measured | verdict |
|---|---|---|---|
| VAD (round trip + compute) | 200 ms | **1.4–2.4 ms** | ✅ 100× inside |
| STT | 250 ms | **387–431 ms** | ❌ ~1.6× over |
| retrieval | 320 ms | **186–255 ms** | ✅ inside |
| generation | 400 ms | **2,043–2,157 ms** | ❌ **5.2× over** |
| TTS to first audio | 150 ms | **353–560 ms** | ❌ 2.4–3.7× over |
| **to first audio** | **800 ms** | **3,025–3,318 ms** | ❌ **3.8–4.1× over** |

Time-to-first-audio **excludes** the VAD stage. The budget clock starts when the speaker
stops, and endpoint detection is what decides that they have — counting it would charge the
pipeline for the moment it is measuring from.

### 3.1 The 200 ms VAD budget is not a cost. It is a decision.

§7.2 lists VAD at 200 ms alongside four stages that are compute, which invites the reader
to treat it as something to optimise. **It is not.** Endpoint detection over four seconds of
audio costs **0.35–0.52 ms**. The 200 ms is the *trailing-silence threshold* — time spent
deliberately waiting to be sure the speaker has finished.

That distinction is worth the paragraph, because the two behave in opposite ways. Compute
gets cheaper with better engineering. A waiting threshold trades against a failure mode:
shorten it and the turn starts sooner but clips a speaker who pauses mid-sentence, which
costs an entire extra turn rather than 100 ms.

The endpointer reports where silence **began**, not where the threshold confirmed it, so
the threshold cannot flatter its own measurement:

| threshold | endpoint reported | compute |
|---|---|---|
| 100 ms | 3,340 ms | 0.52 ms |
| 200 ms | 3,340 ms | 0.51 ms |
| 400 ms | 3,340 ms | 0.45 ms |
| 800 ms | **none** | 0.47 ms |

Stable across the first three, exactly as designed. At 800 ms it returns nothing — the clip
carries only 600 ms of trailing silence, so a threshold longer than the available pause
means the turn never fires at all. That is the failure mode made concrete: **the endpointing
lever is bounded by how long the speaker actually stops for**, not by how fast the detector
is.

### 3.2 Beam search buys nothing here and costs 20–60 ms

`faster-whisper` defaults to `beam_size=5`. Measured on the same clip, warm:

| beam | took | transcript |
|---|---|---|
| 1 (greedy) | 329, 331, 352 ms | correct, verbatim |
| 5 (library default) | 346, 346, 412 ms | **identical** |

The voice path defaults to greedy. It stays a parameter so the trade can be re-measured on
harder input rather than assumed to hold.

### 3.3 The quality/latency trade in TTS does not exist on this stack

§7.2 assumes a smaller model is a faster one. Measured back to back at the same host load:

| voice | first audio | sample rate |
|---|---|---|
| `en_US-lessac-medium` | 122, 174, 201 ms | 22,050 Hz |
| `en_US-lessac-low` | 136, 195, 196 ms | 16,000 Hz |

**The low-quality voice is not faster.** There is therefore no latency argument for taking
the quality hit, and the default stays `medium`. The only thing `low` offers is that it
emits 16 kHz, matching the input rate — and resampling in an interactive path to satisfy a
symmetry nothing needs is not a trade worth making, so the output rate is reported in a
header instead.

---

## 4. The finding that keeps reappearing: host load moves everything

The same TTS call, same text, same warm model, same code:

| host load | first audio |
|---|---|
| ~7.8 | 122–201 ms |
| ~17 | **499–673 ms** |

**3–4× on load alone.** And the pipeline is not the cause — measured *directly* against the
voice service at load ~17, TTS is 499–673 ms while the same stage measured *inside* the
pipeline is 353–560 ms. The pipeline is, if anything, marginally faster; the machine is
just busy.

This is the fourth independent reproduction of the same effect in this project:

| | measured |
|---|---|
| M-21 (m14) | generation p50 7,914 / 19,681 / 20,927 ms across three identical runs |
| M-35 (m15) | 87 s vs 144 s for the same 14 questions at load 5.03 vs 7.80 |
| M-48 (m16) | 520 s vs 706 s for the same 40 questions |
| here | TTS 122–201 ms vs 499–673 ms, same call |

It has a consequence for the headline. **At load ~7.8 the three stages m17 built come to
roughly 480 ms — comfortably inside 800 ms with room to spare. At load ~18 they come to
roughly 850 ms and do not.** Even the part of the budget that could fit is only reliably
inside it on an idle machine.

Every figure in this document therefore carries the load it was taken at, and no figure
here should be compared with one that does not.

---

## 5. The agent route, measured rather than argued

The handoff's standing rule is that a multi-step agent run does not belong in an
interactive path. `route=agent` exists so the cost can be measured instead of asserted.

| route | to first audio |
|---|---|
| `ask` (5 runs, load ~18) | 3,025–3,318 ms |
| `agent` (2 runs, load ~12) | 3,220 ms and **4,557 ms** |

On A-01 — the easiest question in the set, one or two tool calls — the agent is *roughly
comparable*. That is not a reprieve, and the reason is the distribution rather than the
median: M-48 measured agent runs across 40 questions at **1.4 to 58.6 seconds**. A path
whose best case matches `ask` and whose worst case is a minute cannot be the interactive
one. The rule stands, and now it stands on a number.

---

## 6. The three levers from §7.2, honestly scored

**1. Overlap, don't serialise. — PARTIAL, and the remaining half is small.** Retrieval can
start on a partial transcript. Measured, retrieval is 186–255 ms of a 3,000 ms turn, so
perfectly overlapping it saves at most 8%. The lever the plan expected to be large is small,
because the stage it overlaps turned out to be cheap.

**2. Skip the reranker. — DONE, and it was not a sacrifice.** §7.2 framed this as buying
287 ms at some cost in ranking quality. m16 measured the quality: the cross-encoder scores
**8/20** at top-1 against dense's **17/20** on the golden set, while costing 2.9 s. It loses
on both axes. Skipping it is free, and that is only knowable because the ablation was run —
without it this would have been a defensible-sounding sacrifice that was actually a
straight win.

**3. Speak the first sentence early. — PARTIAL, and the limit is structural.** The opening
sentence is split and synthesised first, which is real. The larger half — beginning
synthesis while the model is still generating — needs token streaming out of the generation
layer, and m15 deliberately did not build SSE because nothing consumed it. Against 2.0–2.2 s
of generation, that unbuilt half is worth more than both other levers combined.

**Scored honestly, the three levers are worth roughly 8%, 0% (already taken), and an
unbuilt amount that would matter. §7.2 projected they would take ~1,320 ms down to
600–700 ms. From a real 3,000 ms they would not.**

---

## 7. Two bugs found by running it, not by reading it

**The WebSocket protocol was a lie.** `/voice/stream` documents a binary audio frame after
the answer and sent none: the pipeline kept only the *length* of the synthesised audio,
which was enough for the JSON measurement endpoint and left the socket silent. A client
would have received a correct transcript, a correct answer, correct timings — and nothing to
play. Found by connecting a real client and counting frames. It now streams 338 frames /
297 kB in the same 20 ms framing the client sends, and a test asserts the frame count so
the docstring cannot drift from the code again.

**The router contract test had an untested premise.** `test_every_copilot_router_...`
asserted that every route a copilot router declares appears in `app.openapi()["paths"]`.
That held for four milestones and broke on the project's first WebSocket, which FastAPI
correctly excludes from the schema — a socket is not an operation with a method and a
response model. The test now checks HTTP routes against the schema and WebSocket routes
against the mounted app: absent from the schema is expected, absent from the app is not.

Both belong to the same family as m16's finding that its own CI workflow had never run. A
claim nobody has executed is not a claim.

---

## 8. Known gaps, stated rather than fixed

- **No browser client.** Endpointing runs server-side on the accumulated buffer, one call
  per chunk. A browser endpointing locally would save a round trip per chunk — but VAD
  compute is 0.35 ms, so the saving is transport, not computation, and there is no client
  to put it in. This is the same open question §8.3 of the plan raises about the whole
  system: there is still no user interface.
- **No streaming generation.** The single largest available win, and it needs the SSE layer
  m15 declined to build. Until it exists, time-to-first-audio has a 2-second floor.
- **Opus is not implemented.** §7.1 specifies 20 ms Opus frames; the transport carries raw
  PCM at 20 ms framing. Opus would cut bandwidth roughly 10× and adds an encode/decode step
  to a path that is 3 seconds long — bandwidth is not what is wrong here.
- **One utterance, one speaker, one machine.** Every figure is A-01 spoken by Piper into
  Whisper. A synthetic voice is cleaner than a real one, so the STT numbers are an
  optimistic bound and are not a claim about a human in a room.
- **Three environment variables are not forwarded by compose.** `PIPER_VOICE`,
  `WHISPER_COMPUTE` and `VOICE_BUDGET_MS` are read by the code and absent from
  `docker-compose.yml`, so setting them in `.env` does nothing — the m14 gap, recurring.
  The file is claimed by an earlier uncommitted milestone and the edit is deferred rather
  than made; see §A.5 of the command sheet. The defaults are the operative values today.
