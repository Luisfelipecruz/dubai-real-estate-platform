# Architecture

## Overview

The platform processes Dubai Land Department open data through a pipeline that starts with manual CSV upload and ends with queryable analytics and geospatial visualization.

## Data Flow

```
CSV Upload (raw_source/)
    |
    v
Ingestion Script (scripts/ingest.py)
    - Auto-detect dataset type from column headers
    - Normalize "null" strings to actual NULLs
    - Convert types (dates, booleans, numerics)
    - INSERT ... ON CONFLICT DO NOTHING (dedup)
    |
    v
PostgreSQL (raw tables)
    - raw_transactions (dedup: transaction_id)
    - raw_rent_contracts (dedup: contract_id + line_number)
    - raw_valuations (dedup: procedure_number + instance_date)
    - upload_log (ingestion tracking)
    |
    v
PySpark Aggregation (planned)
    - Quarterly price/volume trends per area
    - Cross-dataset rental yield analysis
    |
    v
area_trends table
    |
    v
FastAPI (planned) --> Next.js Dashboard + Kepler GL Map (planned)
```

## Design Decisions

### CSV Upload Instead of API Polling

The DLD portal provides CSV downloads but no stable public API. Rather than building brittle scrapers, the platform accepts manual CSV uploads and handles deduplication automatically. This is more reliable and mirrors how organizations actually receive government data updates.

### Deduplication at Ingestion

Each dataset has a natural unique key identified from the data:
- Transactions: `transaction_id` is unique across all 5000 rows
- Rent Contracts: `contract_id` + `line_number` (contracts can have multiple line items)
- Valuations: `procedure_number` + `instance_date` (same procedure can be re-evaluated)

Using `ON CONFLICT DO NOTHING` means re-uploading the same file is safe and fast.

### Docker Compose as Orchestration Spine

Every service runs through `docker compose`. A reviewer can clone the repo, run `docker compose up`, and see the platform running without installing Python, Java, Spark, or Node locally.
