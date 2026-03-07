import os


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://dubai_user:dubai_pass@localhost:5432/dubai_re",
)

# Sync URL for ingestion (psycopg2 doesn't support asyncpg://)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "").replace(
    "postgresql://", "postgresql://"
)
