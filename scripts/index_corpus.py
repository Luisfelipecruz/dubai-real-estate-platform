"""Chunk, embed and upsert the corpus. Incremental by content hash.

    corpus.jsonl  ->  chunk (api/services/chunking.py)
                  ->  hash
                  ->  diff against doc_chunks
                  ->  embed ONLY what changed
                  ->  upsert

The hash is what makes this a diff rather than a rebuild. Embedding is the only
expensive step -- a full pass over the corpus is thousands of forward passes on CPU --
and editing one paragraph of one document should not pay for all of them.

Three outcomes per source, and all three are reported:

    inserted   hash not present. Embedded and written.
    skipped    hash already present. Not embedded. Its chunk_index is refreshed,
               because inserting or deleting a sibling chunk shifts the ordinals of
               every chunk after it even though their text is untouched.
    deleted    hash present in the table but no longer produced. Removed, or the index
               keeps serving text that no longer exists in the source.

Usage:
    python index_corpus.py --corpus /app/corpus/corpus.jsonl
    python index_corpus.py --corpus /app/corpus/corpus.jsonl --dry-run
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg2
from psycopg2.extras import execute_batch

sys.path.insert(0, "/app")  # api/ is mounted here; services.chunking lives under it
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from services.chunking import (  # noqa: E402
    Chunk,
    chunk_area_sheet,
    chunk_markdown,
    chunk_note,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dubai_user:dubai_pass@localhost:5432/dubai_re",
)
EMBEDDINGS_URL = os.environ.get("EMBEDDINGS_URL", "http://embeddings:8100")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

# Forward passes are batched, but the batch is bounded: the request body is JSON and a
# 512-batch of 512-token chunks is a multi-megabyte POST for no throughput gain on CPU.
EMBED_BATCH = 64


def chunk_record(record: dict) -> list[Chunk]:
    """Dispatch to the strategy for this source type."""
    source_type = record["source_type"]
    text = record["text"]
    source_id = record["source_id"]

    if source_type == "doc":
        return chunk_markdown(text, source_id)
    if source_type == "area_sheet":
        return chunk_area_sheet(text, source_id)
    if source_type == "note":
        return chunk_note(
            text, source_id, record.get("meta", {}).get("area_name", "unknown")
        )
    raise ValueError(f"unknown source_type {source_type!r}")


def embed_batch(client: httpx.Client, texts: list[str]) -> tuple[list[list[float]], list[int]]:
    resp = client.post(
        f"{EMBEDDINGS_URL}/embed",
        json={"texts": texts, "kind": "document"},
        timeout=300.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    if payload["model"] != EMBEDDING_MODEL:
        raise SystemExit(
            f"FATAL: embeddings service is serving {payload['model']!r} but this "
            f"indexer is configured for {EMBEDDING_MODEL!r}. Writing these vectors "
            f"would poison the index with a second, incomparable vector space."
        )

    for text, was_truncated, count in zip(
        texts, payload["truncated"], payload["token_counts"], strict=True
    ):
        if was_truncated:
            # Loud on purpose. Truncation is silent at every other layer: the vector is
            # returned, the row is written, retrieval returns it, and only the tail of
            # the chunk is unfindable. Oversized fenced code blocks are the expected
            # cause -- chunking.py emits them whole rather than cutting a statement in
            # half, and the lexical arm still indexes the full text.
            print(
                f"  WARNING: truncated at the model's sequence limit "
                f"({count} tokens): {text[:70]!r}...",
                file=sys.stderr,
            )

    return payload["embeddings"], payload["token_counts"]


def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


def sources_to_prune(indexed_keys, corpus_keys):
    """Which (source_type, source_id) pairs are in the index but no longer in the corpus.

    Extracted from the indexing loop so the decision can be asserted without a database.
    The bug it replaced was structural rather than arithmetic -- the loop only ever
    visited sources present in the corpus file, so a source that disappeared completely
    was never considered -- but the safety rule below is the part worth pinning in a test.

    AN EMPTY CORPUS PRUNES NOTHING. `build_corpus.py` failing produces a file with no
    documents, and pruning against that would delete the entire index while reporting
    success. An empty corpus and a failed build are indistinguishable from here, so the
    destructive reading is refused. `--force` remains the way to ask for a full rebuild.
    """
    if not corpus_keys:
        return set()
    return set(indexed_keys) - set(corpus_keys)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="/app/corpus/corpus.jsonl")
    ap.add_argument("--source-type", choices=["doc", "area_sheet", "note"])
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the diff without embedding or writing anything.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Drop every chunk for the configured model first, so nothing is skipped. "
        "The honest full-rebuild baseline the incremental path is measured against, "
        "and the required move after changing the chunker or the embedding model.",
    )
    args = ap.parse_args()

    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"ERROR: corpus not found: {corpus_path}", file=sys.stderr)
        print("Run scripts/build_corpus.py first (make corpus).", file=sys.stderr)
        return 1

    records = [json.loads(line) for line in corpus_path.read_text().splitlines() if line.strip()]
    if args.source_type:
        records = [r for r in records if r["source_type"] == args.source_type]

    started = time.perf_counter()
    chunks_by_source: dict[tuple[str, str], list[Chunk]] = {}
    for record in records:
        key = (record["source_type"], record["source_id"])
        chunks_by_source[key] = chunk_record(record)
    total_chunks = sum(len(v) for v in chunks_by_source.values())
    chunk_ms = int((time.perf_counter() - started) * 1000)

    print(f"corpus      : {len(records)} documents -> {total_chunks} chunks ({chunk_ms} ms)")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    inserted = skipped = deleted = reordered = 0
    pending: list[tuple[Chunk, tuple[str, str]]] = []

    try:
        with conn.cursor() as cur:
            if args.force and not args.dry_run:
                cur.execute(
                    "DELETE FROM doc_chunks WHERE embedding_model = %s",
                    (EMBEDDING_MODEL,),
                )
                deleted += cur.rowcount
                print(f"force       : dropped {cur.rowcount} existing chunks")

            for key, chunks in chunks_by_source.items():
                source_type, source_id = key
                cur.execute(
                    "SELECT content_hash, chunk_index FROM doc_chunks "
                    " WHERE source_type = %s AND source_id = %s AND embedding_model = %s",
                    (source_type, source_id, EMBEDDING_MODEL),
                )
                existing = dict(cur.fetchall())
                produced = {c.content_hash: c for c in chunks}

                stale = set(existing) - set(produced)
                if stale:
                    cur.execute(
                        "DELETE FROM doc_chunks WHERE source_type = %s AND source_id = %s "
                        "  AND content_hash = ANY(%s)",
                        (source_type, source_id, list(stale)),
                    )
                    deleted += cur.rowcount

                for chunk in chunks:
                    if chunk.content_hash in existing:
                        skipped += 1
                        if existing[chunk.content_hash] != chunk.chunk_index:
                            cur.execute(
                                "UPDATE doc_chunks SET chunk_index = %s "
                                " WHERE source_type = %s AND source_id = %s "
                                "   AND content_hash = %s",
                                (chunk.chunk_index, source_type, source_id,
                                 chunk.content_hash),
                            )
                            reordered += 1
                    else:
                        pending.append((chunk, key))

            # ── sources that vanished ENTIRELY ─────────────────────────────
            #
            # The loop above only ever visits sources that are IN the corpus file, so a
            # source that disappeared completely was never looked at and its chunks were
            # never deleted. They stayed in doc_chunks and kept being retrieved.
            #
            # Found by m14's prompt-injection test, which is the only reason it surfaced:
            # a note was POSTed, indexed, attacked, then DELETEd -- and the deleted note
            # was still answering questions on the next `make index`. That is worse than
            # a stale row. `POST /notes` is user-writable, so "delete" that leaves the
            # content live and quotable is a data-deletion failure, not untidiness.
            # The same hole covers a deleted document and an area sheet that drops below
            # the 10-record floor.
            #
            # `--source-type` restricts the scan, or a partial run would prune everything
            # it was told not to look at.
            orphaned = 0
            if not chunks_by_source:
                print(
                    "prune       : SKIPPED - the corpus file has no documents at all. "
                    "That is a build failure, not an empty corpus; nothing was removed."
                )
            else:
                scope = "AND source_type = %s" if args.source_type else ""
                params = [EMBEDDING_MODEL] + (
                    [args.source_type] if args.source_type else []
                )
                cur.execute(
                    f"SELECT DISTINCT source_type, source_id FROM doc_chunks "
                    f" WHERE embedding_model = %s {scope}",
                    params,
                )
                orphans = sources_to_prune(cur.fetchall(), chunks_by_source)
                for source_type, source_id in sorted(orphans):
                    cur.execute(
                        "DELETE FROM doc_chunks "
                        " WHERE source_type = %s AND source_id = %s "
                        "   AND embedding_model = %s",
                        (source_type, source_id, EMBEDDING_MODEL),
                    )
                    orphaned += cur.rowcount
                    print(f"prune       : {source_type}/{source_id} -> -{cur.rowcount}")
                deleted += orphaned

            print(
                f"diff        : {len(pending)} to embed, {skipped} unchanged, "
                f"{deleted} stale removed ({orphaned} from vanished sources), "
                f"{reordered} re-ordered"
            )

            if args.dry_run:
                conn.rollback()
                print("\ndry run - nothing written")
                return 0

            if pending:
                embed_started = time.perf_counter()
                with httpx.Client() as client:
                    for start in range(0, len(pending), EMBED_BATCH):
                        batch = pending[start : start + EMBED_BATCH]
                        vectors, token_counts = embed_batch(
                            client, [c.embed_text for c, _ in batch]
                        )
                        rows = [
                            (
                                source_type,
                                source_id,
                                chunk.chunk_index,
                                chunk.heading_path,
                                chunk.content,
                                chunk.content_hash,
                                token_count,
                                EMBEDDING_MODEL,
                                to_pgvector(vector),
                            )
                            for (chunk, (source_type, source_id)), vector, token_count
                            in zip(batch, vectors, token_counts, strict=True)
                        ]
                        execute_batch(
                            cur,
                            """
                            INSERT INTO doc_chunks (
                                source_type, source_id, chunk_index, heading_path,
                                content, content_hash, token_count, embedding_model,
                                embedding
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                            ON CONFLICT (source_type, source_id, content_hash)
                            DO UPDATE SET chunk_index  = EXCLUDED.chunk_index,
                                          heading_path = EXCLUDED.heading_path,
                                          generated_at = now()
                            """,
                            rows,
                            page_size=EMBED_BATCH,
                        )
                        inserted += len(rows)
                        print(
                            f"  embedded {inserted}/{len(pending)}"
                            f" ({int((time.perf_counter() - embed_started) * 1000)} ms)"
                        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    total_ms = int((time.perf_counter() - started) * 1000)
    print(
        f"\nindexed     : +{inserted} embedded, {skipped} skipped, -{deleted} removed"
        f"  in {total_ms} ms"
    )
    if skipped and not inserted and not deleted:
        print("corpus unchanged - no vectors were recomputed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
