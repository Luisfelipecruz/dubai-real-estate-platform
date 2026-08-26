# pandas vs PySpark, measured on the full 1.02 GB file

Not a feature list — a measurement. Same file, same aggregation, three configurations.

**Input:** `Transactions.csv`, 1,025,416,653 bytes (1.02 GB), **1,665,112 rows × 46 columns**
(DLD Dubai property transactions).

**The aggregation, identical in all runs:**
```
filter actual_worth > 0 and a parseable date
group by area_name_en, year, quarter
  -> count(*), sum(actual_worth), sum(meter_sale_price), count(meter_sale_price)
```

**Environment:** Docker Desktop, 19.5 GB VM, arm64. pandas 2.2.3 / Python 3.12 in the API
image. Spark 3.5.4, standalone cluster, one worker, `--total-executor-cores 2
--executor-memory 900m`.

Reproduce: `scripts/bench_pandas.py <naive|chunked> <csv>` and
`spark/jobs/bench_transactions_csv.py <csv>`.

---

## The numbers

| Run | Configuration | Wall time | Peak RSS | Result |
|---|---|---|---|---|
| **A** | `pd.read_csv(path)` — all 46 columns, inferred dtypes | **19.9 s** | **2,803 MB** | 14,965 groups |
| **A2** | same, in a **2 GB** container | — | — | **killed, exit 137 (SIGKILL/OOM)** |
| **B** | `chunksize=100_000` + `usecols` (5 cols) + explicit `dtype` | **8.5 s** | **230 MB** | 14,965 groups |
| **B2** | same, in a **2 GB** container | **6.4 s** | **229 MB** | 14,965 groups — survives |
| **C** | PySpark, standalone cluster, 2 cores | **8.0 s** (5.2 s in the action) | — | 14,969 groups |

### What each row is actually saying

**A — the memory multiplier.** A 1.02 GB file becomes a **3,472 MB DataFrame**
(`memory_usage(deep=True)`) — **3.4× the file on disk** — with peak process RSS at 2,803 MB.
The cause is dtype: read naively, all 46 columns land as `object`, and every cell is a
separate Python `str` with ~49 bytes of per-object overhead before its characters.

**A2 — the failure is the point.** Cap the container at 2 GB and the identical script is
**OOM-killed with no output at all** — it dies inside `read_csv`, before printing a single
line. This is the mode that takes down a production job at 3 a.m.: not a slow query, a
`SIGKILL`. Note the machine has 19.5 GB, so this only shows up when you constrain it — which
is exactly what a container orchestrator does to you.

**B — the fix is three keyword arguments.** `usecols` (5 of 46 columns), explicit `dtype`,
and `chunksize=100_000` (17 chunks). **230 MB peak — 12.2× less memory than A — and 2.3×
faster**, because the columns never read cost nothing to parse. The partial aggregates are
merged at the end; only the grouped result is ever fully resident.

**B2 — the same 2 GB box that killed A.** Chunked, it finishes in 6.4 s at 229 MB. Same
container, same file, same answer. **That pair — A2 dies, B2 succeeds — is the whole pandas
memory lesson in one comparison.**

**C — Spark at this size is a tie, not a win.** 8.0 s total against chunked pandas' 8.5 s,
and 2.75 s of that 8.0 s is spent building the plan before any data is touched. For 1 GB on
one machine, the JVM, the cluster round-trip and the 200-partition shuffle cost about as much
as they save. **Spark's advantage is not speed at this size — it is that the ceiling moves
off this machine.** Chunked pandas is bounded by one host's cores and disk; Spark is bounded
by the cluster.

> Say this unprompted: *"On 1 GB, Spark was a wash against chunked pandas — 8.0 versus 8.5
> seconds — and about a third of Spark's time was planning. The crossover isn't 'big data'
> vibes, it's single-machine memory. I use pandas for per-file ingestion because those CSVs
> are ~100 MB, and Spark for the cross-dataset quarterly aggregation because that one joins
> 1.6 million transactions against rents and valuations."*

---

## The finding that matters more than the timings

**The three runs did not agree, and the disagreement was real.**

```
pandas : 1,665,108 rows   14,965 groups   total 6,497,016,734,687
Spark  : 1,665,112 rows   14,969 groups   total 6,497,022,024,687
                 ^^^^ 4 rows            ^^^^ 4 groups      Δ 5,290,000
```

Four rows. Chasing them found this:

| transaction_id | instance_date | area_name_en | actual_worth |
|---|---|---|---|
| 2-13-1995-137 | `23-11-1422` | Al Hamriya | 2,000,000 |
| 2-13-1999-631 | `30-01-1420` | Al Mizhar Second | 500,000 |
| 2-13-1996-190 | `04-02-1417` | Al Mararr | 2,290,000 |
| 2-13-1995-128 | `02-07-1416` | Al Mizhar Second | 500,000 |

**Those are Hijri dates.** Years 1416–1422 AH — four records that went into the Dubai Land
Department's export on the Islamic calendar and were never converted to Gregorian. Real
government data, real dirt.

The two engines then disagreed about what to do with them:

- **pandas** coerces them to `NaT`. A `Series` conversion targets `datetime64[ns]`, whose
  representable range is **1677-09-21 → 2262-04-11** (nanoseconds in a signed 64-bit int).
  Year 1422 is outside it. Without `errors="coerce"` it raises
  `OutOfBoundsDatetime: Out of bounds nanosecond timestamp`. The four rows silently vanish.
- **Spark** parses them happily — `java.time.LocalDate` has no such range limit — yielding
  `1422-11-23` and **four spurious groups in years 1416–1422**, complete with a bogus
  5,290,000 added to the total.

**Neither engine is wrong; neither is right.** One silently drops the rows, the other
silently invents four groups fifteen centuries out of range. Both are wrong about the data,
which needs Hijri→Gregorian conversion, and until it gets one the honest move is to reject
the rows loudly rather than let either default decide.

> This is the strongest thing in this document to say out loud. It's a case where *the same
> logic on the same input gave two different answers*, the cause was a representation limit
> most people know only as trivia, and the fix is a domain conversion — not a code change.

### And a second parsing bug found the same way

The first version used `pd.to_datetime(..., format="mixed")`, which infers a format **per
element** — so an unambiguous `16-10-2006` reads day-first while an ambiguous `03-04-2019`
can read month-first, in the same column. Pinning `format="%d-%m-%Y"` moved the result from
**15,470 groups to 14,965**: 505 groups were artefacts of rows landing in the wrong quarter.

Spark's failure mode here is worse and quieter: `to_date()` defaults to `yyyy-MM-dd` and
returns **NULL** on mismatch rather than raising. The first cluster run returned **0 groups**
and exit code 0 — a completely successful job that computed nothing.

**Rule that comes out of this: always pin the date format explicitly, in both engines.**
Silent nulls and per-row inference are the two ways a date column lies to you.

---

## The decision, stated as a decision

**pandas** is single-node and eager: it materialises everything in RAM, so the ceiling is one
machine — in practice a few GB, because object dtypes cost several times the file size. Below
that ceiling it wins on latency, no JVM, no cluster, and a richer API. In this platform it
handles per-file CSV ingestion (~100 MB each): **199,427 rows in 32.1 s** through pandas +
`execute_values`.

**PySpark** is distributed and lazy: it builds a plan, Catalyst optimises it, and nothing
executes until an action. It wins when data exceeds one machine, when the work should
parallelise across a cluster, or when a long job needs fault tolerance mid-flight. Here it
runs the cross-dataset quarterly aggregation over 1.6 M transactions joined to rents and
valuations.

**The line between them is single-machine memory, and the measurements above are where it
sits for this workload.**

Supporting points worth having ready: lazy vs eager evaluation; narrow vs wide
transformations and why the shuffle is the expensive one (this job used the default
`spark.sql.shuffle.partitions = 200` for 14,969 groups — over-partitioned for the data
size); `.collect()` pulling a whole DataFrame into the driver as the classic mistake;
broadcast joins for the small-lookup case; and the third option — pushing the aggregation
into Postgres with SQL and moving no data at all, which for this particular query would beat
both.
