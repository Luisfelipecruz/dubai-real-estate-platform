#!/usr/bin/env bash
# P2 — concurrent insert lab. Drives two persistent psql sessions over FIFOs
# plus a third one-shot "observer" session, and writes a full transcript.
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/p2_transcript.txt"
CTR="dubai-real-estate-platform-postgres-1"
: > "$OUT"

PSQL_ONE() { docker exec -i "$CTR" psql -X -U dubai_user -d dubai_re -v ON_ERROR_STOP=0 -c "$1" 2>&1; }

say() { printf '\n========== %s ==========\n' "$1" >> "$OUT"; }
obs() { printf -- '--- observer: %s\n' "$1" >> "$OUT"; PSQL_ONE "$2" >> "$OUT"; }

# ---- open two persistent sessions -------------------------------------------
for S in A B; do
  rm -f "$DIR/$S.fifo"; mkfifo "$DIR/$S.fifo"; : > "$DIR/$S.out"
  ( docker exec -i "$CTR" psql -X -U dubai_user -d dubai_re \
      -v ON_ERROR_STOP=0 --echo-all < "$DIR/$S.fifo" > "$DIR/$S.out" 2>&1 ) &
done
exec 3> "$DIR/A.fifo"
exec 4> "$DIR/B.fifo"
A() { printf '%s\n' "$1" >&3; }
B() { printf '%s\n' "$1" >&4; }

A '\set VERBOSITY verbose'
B '\set VERBOSITY verbose'
A "SELECT pg_backend_pid() AS session_A_pid;"
B "SELECT pg_backend_pid() AS session_B_pid;"
sleep 2

# =============================================================================
say "SETUP — scratch rows + a serializable playground table"
PSQL_ONE "DELETE FROM raw_transactions WHERE transaction_id LIKE 'LAB-%';" >> "$OUT"
PSQL_ONE "DROP TABLE IF EXISTS lab_counters; CREATE TABLE lab_counters(id serial primary key, tag text, n int);" >> "$OUT"
PSQL_ONE "INSERT INTO lab_counters(tag,n) VALUES ('x',1),('x',2),('y',3);" >> "$OUT"

# =============================================================================
say "DEMO 1 — two inserts of the SAME transaction_id: the block, then 23505"

A "BEGIN;"
A "INSERT INTO raw_transactions (transaction_id, area_name_en, actual_worth) VALUES ('LAB-X-1','Lab Area',100);"
sleep 2
printf -- '--- session A has inserted, transaction still OPEN\n' >> "$OUT"

B "BEGIN;"
B "INSERT INTO raw_transactions (transaction_id, area_name_en, actual_worth) VALUES ('LAB-X-1','Lab Area',999);"
sleep 3
printf -- '--- session B issued the same insert; it should now be BLOCKED\n' >> "$OUT"

obs "who is running / waiting" \
"SELECT pid, state, wait_event_type, wait_event, left(query,55) AS query
   FROM pg_stat_activity
  WHERE datname='dubai_re' AND state <> 'idle' AND pid <> pg_backend_pid()
  ORDER BY state;"

obs "blocking graph (pg_blocking_pids)" \
"SELECT pid, pg_blocking_pids(pid) AS blocked_by, left(query,55) AS query
   FROM pg_stat_activity
  WHERE cardinality(pg_blocking_pids(pid)) > 0;"

obs "ungranted locks — note locktype/mode" \
"SELECT locktype, relation::regclass AS rel, transactionid, mode, granted, pid
   FROM pg_locks WHERE NOT granted;"

obs "what B is actually waiting for: a ShareLock on A's xid" \
"SELECT l.pid, l.locktype, l.transactionid, l.mode, l.granted
   FROM pg_locks l
  WHERE l.locktype = 'transactionid'
  ORDER BY l.granted;"

printf -- '\n--- session A COMMITs -> B must now fail with 23505\n' >> "$OUT"
A "COMMIT;"
sleep 3
B "ROLLBACK;"
sleep 1

# =============================================================================
say "DEMO 2 — same race, but A ROLLS BACK: B succeeds instead"

A "BEGIN;"
A "INSERT INTO raw_transactions (transaction_id, area_name_en, actual_worth) VALUES ('LAB-X-2','Lab Area',100);"
sleep 2
B "BEGIN;"
B "INSERT INTO raw_transactions (transaction_id, area_name_en, actual_worth) VALUES ('LAB-X-2','Lab Area',999);"
sleep 3
printf -- '--- B blocked again; this time A rolls back\n' >> "$OUT"
A "ROLLBACK;"
sleep 3
B "SELECT transaction_id, actual_worth FROM raw_transactions WHERE transaction_id='LAB-X-2';"
B "COMMIT;"
sleep 2

# =============================================================================
say "DEMO 3 — sequences are NON-TRANSACTIONAL (gaps are expected)"

obs "sequence before" "SELECT last_value, is_called FROM raw_transactions_id_seq;"
PSQL_ONE "BEGIN; INSERT INTO raw_transactions (transaction_id) VALUES ('LAB-ROLLBACK-ME'); ROLLBACK;" >> "$OUT"
obs "sequence after an INSERT that was ROLLED BACK" "SELECT last_value, is_called FROM raw_transactions_id_seq;"
obs "and the row is definitely not there" "SELECT count(*) AS should_be_zero FROM raw_transactions WHERE transaction_id='LAB-ROLLBACK-ME';"

# =============================================================================
say "DEMO 4 — ON CONFLICT DO NOTHING still burns sequence values"

obs "sequence before" "SELECT last_value FROM raw_transactions_id_seq;"
obs "insert a duplicate with ON CONFLICT DO NOTHING (0 rows affected)" \
"INSERT INTO raw_transactions (transaction_id, area_name_en) VALUES ('LAB-X-1','dup')
 ON CONFLICT (transaction_id) DO NOTHING;"
obs "sequence after — advanced anyway" "SELECT last_value FROM raw_transactions_id_seq;"
obs "DO UPDATE ... RETURNING (the upsert form)" \
"INSERT INTO raw_transactions (transaction_id, area_name_en, actual_worth) VALUES ('LAB-X-1','upserted',555)
 ON CONFLICT (transaction_id) DO UPDATE SET actual_worth = EXCLUDED.actual_worth
 RETURNING id, transaction_id, area_name_en, actual_worth;"

# =============================================================================
say "DEMO 5 — DEADLOCK (40P01) from batches inserted in opposite order"

A "BEGIN;"
A "INSERT INTO raw_transactions (transaction_id) VALUES ('LAB-D1');"
B "BEGIN;"
B "INSERT INTO raw_transactions (transaction_id) VALUES ('LAB-D2');"
sleep 3
printf -- '--- now each session reaches for the other one key: A->D2, B->D1\n' >> "$OUT"
A "INSERT INTO raw_transactions (transaction_id) VALUES ('LAB-D2');"
sleep 2
B "INSERT INTO raw_transactions (transaction_id) VALUES ('LAB-D1');"
sleep 4
printf -- '--- deadlock_timeout is 1s by default; the detector should have fired\n' >> "$OUT"
obs "deadlock counter for this database" \
"SELECT datname, deadlocks FROM pg_stat_database WHERE datname='dubai_re';"
A "ROLLBACK;"
B "ROLLBACK;"
sleep 2

# =============================================================================
say "DEMO 6 — ISOLATION: Read Committed vs Repeatable Read snapshot"

A "BEGIN ISOLATION LEVEL REPEATABLE READ;"
A "SELECT count(*) AS a_sees_at_start FROM raw_transactions WHERE transaction_id LIKE 'LAB-%';"
sleep 2
PSQL_ONE "INSERT INTO raw_transactions (transaction_id) VALUES ('LAB-PHANTOM');" >> "$OUT"
sleep 1
A "SELECT count(*) AS a_still_sees_snapshot FROM raw_transactions WHERE transaction_id LIKE 'LAB-%';"
A "COMMIT;"
sleep 1
A "SELECT count(*) AS a_after_commit_sees_it FROM raw_transactions WHERE transaction_id LIKE 'LAB-%';"
sleep 2

# =============================================================================
say "DEMO 7 — SERIALIZABLE: 40001 serialization_failure on write skew"

A "BEGIN ISOLATION LEVEL SERIALIZABLE;"
B "BEGIN ISOLATION LEVEL SERIALIZABLE;"
A "SELECT sum(n) AS a_reads FROM lab_counters WHERE tag='x';"
B "SELECT sum(n) AS b_reads FROM lab_counters WHERE tag='x';"
sleep 2
A "INSERT INTO lab_counters(tag,n) SELECT 'y', 100;"
B "INSERT INTO lab_counters(tag,n) SELECT 'y', 200;"
sleep 2
A "COMMIT;"
sleep 2
printf -- '--- A committed; B now commits into a conflicting snapshot\n' >> "$OUT"
B "COMMIT;"
sleep 3

# =============================================================================
say "DEMO 8 — FOR UPDATE vs FOR UPDATE SKIP LOCKED (the queue pattern)"

A "BEGIN;"
A "SELECT id, tag FROM lab_counters ORDER BY id LIMIT 2 FOR UPDATE;"
sleep 2
B "BEGIN;"
B "SELECT id, tag FROM lab_counters ORDER BY id LIMIT 2 FOR UPDATE SKIP LOCKED;"
sleep 3
printf -- '--- B skipped A-locked rows instead of blocking. Now try WITHOUT skip locked:\n' >> "$OUT"
B "COMMIT;"
sleep 1
B "BEGIN;"
B "SELECT id, tag FROM lab_counters ORDER BY id LIMIT 2 FOR UPDATE;"
sleep 3
obs "B should now be blocked" \
"SELECT pid, state, wait_event_type, wait_event, left(query,50) AS query
   FROM pg_stat_activity WHERE datname='dubai_re' AND wait_event_type='Lock';"
A "COMMIT;"
sleep 2
B "COMMIT;"
sleep 1

# =============================================================================
say "DEMO 9 — ADVISORY LOCKS (application-level mutex, no row required)"

A "SELECT pg_advisory_lock(42) AS a_took_the_lock;"
sleep 2
B "SELECT pg_try_advisory_lock(42) AS b_tries_nonblocking;"
sleep 2
A "SELECT pg_advisory_unlock(42) AS a_released;"
sleep 2
B "SELECT pg_try_advisory_lock(42) AS b_tries_again;"
B "SELECT pg_advisory_unlock(42);"
sleep 2

# =============================================================================
say "DEMO 10 — MVCC: xmin / xmax / ctid and the bloat an UPDATE leaves behind"

obs "row versions are visible in system columns" \
"SELECT ctid, xmin, xmax, transaction_id, actual_worth
   FROM raw_transactions WHERE transaction_id='LAB-X-1';"
obs "update it -> new tuple version at a new ctid" \
"UPDATE raw_transactions SET actual_worth = 777 WHERE transaction_id='LAB-X-1'
 RETURNING ctid, xmin, xmax, actual_worth;"
obs "dead tuples now accounted for" \
"SELECT n_live_tup, n_dead_tup, last_autovacuum
   FROM pg_stat_user_tables WHERE relname='raw_transactions';"

# =============================================================================
say "CLEANUP"
A "\\q"
B "\\q"
exec 3>&-
exec 4>&-
sleep 2
PSQL_ONE "DELETE FROM raw_transactions WHERE transaction_id LIKE 'LAB-%';" >> "$OUT"
PSQL_ONE "DROP TABLE IF EXISTS lab_counters;" >> "$OUT"
PSQL_ONE "SELECT count(*) AS final_row_count FROM raw_transactions;" >> "$OUT"

# ---- fold the session transcripts in -----------------------------------------
{
  printf '\n\n############### SESSION A TRANSCRIPT ###############\n'; cat "$DIR/A.out"
  printf '\n\n############### SESSION B TRANSCRIPT ###############\n'; cat "$DIR/B.out"
} >> "$OUT"

rm -f "$DIR/A.fifo" "$DIR/B.fifo"
echo "DONE -> $OUT"
