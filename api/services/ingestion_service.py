"""Wraps scripts/ingest.py for use from FastAPI."""

import io
import tempfile
import asyncio

import psycopg2

from config import DATABASE_URL


# The sync DATABASE_URL for psycopg2 (strip +asyncpg if present)
SYNC_DB_URL = DATABASE_URL.replace("+asyncpg", "")


def _ingest_csv_sync(file_bytes: bytes, filename: str) -> dict:
    """Run ingestion synchronously (called in a thread pool)."""
    # Import ingest functions from scripts/
    import sys
    import os

    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from ingest import ingest_file

    # Write bytes to a temp file so ingest_file can read it as CSV
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as f:
        f.write(file_bytes)
        temp_path = f.name

    try:
        conn = psycopg2.connect(SYNC_DB_URL)
        result = ingest_file(temp_path, conn, override_filename=filename)
        conn.close()
    finally:
        os.unlink(temp_path)

    return result


async def ingest_csv(file_bytes: bytes, filename: str) -> dict:
    """Run ingestion in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _ingest_csv_sync, file_bytes, filename)
