# The retrieval corpus — what goes in it, and what must never go in it

Written 2026-08-29 · pgvector 0.8.6 on PostGIS 3.4.3 / PostgreSQL 16.15 · BGE-small-en-v1.5 (384-dim)

This platform holds 561,115 rows of transactions, rent contracts and valuations in
typed Postgres columns with indexes on them. Putting a retrieval layer on top of that
raises one question before any other: **what is actually worth embedding?**

The answer is: very little of it. That is the whole design.

---

## 1. The routing rule

> **"What was the median price per m² in Dubai Marina in 2024?" must never go to a
> vector index.**

It is a `PERCENTILE_CONT` over an indexed column. It is exact, it is fast, and it is
already served by `GET /areas/{name}/history`. Embedding it into a 384-dimensional
space can only make it worse, and the failure is invisible: semantic similarity over
numbers returns a fluent, confident, wrong figure with no error anywhere in the stack.

So the copilot routes *before* it retrieves.

| Question shape | Path | Example |
|---|---|---|
| Aggregate over rows | **SQL** | "Median price per m² in Marina, 2024" |
| Spatial | **PostGIS** | "Which communities border Business Bay?" |
| Definitional / methodological | **RAG** | "How does this platform deduplicate rent contracts?" |
| Qualitative, analyst-authored | **RAG** | "What have we noted about Al Qusais?" |
| Mixed | **Agent: both, then compose** | "Is Marina a better yield than JVC, and how is yield computed here?" |

The tool layer that makes the first two columns real is m15. `GET /search` (m13) serves
only the third and fourth.

---

## 2. Three sources

### Source 1 — the engineering corpus

`docs/*.md`. Small, but it is real prose about real decisions, and it answers "how does
this system work" questions that no SQL query can.

Note the self-reference: this file and `hybrid-retrieval-plans.md` are themselves in the
corpus. Documenting the retrieval layer grows the thing it retrieves from, which is why
`make corpus-stats` is the authority and the table below is a snapshot with a date on it.
There is no fixed point to chase here: editing this paragraph moves its own row.

**Measured 2026-08-29, after indexing**: 11 files, 16,435 words, **128 chunks**.
Token counts below are the embedding model's own tokenizer as stored in
`doc_chunks.token_count` — not the chunker's cheaper word-based estimate, which is what
it uses to *pick* boundaries. The two differ, and the column records what actually
happened.

| File | Words | Chunks | Largest chunk (tokens) |
|---|---|---|---|
| `architecture.md` | 271 | 5 | 216 |
| `changelog.md` | 3,721 | 30 | 455 |
| `concurrent-inserts.md` | 1,779 | 13 | 469 |
| `data-model.md` | 601 | 8 | 381 |
| `hybrid-retrieval-plans.md` | 2,541 | 16 | 446 |
| `n-plus-one-demo.md` | 200 | 2 | 275 |
| `pandas-vs-pyspark.md` | 1,320 | 8 | 430 |
| `polygon-adjacency-plans.md` | 1,726 | 14 | 512 |
| `polygon-simplification.md` | 981 | 7 | 436 |
| `postgis-query-plans.md` | 697 | 7 | **838** |
| `rag-corpus-design.md` | 2,598 | 18 | 447 |

Compare against the same table taken before these results were written up: 14,488 words
and 120 chunks. The two files documenting the retrieval layer grew by 1,947 words between
those measurements, which is the self-reference in §2 doing exactly what it says.

Two chunks exceed the model's 512-token sequence limit, both in
`postgis-query-plans.md`, and both are fenced `EXPLAIN (ANALYZE, BUFFERS)` output. That
is the chunker working as specified rather than a bug: **a fenced block is never split**,
because a truncated SQL statement is worse than no SQL statement — it retrieves, and
then it misleads. The consequences are stated rather than hidden:

- The dense arm sees only the first 512 tokens of those two chunks.
- The lexical arm sees all of both, because `tsv` is generated over the full `content`.
- `scripts/index_corpus.py` prints a `WARNING: truncated` line for each, every run.

This is one of the concrete arguments for hybrid retrieval in this repository rather
than in general: the two arms have different failure modes, and here they cover for
each other.

### Source 2 — area fact sheets, generated deterministically

One templated paragraph per area, rendered by `scripts/build_corpus.py` from aggregates
the platform already computes:

> **Dubai Marina.** 18,432 recorded sales between 2011 and 2026. Median price per m² in
> 2025 was AED 18,940 across 2,104 sales, up 12.3% from AED 16,865 in 2024. 62% of sales
> are existing property and 38% off-plan. 4,120 rent contracts on record, registered
> between 2026-01-01 and 2026-08-14, median annual rent per property AED 105,000. Rent
> figures are a point-in-time snapshot of registered contracts, not a time series, and
> cannot be read as a rental trend. Shares a boundary with Al Thanyah Fifth, …

**This is not "RAG over the database", and the distinction is the whole point.**

A fact sheet is a *semantic view*: a stable, templated text surface whose job is to make
an area **findable** by a vague question — "somewhere waterfront with strong rental
demand" matches no column in any table. The numbers inside it exist to ground and to
cite. When the user asks for a figure, the agent calls the SQL tool and quotes *that*.

Three properties keep it honest:

- **Templated, never model-written.** A generated summary would be more fluent and
  completely unverifiable: there would be no way to say whether a sentence came from the
  data or from the model. Every number traces to one aggregate in one query.
- **Carries its provenance — outside the hashed text.** The generation timestamp lives
  in the corpus record's `meta` and in `doc_chunks.generated_at`; the chunk row stores the
  row counts the sheet was built from. Staleness is detectable, not assumed.
  It is deliberately **not** in the sheet's text: `content_hash` is a sha256 over exactly
  that text, so a timestamp inside it made all 175 sheets look new on every build and the
  incremental index re-embedded the entire corpus each run. Provenance belongs next to the
  content, not inside it. Measured before and after in `hybrid-retrieval-plans.md` §5.
- **Refuses to imply a trend it does not have.** See §3.

Areas with fewer than 10 combined records are skipped. A sheet reading "1 recorded sale,
no median" retrieves for everything and grounds nothing.

### Source 3 — analyst notes

The `area_notes` table, already served by the ORM write path with ETag concurrency.
Genuinely unstructured, genuinely human-authored, and it grows. Tags are folded into the
indexed text because short identity strings (`off-plan`, `yield-watch`) are exactly what
the lexical arm is good at and the dense arm is not.

`area_notes` is created by Alembic, not `init.sql`. After a volume rebuild it does not
exist until `alembic upgrade head` runs, and `build_corpus.py` treats that as a
migration state rather than a corpus failure.

---

## 3. Two data traps the fact sheets have to respect

Both were found the hard way and are already recorded in `models/area.py`. A corpus
that ignores them would publish the same wrong number in a more persuasive format.

**Rent contracts are a snapshot, not a time series.** Every contract in the DLD portal
export was *registered* inside one window. The spread of `contract_start_date` makes it
look historical and it is not — plotting it produces a fake 20× hockey stick, because
early years hold only the long-running contracts still active at export time. The sheets
state a registration window, never a rent trend, and say so in the text so a model
reading the chunk cannot infer one either.

**`annual_amount` is the contract total, not the per-property rent.** One contract can
cover hundreds of properties, each carrying the full portfolio amount on its own row.
The median divides by `no_of_prop`; the raw column produces gross yields above 200%.

---

## 4. Chunking

One strategy per source, because one strategy for all three is wrong for all three.

| Source | Strategy | Why |
|---|---|---|
| `docs/*.md` | Structure-aware split on `##`/`###`, 512-token target, 64-token overlap, heading path prepended | Markdown already carries semantic boundaries the author wrote down. Splitting on character count throws them away. |
| Fact sheets | One chunk per area, never split | ~120 tokens and internally coherent. Splitting separates the area's name from its numbers — the worst possible cut. |
| `area_notes` | One chunk per note, split only above 512 tokens | Notes are authored as units. |

**Heading paths are prepended to the embedded text.** `changelog.md > v0.5.0 > The
synthetic rent key` costs nine tokens and restores the one thing a mid-document chunk
has lost: its position. Without it, a chunk reading "the key is `(contract_id,
line_number)`" is about nothing in particular.

The hash covers the heading path as well as the body. Restructuring a document changes
what a chunk *means* without changing a word of it; hashing the body alone would leave
those vectors stale and undetectable.

**Overlap applies only between continuation chunks of the same section**, never across a
heading. Across a heading, the heading path already carries the context that overlap
exists to restore, and duplicating a section's opening lines into the previous section
makes both retrievable for the wrong query.

### Token counting, twice, on purpose

`estimate_tokens()` is a word-piece approximation used to pick boundaries — cheap, no
tokenizer, no network. The count actually stored in `doc_chunks.token_count` comes back
from the embeddings service, which has the real tokenizer. The estimator is deliberately
conservative on identifiers (`meter_sale_price` costs 4, not 1) because the dangerous
direction of error is underestimating, which ends in silent truncation.

That asymmetry is not hypothetical: the first version of the estimator branched on
`str.isalnum()`, which is `False` for any string containing an underscore, and counted
every snake_case identifier in the corpus as a single token. A unit test caught it.

---

## 5. Embeddings

`BAAI/bge-small-en-v1.5`, 384 dimensions, CPU, in a dedicated service.

Chosen over `all-MiniLM-L6-v2` (same dimensionality, measurably weaker on retrieval
benchmarks) and over `bge-base` (768-dim, ~3× the index size and inference cost, for a
margin that will not show at this corpus size).

**There is no first-party Anthropic embeddings endpoint.** Claude is a generation model.
That produces a split worth stating plainly: *the embedding layer is local and fixed;
the generation layer is pluggable.*

The practical consequence is operational. Changing `EMBEDDING_MODEL` invalidates every
stored vector, and nothing raises: query vectors from model B get compared against
document vectors from model A, every cosine distance becomes meaningless, and `/search`
keeps returning five confident results. So the model name is written into every row and
asserted at query time — `/search` returns **503 with the mismatch spelled out** rather
than serving it, and `/search/corpus` reports `model_matches`.

**The BGE asymmetric prefix lives in the service, not in the callers.** Queries are
embedded with `Represent this sentence for searching relevant passages: `; documents are
not. Getting it backwards, or forgetting it, costs 5–10 points of recall with no error
anywhere. One place to get it right, and `GET /health` publishes the exact string so a
test can assert on the live value instead of a constant copied into three files.

A separate container rather than importing torch into the API image: it keeps ~900 MB
out of the API, loads the weights once into a named volume, and — the part that matters
operationally — lets the API start and serve its 27 core operations while the embedder
is still downloading. There is deliberately **no `depends_on`**.

---

## 6. Storage and hybrid retrieval

```sql
CREATE TABLE doc_chunks (
    id BIGSERIAL PRIMARY KEY,
    source_type VARCHAR(20), source_id VARCHAR(200), chunk_index INT,
    heading_path TEXT, content TEXT, content_hash CHAR(64), token_count INT,
    embedding_model VARCHAR(80), embedding vector(384),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(heading_path, '') || ' ' || content)
    ) STORED,
    generated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source_type, source_id, content_hash)
);
```

Three stages:

1. **Dense** — cosine KNN over `embedding`, top 20. `ORDER BY embedding <=> $1`, on the
   raw distance operator. Ordering by the derived `1 - (embedding <=> $1)` DESC is
   mathematically identical and silently drops HNSW for a sequential scan.
2. **Lexical** — `ts_rank_cd` over `tsv`, top 20, via `websearch_to_tsquery`. Not
   decoration: `meter_sale_price`, `CNT` contract prefixes, `v0.5.0` and `Al Thanyah
   Fifth` are *identity* tokens — they denote rather than mean, which is exactly the
   class of string a semantic embedding smears together.
3. **Fusion** — Reciprocal Rank Fusion, `score = Σ 1/(k + rank_i)`, `k = 60`.

RRF over score normalisation, deliberately. Cosine similarity lives in [0, 1];
`ts_rank_cd` is an unbounded relevance mass. Any weighted blend of the two needs a
constant that has to be re-tuned whenever either side changes, and that constant is
invisible in the output. RRF consumes only ranks: one parameter, no calibration, no
scale to drift. `k = 60` is the value from Cormack et al. (2009), inherited as a
starting point and measured in m16 rather than taken on faith.

### Reranking

`BAAI/bge-reranker-base`, a cross-encoder, over the fused candidates, returning 5.

A bi-encoder embeds query and document independently, so it can never model interaction
between them — which is also what makes it indexable. A cross-encoder reads both
together and is far more accurate, and far too slow to run over a corpus. Reranking the
top 20 is the standard resolution, at roughly 200–400 ms on CPU.

**Whether it earns that latency is an open question, not an assumption.** m16 measures
nDCG@5 with and without it. If the metric does not move, the stage gets deleted and the
result gets written up. This repository already contains three negative findings; a
fourth is not a failure.

---

## 7. The corpus is smaller than planned, and that matters

The implementation plan estimated ~4,100 chunks. **Built and measured 2026-08-29: 295**,
and 320 by the end of the same day, because this document is inside the corpus it
describes and writing the results up grew it. `make corpus-stats` is the authority for
today's number; the table below is a dated reading, not a live one.

| Source | Documents | Chunks | Tokens | avg | max |
|---|---|---|---|---|---|
| `doc` (`docs/*.md`) | 11 | 120 | 32,100 | 268 | 838 |
| `area_sheet` | 175 | 175 | 30,608 | 175 | 241 |
| `note` | 0 | 0 | — | — | — |
| **total** | **186** | **295** | **62,708** | | |

175 of 221 areas produced a sheet; **48 were skipped** by the 10-record floor, and no
area needed more than one chunk. An order of magnitude below the estimate.

That is a design input, not a disappointment — but the input turned out to point the
other way from what was predicted here. The expectation was that HNSW would lose to a
sequential scan at this size, as the GiST index did over 222 polygons in
[`postgis-query-plans.md`](postgis-query-plans.md). **Measured, HNSW is faster than the
sequential scan and the planner declines to use it anyway** — 3.5× faster at 295 chunks,
1.1× faster on re-measurement at 304 — because pgvector prices the index descent at a
startup cost several times the total cost of scanning the whole table. The full result,
and why that is a different failure mode from the GiST one, is in
[`hybrid-retrieval-plans.md`](hybrid-retrieval-plans.md) Experiment 1.

---

## 7.5 What is deliberately NOT in the corpus

Exactly one thing: **the evaluation questions.**

They live in [`eval/golden/retrieval.yaml`](../eval/golden/retrieval.yaml), which is not
under `docs/`, and `build_corpus.py` globs `docs/*.md`. The isolation is structural —
there is no filter to remember and no flag to pass. `scripts/build_corpus.py` also carries
a deny-list and an `--exclude` glob, but those are the second line of defence, for the day
someone points `--docs` at the repository root.

This is a correction, not a precaution. m13 wrote the ten questions into
`docs/hybrid-retrieval-plans.md`, that file is part of the corpus, and the lexical arm
then returned it for 8 of the 10 questions — matching the questions rather than the
answers. `mode=hybrid` was the shipped default and it was the worst of the three modes on
its own corpus. `api/tests/test_corpus_isolation.py` now fails the build if any golden
question reappears in `doc_chunks`, which it did once more while this milestone was being
written up.

**What is NOT excluded: the design documents themselves.** `hybrid-retrieval-plans.md`,
this file, and the rest of `docs/` stay indexed. They are the corpus's stated purpose —
"how does this platform deduplicate rent contracts?" is answered from engineering prose
and from nowhere else. Removing them would have fixed the metric by deleting the feature.

Two near-variants survive deliberately: the routing table in §1 above uses example
questions one word away from two of the golden ten. They are legitimate content in a
design document, they are graded 0 in the fixture, and when the cross-encoder promoted
them to rank 1 that was recorded as a result rather than patched out of the corpus.

---

## 8. Enabling pgvector — which is not the destructive part after all

The obvious reading is that this requires wiping the database. It does not, and the
difference is 561,115 rows.

`CREATE EXTENSION vector` lives in `init.sql`, and `docker-entrypoint-initdb.d` runs
**only on an empty data directory**. Both true. The conclusion drawn from it — that the
volume must therefore be dropped — is false. `CREATE EXTENSION` needs the pgvector
**binary present in the image**; it has no opinion about how old the cluster is.
`init.sql` is a convenience for a *fresh* volume, not the only route in.

So the blocker was always the image, and the fix touches only the image:

```bash
docker compose build postgres embeddings      # postgresql-16-pgvector from PGDG
docker compose up -d postgres                 # recreates the CONTAINER, keeps the VOLUME

docker compose exec postgres psql -U dubai_user -d dubai_re \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# The doc_chunks DDL, applied by hand. It is all IF NOT EXISTS, so this is the same
# statement init.sql would have run on a fresh volume.
awk '/^CREATE TABLE IF NOT EXISTS doc_chunks/,0' infra/postgres/init.sql \
  | docker compose exec -T postgres psql -U dubai_user -d dubai_re -v ON_ERROR_STOP=1

docker compose exec postgres psql -U dubai_user -d dubai_re \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','vector');"
# TWO rows expected: postgis 3.4.3, vector 0.8.6. One row means the image did not rebuild.

docker compose up -d
make test                                     # 111 passed
make index                                    # corpus -> chunks -> vectors
make corpus-stats
```

Executed 2026-08-29: **561,115 rows intact**, Alembic still at `0001`, `area_notes` and
`note_tags` untouched, no reload, no `alembic upgrade head`. `make seed` was not needed.

**If you genuinely have an empty volume** — a fresh clone, or CI — none of the above is
necessary: `init.sql` runs on first boot and creates the extension, the table and both
indexes. In that case you do need `make seed`, the portal loaders, and
`alembic upgrade head`, because `init.sql` creates every table *except* `area_notes` and
`note_tags`. Skipping Alembic fails 13 tests with a relation-does-not-exist error.

`make index` is incremental. Chunks whose hash is already present are not re-embedded;
their `chunk_index` is refreshed, because inserting or deleting a sibling shifts the
ordinals of everything after it even when the text is untouched. `make reindex` forces
the full rebuild and is **required** after changing the chunker or `EMBEDDING_MODEL`.
