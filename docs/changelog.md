# Changelog

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
