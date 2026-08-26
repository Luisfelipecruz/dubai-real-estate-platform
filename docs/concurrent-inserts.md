# What happens when two inserts race

Captured against this stack — PostgreSQL 16.4, `raw_transactions` (200,001 rows,
`SERIAL` PK + `UNIQUE(transaction_id)`), two live `psql` sessions plus a third
observer session. Every code and number below is copied from the run, not recalled.

The anchor in this project: ingestion of the DLD CSV inserted **199,427 rows in 32.1 s
and rejected 573 duplicates** on that unique constraint. This document is what those
573 rejections actually are, mechanically.

---

## 1. The block, and then `23505`

Session A opens a transaction and inserts `LAB-X-1`. Session B inserts the *same*
`transaction_id` while A is still open. B does not fail — **B blocks.**

While B is blocked, from a third session:

```
 pid  |        state        | wait_event_type |  wait_event   | query
------+---------------------+-----------------+---------------+-------------------------
 3353 | active              | Lock            | transactionid | INSERT INTO raw_trans...
 3354 | idle in transaction | Client          | ClientRead    | INSERT INTO raw_trans...
```

```
 pid  | blocked_by
------+------------
 3353 | {3354}
```

```
   locktype    | transactionid |     mode      | granted | pid
---------------+---------------+---------------+---------+------
 transactionid |           967 | ShareLock     | f       | 3353   <- B waiting
 transactionid |           967 | ExclusiveLock | t       | 3354   <- A holds its own xid
 transactionid |           968 | ExclusiveLock | t       | 3353
```

**The detail worth saying out loud:** B is not waiting on a row lock. It is waiting for a
**`ShareLock` on transaction 967** — A's transaction id. Every transaction holds an
`ExclusiveLock` on its own xid for its whole life, so "wait for that xid's ShareLock" is
Postgres's generic way of spelling *wait until that transaction ends*. B cannot lock the
conflicting row, because from B's snapshot **the row does not exist yet**. The btree
unique check found an in-progress tuple and had nothing to block on except its author.

When A commits, B wakes up and re-checks:

```
ERROR:  23505: duplicate key value violates unique constraint "raw_transactions_transaction_id_key"
DETAIL:  Key (transaction_id)=(LAB-X-1) already exists.
LOCATION:  _bt_check_unique, nbtinsert.c:666
```

`23505` = `unique_violation`. The `LOCATION` names the mechanism: `_bt_check_unique`
in the **btree** insert path. The uniqueness is enforced by the index, not by the table.

### The same race where A rolls back

Identical setup, but A issues `ROLLBACK` instead of `COMMIT`. B wakes from the same
block and **succeeds**:

```
 transaction_id | actual_worth
----------------+--------------
 LAB-X-2        |       999.00
```

So the block is not a failure — it is a deferred decision. B sleeps until A's outcome is
known, then becomes either a duplicate error or a successful insert. **Block first, decide
after** is the part most candidates skip.

---

## 2. Sequences are non-transactional

`nextval` never blocks and never rolls back. That is deliberate — if it did either, every
insert would serialise on the sequence.

```
last_value before          : 200009
BEGIN; INSERT ...; ROLLBACK;
last_value after           : 200010     <- advanced anyway
rows matching that id      : 0          <- the row really is gone
```

**Gaps in a `SERIAL` column are expected, not corruption.** A surrogate key is an identity,
not a count. If someone needs a gapless sequence they need a different design (and a
serialisation point they will not enjoy).

---

## 3. `ON CONFLICT` — and the cost nobody mentions

```
last_value before                                    : 200010
INSERT ... ON CONFLICT (transaction_id) DO NOTHING   : INSERT 0 0
last_value after                                     : 200011     <- burned
```

Zero rows written, sequence still advanced. The default is evaluated *before* the conflict
is detected. At scale — a nightly idempotent re-ingest of a mostly-unchanged file — this
burns a sequence value per skipped row. Harmless on `bigint`, a real incident on `int`.

The upsert form, which is what idempotent ingestion should use:

```sql
INSERT INTO raw_transactions (transaction_id, area_name_en, actual_worth)
VALUES ('LAB-X-1','upserted',555)
ON CONFLICT (transaction_id) DO UPDATE SET actual_worth = EXCLUDED.actual_worth
RETURNING id, transaction_id, actual_worth;
```
```
   id   | transaction_id | actual_worth
--------+----------------+--------------
 200006 | LAB-X-1        |       555.00
```

`EXCLUDED` is the row that *would* have been inserted. `RETURNING` tells you which id you
ended up with — the only way to know without a second round trip.

**This is the fix for this project's ingestion.** Today it dedupes post-hoc and lets the
constraint reject 573 rows; `ON CONFLICT` makes it idempotent by primary key, which is
what it should have been from the start.

---

## 4. Deadlock — `40P01` — the multi-row batch trap

Two sessions insert the *same two keys in opposite order*:

| Session A | Session B |
|---|---|
| `BEGIN; INSERT 'LAB-D1';` | `BEGIN; INSERT 'LAB-D2';` |
| `INSERT 'LAB-D2';` → waits on B | |
| | `INSERT 'LAB-D1';` → waits on A → **cycle** |

```
ERROR:  40P01: deadlock detected
DETAIL:  Process 3353 waits for ShareLock on transaction 973; blocked by process 3354.
         Process 3354 waits for ShareLock on transaction 974; blocked by process 3353.
CONTEXT:  while inserting index tuple (4090,32) in relation "raw_transactions_transaction_id_key"
```

`pg_stat_database.deadlocks` went `0 → 1`. (It read 0 immediately after — the stats
collector flushes on a delay. Don't misread that as "no deadlock happened.")

Postgres detects the cycle after `deadlock_timeout` (1 s by default — it is a *timeout
before checking*, not a wait limit) and kills **one** victim. B died; **A survived and both
its inserts committed**. The database always breaks the cycle; your job is only to retry.

**The mitigation is one line: sort the batch by key before inserting.** If every writer
acquires keys in the same order, a cycle is impossible. This is the single most useful
thing to say here, because it is the fix for real bulk-insert deadlocks.

---

## 5. Isolation — what a concurrent insert is *allowed* to do to you

**Read Committed (default):** each statement takes a fresh snapshot, so a concurrent
committed insert becomes visible mid-transaction.

**Repeatable Read:** the snapshot is taken once, at first statement. Measured:

```
A: BEGIN ISOLATION LEVEL REPEATABLE READ;
A: count -> 2
   (another session inserts a matching row and COMMITs)
A: count -> 2        <- still the snapshot; the phantom is invisible
A: COMMIT;
A: count -> 3        <- now it is there
```

**Serializable:** true serial-equivalence via SSI, enforced by aborting one participant.
Two transactions each read `tag='x'` and then write based on what they read:

```
ERROR:  40001: could not serialize access due to read/write dependencies among transactions
DETAIL:  Reason code: Canceled on identification as a pivot, during commit attempt.
HINT:  The transaction might succeed if retried.
```

`40001` = `serialization_failure`. "Pivot" is SSI's term for the transaction sitting in the
middle of a dangerous read/write dependency structure. **Serializable is not free and it is
not optional to handle: if you choose it, you must write the retry loop.** The `HINT` is the
database telling you so.

---

## 6. Why a row lock cannot solve this

`SELECT ... FOR UPDATE` locks rows **that exist**. It cannot reserve a key that has not been
inserted yet — there is no tuple to lock, so two sessions both find nothing and both proceed.
That is precisely the hole `ON CONFLICT` (or a unique index, or an advisory lock) fills.

What `FOR UPDATE` *is* good for — the queue pattern:

```
A: BEGIN; SELECT id, tag FROM lab_counters ORDER BY id LIMIT 2 FOR UPDATE;    -> 1, 2
B: SELECT ... LIMIT 2 FOR UPDATE SKIP LOCKED;                                 -> 3, 4
```

B skipped A's locked rows and took the next available work instead of queuing behind it.
Without `SKIP LOCKED`, B blocks:

```
 pid  | state  | wait_event_type |  wait_event   | query
------+--------+-----------------+---------------+-----------------------------
 3353 | active | Lock            | transactionid | SELECT id, tag FROM lab_...
```

…and receives rows `1, 2` only once A commits. `SKIP LOCKED` is how you build a
work queue in Postgres without every worker serialising on the same head row.

**Advisory locks** — a mutex with no row behind it at all:

```
A: pg_advisory_lock(42)        -> acquired
B: pg_try_advisory_lock(42)    -> f      (non-blocking, refused)
A: pg_advisory_unlock(42)      -> t
B: pg_try_advisory_lock(42)    -> t      (now free)
```

Right tool for "only one instance of this import job may run", where the thing you are
protecting is not a row.

---

## 7. MVCC — why readers never blocked through any of this

An `UPDATE` does not overwrite. It writes a **new tuple version** and marks the old one dead:

```
before:  ctid (4082,28)   xmin 972   xmax 972
after :  ctid (4093,28)   xmin 981   xmax 0
```

Different `ctid` — a different physical location in the heap. `xmin` is the inserting xid,
`xmax` the deleting one. Visibility is a comparison of those against your snapshot, which is
why **readers never block writers and writers never block readers**. The only blocking in
this whole document was writer-vs-writer on the same key.

The bill arrives as bloat:

```
 n_live_tup | n_dead_tup |        last_autovacuum
------------+------------+-------------------------------
     200004 |          9 | 2026-08-15 07:42:14.632223+00
```

Dead tuples are reclaimed by `VACUUM`. That is the trade MVCC makes: no read locks, paid for
with garbage collection.

---

## The 60-second spoken answer

> Two inserts of different keys both succeed, and each gets its own sequence value —
> sequences are non-transactional, so `nextval` never blocks and never rolls back, which is
> why you see gaps after a rollback. Two inserts of the *same* unique key is the interesting
> case: the second one doesn't fail immediately, it **blocks** — and specifically it waits for
> a ShareLock on the first transaction's xid, because the conflicting row isn't visible to it
> yet, so there's no row to lock. When the first commits, the second raises `23505`
> unique_violation; if the first rolls back, the second succeeds. In my ingestion that's
> exactly the 573 duplicates the constraint rejected out of 199,427 rows. The right fix is
> `ON CONFLICT DO NOTHING` or `DO UPDATE ... RETURNING` to make it idempotent by key — noting
> it still burns sequence values, and that batches inserting overlapping keys in different
> orders will deadlock with `40P01`, so you sort the batch. Underneath it's MVCC: the insert
> writes a new tuple version with its `xmin`, readers never block writers, and the cost is
> bloat and VACUUM.

## Codes to know cold

| Code | Name | Raised when |
|---|---|---|
| `23505` | `unique_violation` | duplicate key, after the conflicting txn commits |
| `40P01` | `deadlock_detected` | lock cycle; one victim is killed, survivor proceeds |
| `40001` | `serialization_failure` | SSI conflict under Serializable — **retry** |
| `55P03` | `lock_not_available` | `NOWAIT` would have had to wait |

## Reproduce

`scripts/lab_concurrent_inserts.sh` drives both sessions over FIFOs and writes a full
transcript. It cleans up after itself — verified back to 200,001 rows, 49 tests green.
