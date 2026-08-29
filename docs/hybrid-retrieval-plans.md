# Hybrid retrieval query plans — does HNSW earn its place at this corpus size?

**Status: measured 2026-08-29 (m13), re-measured 2026-08-29 (m13a)** against 304 chunks on
PostgreSQL 16.15 (x86_64, emulated) / PostGIS 3.4.3 / pgvector 0.8.6, embeddings
`BAAI/bge-small-en-v1.5`, reranker `BAAI/bge-reranker-base`.

Every number below was captured from the commands printed beside it. Four of the five
experiments contradicted the hypothesis they were written to test, one found a bug, and
one — Experiment 3 — had to be thrown away and run again because the questions it used
were inside the corpus it was measuring. Those outcomes are recorded here in preference
to the expectations they replaced.

**Two of them changed a shipped default.** `GET /search` now defaults to `mode=dense`
and `rerank=false`; it shipped as `mode=hybrid, rerank=true`. Both changes are Experiment
3 run 2.

**The corpus was 304 chunks when these numbers were taken. It is larger now, because
writing them down grew it** — this file is in the corpus it measures. Re-running an
experiment will therefore not reproduce the row counts here exactly, and
`make corpus-stats` is always the authority for the current size. That is a mild nuisance
for Experiments 1, 2 and 5. For Experiment 3 it was fatal, and the fix is m13a: the ten
questions now live in [`eval/golden/retrieval.yaml`](../eval/golden/retrieval.yaml),
outside `docs/` and so outside the corpus, and
`api/tests/test_corpus_isolation.py` fails the build if any of them reappears in it.

**Read the caveat before quoting a timing.** The `postgres` container runs `linux/amd64`
under emulation on this arm64 host — its data directory was initialised by an amd64
cluster, and PostgreSQL data directories are not portable across architectures, so
switching the image would mean rebuilding the volume. Every database timing here is
therefore inflated by emulation. **Comparisons between two plans are sound** (both arms
pay the same tax); **absolute milliseconds are not** a native-hardware figure. The
`embeddings` and `api` containers are native arm64, so Experiment 4's numbers are real.

---

## The question

`docs/postgis-query-plans.md` recorded a result worth taking seriously: a GiST index over
222 community polygons made a single point-in-polygon lookup **slower** than the
sequential scan it replaced (2.95 ms vs 2.34 ms). The planner's cost estimate dropped
137×; the wall-clock time went up. 222 rows live in a handful of pages, so reading all of
them costs nothing, and the index descent is pure overhead.

The retrieval corpus is the same order of magnitude — **304 chunks measured** (129 from
`docs/*.md`, 175 area fact sheets, 0 notes). So:

> **Hypothesis: at this corpus size the HNSW index will not beat a sequential scan, and
> may lose to it.**

**The hypothesis was wrong, and the way it was wrong is the interesting part.** See
Experiment 1.

---

## Experiment 1 — HNSW vs sequential scan on the dense arm

```bash
# What the planner does when left alone
docker compose exec postgres psql -U dubai_user -d dubai_re -c "
  EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT id FROM doc_chunks
   ORDER BY embedding <=> '[...]'::vector LIMIT 20;"

# Forced onto the index for comparison
docker compose exec postgres psql -U dubai_user -d dubai_re -c "
  SET enable_seqscan = off;
  EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT id FROM doc_chunks
   ORDER BY embedding <=> '[...]'::vector LIMIT 20;"
```

Four warm repetitions each; the first (cold-cache) run of each is reported separately
rather than averaged in.

| Run | Chunks | Configuration | Planner cost | Warm median (end to end) | Buffers |
|---|---|---|---|---|---|
| m13 | 295 | HNSW index scan (forced) | 302.21..533.90 | **0.131 ms** | **340** |
| m13 | 295 | Sequential scan (chosen) | 0.00..60.69 → Sort 68.54..69.27 | 0.464 ms | 645 |
| m13a | 304 | HNSW index scan (forced) | 478.28..934.08 | **1.85 ms** | **403** |
| m13a | 304 | Sequential scan (chosen) | 0.00..116.80 → Sort 124.89..125.65 | 2.06 ms | 1,056 |

**The finding, and it is the opposite of the hypothesis: HNSW wins on both axes — and the
planner refuses to use it anyway.**

**Read the two runs as one conclusion and two margins.** The direction held on
re-measurement — HNSW faster, HNSW cheaper in buffers, planner declining it — but the
margin collapsed from 3.5× to 1.1×, and every absolute number rose about 4×. The row
count moved only 3%; the heap doubled, 456 kB → 904 kB, because the documents rewritten
while recording these results are much longer than the ones they replaced. A sequential
scan pays for that directly and the index scan does not, which is why the buffer ratio
moved the other way (1.9× → 2.6×).

Absolute milliseconds across two sessions on an emulated container with different cache
states are not a measurement of anything. **Plan versus plan inside one session is**, and
that comparison gives the same answer twice. The m13a row is post-`VACUUM (ANALYZE)`, so
it is not reporting transient bloat from the re-index cycles.

The cost model is why. pgvector prices the HNSW scan at a **startup cost of 302.21**,
five times the *total* cost of scanning and sorting all 295 rows (69.27) — and on the
m13a re-run, 478.28 against a total of 125.65, a gap that widened to 3.8×. The planner is
not comparing execution times; it is comparing its own estimates, and its estimate of the
index descent is far more pessimistic than reality. At 295 rows nothing here is slow
enough for the difference to matter — 0.33 ms — but the shape of the error is worth
knowing: **this index will sit unused until the corpus grows enough to move the seq-scan
cost above 302**, which at ~0.2 cost units per row is somewhere near 1,500 chunks.

This is a materially different conclusion from the GiST result it was modelled on. There,
the index was genuinely slower and the cost estimate was wildly optimistic. Here the index
is genuinely faster and the cost estimate is wildly pessimistic. The two cases look alike
— "small table, index not worth it" — and are not.

**The index stays.** Not because it is earning anything today, but because the cost of
keeping it is 600 kB and a millisecond per re-index, and it starts paying automatically.

### The ordering trap

`ORDER BY embedding <=> $1` can use the index. `ORDER BY 1 - (embedding <=> $1) DESC` is
mathematically identical, reads more naturally, and cannot — the operator class answers
only the bare distance operator. `api/services/retrieval.py` orders on the raw operator
and computes similarity as a separate select-list expression for this reason.

| Ordering expression | Node chosen | Actual time |
|---|---|---|
| `ORDER BY embedding <=> $1` | Seq Scan + Sort | 0.512 ms |
| `ORDER BY 1 - (embedding <=> $1) DESC` | Seq Scan + Sort | 0.429 ms |

**Both sequential — so the trap is real but currently unobservable here.** The planner
declines the index for the raw operator too (above), so the two forms collapse onto the
same plan and the derived form is not punished. The defensive coding in `retrieval.py`
is still correct and still worth keeping: it is protecting against the state this table
enters once it passes ~1,500 chunks, at which point only one of these two forms keeps
using the index. It just cannot be demonstrated at 295 rows, and claiming otherwise from
this data would be dishonest.

---

## Experiment 2 — index size against corpus size

```sql
SELECT (SELECT COUNT(*) FROM doc_chunks)                     AS chunks,
       pg_size_pretty(pg_relation_size('doc_chunks'))        AS tbl,
       pg_size_pretty(pg_relation_size('idx_chunks_hnsw'))   AS hnsw,
       pg_size_pretty(pg_relation_size('idx_chunks_tsv'))    AS gin,
       pg_size_pretty(pg_total_relation_size('doc_chunks'))  AS total;
```

| Run | Chunks | Table | HNSW | GIN | Total | HNSW as % of table |
|---|---|---|---|---|---|---|
| m13 | 295 | 456 kB | 600 kB | 720 kB | 2,592 kB | **132%** |
| m13a | 304 | 904 kB | 952 kB | 720 kB | 4,112 kB | **105%** |

**Both indexes are larger than the table they index**, and the GIN index was larger than
the HNSW one until the documents grew. A 384-dim `vector` is ~1,532 bytes of payload, so
the table is mostly vector; HNSW then stores its own copy of every vector plus the graph
edges, which is why it cannot help but exceed the heap at small row counts. The whole
retrieval layer costs **4.1 MB** — against 561,115 rows of DLD data in the same database.

The ratio fell from 132% to 105% on a 3% row increase, which is worth reading correctly:
HNSW did not get more efficient. The *heap* grew — longer documents, more text per row —
while the vector payload per row is fixed at 384 dimensions no matter how long the chunk
is. GIN is flat at 720 kB across both runs because the lexemes were already there.


---

## Experiment 3 — the three retrieval modes

Ten questions, `rerank=false` so this compares the retrieval arms rather than the
cross-encoder. Top-1 only.

**The questions are not written down in this file.** They live in
[`eval/golden/retrieval.yaml`](../eval/golden/retrieval.yaml) — outside `docs/`, and so
outside the corpus — and appear here only as `G-01`…`G-10`. That is not tidiness. It is
the fix for what the first run of this experiment actually measured, and the first run is
kept below because the difference between the two is the result.

```bash
for MODE in dense lexical hybrid; do
  curl -s -G 'http://localhost:8000/search' --data-urlencode "q=$Q" \
       --data-urlencode "mode=$MODE" --data-urlencode 'rerank=false' --data-urlencode 'k=1'
done
```

### Run 1 — invalid. The eval questions were inside the corpus.

| Q | Dense top-1 | Lexical top-1 | Hybrid top-1 | Which arm was right |
|---|---|---|---|---|
| G-01 | architecture.md › Deduplication at Ingestion | *this file* | architecture.md › Deduplication at Ingestion | dense |
| G-02 | changelog.md › v0.5.0 | *this file* | changelog.md › v0.5.0 | dense |
| G-03 | changelog.md › v0.6.0 | *this file* | pandas-vs-pyspark.md | dense (hybrid lost it) |
| G-04 | rag-corpus-design.md | *this file* | rag-corpus-design.md | dense |
| G-05 | **postgis-query-plans.md** | polygon-adjacency-plans.md | polygon-adjacency-plans.md | dense (hybrid lost it) |
| G-06 | changelog.md › v0.7.0 | *this file* | changelog.md › v0.7.0 | dense |
| G-07 | **Business Bay** (area sheet) | *this file* | *this file* | dense (hybrid lost it) |
| G-08 | **Business Bay** (area sheet) | changelog.md › v0.7.0 | rag-corpus-design.md | dense (hybrid lost it) |
| G-09 | **n-plus-one-demo.md** › Captured output | *this file* | *this file* | dense (hybrid lost it) |
| G-10 | *this file* | *this file* | *this file* | inconclusive |

*Italics* mark a hit on `hybrid-retrieval-plans.md` — this document.

**The lexical arm returned this file for 8 of the 10 questions.** Not because it retrieves
badly, but because this document contained the ten evaluation questions verbatim, in that
table, and `websearch_to_tsquery` matches a question against the literal text of that
question better than against any document that merely *answers* it.

The leak was worse than it was first reported. The original write-up said "7 of the 10
questions appear word-for-word in the indexed corpus", counted by hand.
`test_no_golden_question_appears_in_the_corpus` counts it by querying `doc_chunks`, and
the answer is **9 of 9** — every question still phrased as it was then. (G-08 is the
tenth and was reworded in m13a; see the fixture for why.) A hand-count of a contamination
problem undercounted the contamination, which is its own small lesson about hand-counts.

Two consequences, and the second is the one that mattered:

1. **The lexical column was unusable as evidence.** It measured self-reference, not
   retrieval.

2. **Hybrid scored worse than dense alone on 5 of 10 questions**, because RRF gives the
   contaminated lexical ranking equal weight with a dense ranking that was right 9 times
   out of 10. Fusing a good arm with a poisoned one produces something worse than the
   good arm — a correct and unsurprising property of RRF being fed bad input, since it
   has no notion of which arm to trust. But it meant the shipped default, `mode=hybrid`,
   was the worst of the three modes on its own corpus.

**This was a corpus-construction bug, not a retrieval bug.** Fixed in m13a by moving the
questions out of `docs/` — not by removing the design documents, which are in the corpus
on purpose.

### Run 2 — questions outside the corpus

| Q | Dense top-1 | Lexical top-1 | Hybrid top-1 | Graded D/L/H |
|---|---|---|---|---|
| G-01 | **architecture.md › Deduplication at Ingestion** | rag-corpus-design.md › The routing rule | **architecture.md › Deduplication at Ingestion** | 3/0/3 |
| G-02 | **changelog.md › Measured** | **changelog.md › The routing decision** | **changelog.md › Measured** | 3/3/3 |
| G-03 | changelog.md › The chart decisions | pandas-vs-pyspark.md | pandas-vs-pyspark.md | 1/1/1 |
| G-04 | **rag-corpus-design.md › Two data traps** | **rag-corpus-design.md › Two data traps** | **rag-corpus-design.md › Two data traps** | 3/3/3 |
| G-05 | **postgis-query-plans.md › Experiment 1** | polygon-adjacency-plans.md | polygon-adjacency-plans.md | 3/1/1 |
| G-06 | **changelog.md › The routing decision** | **changelog.md › Measured** | **changelog.md › The routing decision** | 3/3/3 |
| G-07 | **Business Bay** (area sheet) | changelog.md › Fixed (data-quality) | **Business Bay** (area sheet) | 3/0/3 |
| G-08 | **Business Bay** (area sheet) | changelog.md › Fixed (data-quality) | **Business Bay** (area sheet) | 3/0/3 |
| G-09 | **n-plus-one-demo.md › Captured output** | changelog.md › v0.6.0 | **n-plus-one-demo.md › Captured output** | 3/0/3 |
| G-10 | rag-corpus-design.md › Enabling pgvector | architecture.md › Docker Compose | rag-corpus-design.md › Enabling pgvector | 0/0/0 |

Grades are from the rubric in the fixture, written before the run: **3** ideal, **2**
acceptable, **1** related, **0** wrong. Recall counts only the ideal document.

| Mode | top-1 ideal | mean grade | recall@1 | recall@5 | recall@10 | returned nothing |
|---|---|---|---|---|---|---|
| **dense** | **8/10** | **2.50** | **8/10** | **9/10** | **9/10** | 0/10 |
| hybrid | 7/10 | 2.30 | 7/10 | 9/10 | 9/10 | 0/10 |
| lexical | 3/10 | 1.10 | 3/10 | 7/10 | 8/10 | 0/10 |


### What the clean run says

**1. Hybrid never beat dense — at any k, in any configuration.** It ties at recall@5 and
recall@10 and loses one position at k=1 (G-05, where the fused lexical ranking pushes the
correct document from rank 1 to rank 3). There is no question in the set where the lexical
arm supplied a correct document that dense had missed. Not one.

The case for hybrid retrieval on this corpus is therefore unproven, and the default
changed to `mode=dense`. What would change the answer: exact-match surface — procedure
numbers, error strings, identifiers — which ten hand-written prose questions do not
exercise and a real user would eventually produce.

**2. The lexical arm returned nothing at all for 5 of the 10 questions**, and this was
completely invisible in run 1. `websearch_to_tsquery` **conjoins** its terms:

```
'Which districts adjoin Palm Jumeirah'  ->  'district' & 'adjoin' & 'palm' & 'jumeirah'
```

(That example is deliberately *not* one of the ten. Writing a golden question into this
file to illustrate its own tsquery would re-create the exact bug the milestone fixed —
`test_no_golden_question_appears_in_the_corpus` caught the first draft of this paragraph
doing precisely that.)

A chunk missing any single stem is excluded. Measured against the corpus directly, the
strict query matched **0 chunks for G-06 through G-10** and 1–3 chunks for most of the
rest. In run 1 every conjunction was satisfied — by the document containing the question.
**The contamination was not just inflating the lexical arm's score; it was hiding that
the arm barely worked.**

The fix is a relaxation: when the strict query matches nothing, re-run it with the
top-level `&` rewritten to `|` and let `ts_rank_cd` sort. Lexical-only recall@5 went 3/10
→ 7/10.

**3. Relaxing inside hybrid made hybrid worse — 7/10 → 5/10 top-1.** The relaxed arm
stops returning nothing and starts returning a confidently wrong document at rank 1, and
RRF weights it equally with a dense ranking that was right. This is the contamination
lesson arriving from the opposite direction: **RRF has no notion of which arm to trust, so
improving an arm's recall while destroying its precision@1 makes the fusion worse.** The
relaxation now runs only when lexical is the sole arm — in hybrid the dense arm already
guarantees a non-empty result, so it has nothing to fix there.

**4. G-07 is the clearest single demonstration of why the dense arm exists.** The fact
sheets say *"Shares a boundary with AL QOUZ FIRST, AL WASL, …"*. The question says
*"border"*. `boundari` and `border` are different lexemes, so no lexical query can bridge
them at any relaxation setting — and the dense arm returned the right sheet at rank 1.
That is the textbook argument for embeddings, and it is the one case here where it is
demonstrated rather than asserted.

**5. Two questions are missed by every mode, and both are corpus-construction problems.**

- **G-03** wants `data-model.md`, where the answer is one row of a forty-row markdown
  table. The chunk embeds as "a table of column definitions", not as "what
  `meter_sale_price` means". A reference table is a bad chunk, and no retrieval mode
  rescues it.
- **G-10** wants the one bullet in `changelog.md` that argues against LangChain. Dense
  returns a pgvector section instead. One sentence inside a 284-token chunk is below the
  resolution of the chunker.

Both are m16 material: they are fixed by chunking, not by retrieval.

### What the cross-encoder does to ranking

Experiment 4 measured what the reranker *costs* — 2,944 ms p50, 99.2% of the pipeline.
It did not measure what it *buys*. Re-running the golden set with `rerank=true`:

| Mode | top-1 ideal, rerank off | top-1 ideal, rerank on | recall@5 off | recall@5 on |
|---|---|---|---|---|
| dense | **8/10** | **3/10** | **9/10** | 6/10 |
| hybrid | 7/10 | 2/10 | 9/10 | 6/10 |
| lexical | 3/10 | 4/10 | 7/10 | 8/10 |

**The cross-encoder loses five of dense's eight correct top-1 answers.** It moves G-04
from rank 1 to unranked, G-09 from rank 1 to rank 7, G-05 from rank 1 to rank 6.

This was checked for the obvious bug first, because a result this bad is usually a sort
direction. It is not. Probed directly with three documents, the reranker scores the
relevant one **0.2574** and the two irrelevant ones **0.0000374** — correct, and correctly
ordered. The model works. It is being asked the wrong question.

What it actually promotes is the tell. For G-01 and G-07 the top-ranked chunk becomes
`rag-corpus-design.md › The routing rule` — the section holding a table of **example
questions** used to illustrate which queries should go to SQL and which to RAG. Those two
examples are near-variants of G-01 and G-07, one word apart, and they are deliberately
still in the corpus and graded 0 in the fixture. The bi-encoder ranked the answers first.
**The cross-encoder, scoring the query against each document jointly, is drawn to text
that *resembles the question* rather than text that answers it** — the same failure the
contaminated lexical arm had, in a model that was supposed to be the quality layer.

So `rerank` is now opt-in. It is the rare change that is simultaneously 44× faster and
more accurate, and the honest summary is that **this repository has not found a
configuration in which the cross-encoder earns its 2.9 seconds.** m16 gets the levers —
truncate before scoring, cut the candidate count, ONNX export, or drop it — and now has a
quality number to beat as well as a latency one.

### What this experiment is not

n = 10 questions, hand-written, against a 304-chunk corpus of one project's own
engineering documentation, by the person who wrote both the documents and the questions.
That is enough to change a default — the effects are large and mechanically explained —
and nowhere near enough to say anything general about hybrid retrieval or cross-encoders.
The m16 harness exists to make this set bigger and the grading less mine.


## Experiment 4 — per-stage latency, and what the reranker costs

20 samples (10 questions × 2 rounds) per configuration, models already warm. `api` and
`embeddings` are native arm64, so these are real numbers.

| Stage | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|
| embed (query) | 31 | 70 | 133 |
| dense | 1 | 1 | 1 |
| lexical | 0 | 0 | 0 |
| fuse | 0 | 0 | 0 |
| rerank (≤40 candidates) | **2,919** | **4,098** | 6,135 |
| **total, rerank=true** | **2,944** | **4,137** | 6,208 |
| **total, rerank=false** | **67** | **155** | 218 |

**The cross-encoder is 99.2% of the p50 latency and costs 44× the entire rest of the
pipeline.** Retrieval itself — embed, both arms, and fusion — completes in 67 ms p50.

This is an order of magnitude over the 200–400 ms the plan budgeted for reranking, and it
has consequences beyond m13:

- **The m17 voice budget of 800 ms to first audio cannot include this reranker.** It is
  3.7× the entire budget on its own. Voice must run `rerank=false`, or the reranker must
  get an order of magnitude cheaper.
- `bge-reranker-base` is a 278M-parameter cross-encoder scoring up to 40 query/document
  pairs of up to 512 tokens each, on CPU, one request at a time. The bi-encoder embeds a
  query in 31 ms because it does one forward pass over ~10 tokens; the cross-encoder does
  40 forward passes over ~500 tokens. The ratio is roughly what the arithmetic predicts.
- The obvious levers, none yet measured: truncate documents before scoring, cut the
  candidate count below 40, batch, export to ONNX, or drop the reranker. m16 decides,
  and it now has a real number to beat instead of an assumption.

**`rerank=false` is not a degraded mode — it is the fast path.** Experiment 3 run 2 went
further and measured what the reranker buys as well as what it costs: dense top-1 falls
from 8/10 to 3/10 with the cross-encoder in the loop. It is the *only* path this
repository can currently defend, and it is now the default.

---

## Experiment 5 — incremental re-index cost

```bash
make reindex   # full rebuild, --force
make index     # incremental, hash diff
```

| Operation | Chunks embedded | Chunks skipped | Wall clock |
|---|---|---|---|
| Full rebuild (`make reindex`) | 295 | 0 | 31,240 ms |
| One document edited (`make index`) | **1** | 294 | 1,155 ms |
| No change at all (`make index`) | **0** | 295 | **146 ms** |

A no-op re-index is **214× cheaper** than a rebuild, and editing one document costs one
embedding.

Re-run in m13a after rewriting three documents and adding one, at 304 chunks:

| Operation | Chunks embedded | Chunks skipped | Stale removed | Wall clock |
|---|---|---|---|---|
| Four documents edited (`make index`) | **7** | 297 | 7 | 931 ms |
| No change at all (`make index`) | **0** | 304 | 0 | **82 ms** |

The second row is the one that matters and it is the reason to re-run this experiment at
all: the content-hash fix below still holds after a corpus edit that touched four of the
eleven documents. Seven chunks changed, seven were re-embedded, and the 297 that did not
change were not touched.

### This experiment found a bug

The doc said: *"The third row is the one to check first. If an unchanged corpus re-embeds
anything, the hash is not covering what it should."* On the first run it re-embedded
**175 of 295 chunks with no source change** — every area fact sheet, every time:

```
diff : 175 to embed, 120 unchanged, 175 stale removed, 0 re-ordered
```

The 120 document chunks were correctly skipped, which localised it immediately: something
in the *generated* sheets was unstable. Diffing two consecutive builds character by
character found it at offset 466 of every sheet —

```
A: ... Fact sheet generated 2026-08-29T11:47:54+00:00 from the loaded DLD data.
B: ... Fact sheet generated 2026-08-29T11:47:57+00:00 from the loaded DLD data.
```

`render_area_sheet()` embedded `datetime.now()` in the text that `content_hash` is
computed over, so every sheet looked new on every build. **Generation time is provenance,
not content.** It was removed from the hashed text; it survives in the record's `meta`
and in the `doc_chunks.generated_at` column, neither of which is hashed. The three rows
above are from after the fix.

Worth stating plainly: **only the second run could have caught this.** A single indexing
run looks identical whether the hash works or not.

---

## Known truncations, already measured

Two chunks exceed the model's 512-token sequence limit, both fenced `EXPLAIN` blocks in
`postgis-query-plans.md`, at **838 and 811 tokens**. `index_corpus.py` prints a
`WARNING: truncated` line for each on every run. The chunker emits oversized fenced
blocks whole rather than cutting a statement in half, so the dense arm sees only their
first 512 tokens while the lexical arm sees all of both.

Experiment 3's G-05 was written to check whether that question is answered from one of
these two chunks, and by which arm. **It is, and by the dense arm** —
which returned `postgis-query-plans.md` correctly despite seeing only the first 512
tokens of the relevant block. The lexical arm, which can see all 838 tokens, returned
`polygon-adjacency-plans.md` instead. The hoped-for illustration — lexical recovering
text dense cannot see — did not happen; the reverse did.
