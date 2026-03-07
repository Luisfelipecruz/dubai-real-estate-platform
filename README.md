# Dubai Real Estate Market Intelligence Platform

> End-to-end data platform processing Dubai Land Department transactions, rent contracts, and property valuations.
> Docker Compose orchestrates the full stack. Upload CSVs, deduplicate automatically, query via API, visualize on a map.

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Orchestration | Docker Compose | Central platform orchestration, service networking, health checks |
| Storage | PostgreSQL 16 | Raw data, analytics tables, ingestion tracking |
| Ingestion | Python (pandas, psycopg2) | CSV auto-detection, null normalization, deduplication |
| API | FastAPI, Pydantic | REST endpoints with auto-generated OpenAPI docs |
| Frontend | Next.js, shadcn/ui | Upload interface, data dashboard, area analytics |
| Pipeline | Apache Airflow 2.x | DAG scheduling for aggregation jobs |
| Processing | PySpark | Distributed aggregation across datasets |
| Visualization | Kepler GL | Interactive geospatial map with time animation |

## Architecture

```
┌──────────────────────────────── docker compose ────────────────────────────────┐
│                                                                                │
│  ┌────────────┐  uploads CSV   ┌──────────┐  reads/writes  ┌──────────┐      │
│  │  Next.js   │───────────────>│ FastAPI  │───────────────>│ Postgres │      │
│  │  :3000     │  fetches data  │ :8000    │                │ :5432    │      │
│  │            │<───────────────│          │                │          │      │
│  └────────────┘                └──────────┘                └────┬─────┘      │
│                                                                 │            │
│  ┌──────────┐    triggers    ┌──────────────┐    writes         │            │
│  │ Airflow  │───────────────>│ Spark Master │──────────────────>│            │
│  │ :8080    │                │ + Workers    │                                │
│  └──────────┘                └──────────────┘                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data Sources

Three CSV datasets from [Dubai Land Department](https://dubailand.gov.ae/en/open-data/real-estate-data/) via [data.dubai](https://data.dubai):

| Dataset | Unique Key | Content |
|---------|-----------|---------|
| Transactions | `transaction_id` | Sales, mortgages, gifts with property details and amounts |
| Rent Contracts | `contract_id` + `line_number` | Ejari rental registrations with annual amounts |
| Valuations | `procedure_number` + `instance_date` | Property evaluations with assessed values |

All three datasets share `area_id` / `area_name_en` as a join key (119+ common areas).

## Quick Start

Prerequisites: Docker and Docker Compose.

```bash
git clone https://github.com/lfcruz2/dubai-real-estate-platform.git
cd dubai-real-estate-platform
cp .env.example .env
docker compose up -d postgres          # Boot the database
```

### Loading Data

1. Download CSVs from the [DLD open data portal](https://dubailand.gov.ae/en/open-data/real-estate-data/)
2. Place them in `raw_source/`
3. Run the ingestion:

```bash
make seed
```

The ingestion script auto-detects the dataset type, normalizes null values, and deduplicates using each dataset's unique key. Re-uploading the same file inserts 0 new rows.

## Project Status

| Milestone | Status |
|-----------|--------|
| PostgreSQL foundation + schema | Done |
| Ingestion with deduplication | Done |
| FastAPI + upload endpoint | Planned |
| Next.js upload interface + dashboard | Planned |
| Airflow + Spark aggregations | Planned |
| Quality gates | Planned |
| Kepler GL geospatial map | Planned |
| CI/CD + polish | Planned |

## Services

| Service | URL | Status |
|---------|-----|--------|
| PostgreSQL | localhost:5432 | Available |
| FastAPI Docs | http://localhost:8000/docs | Planned |
| Next.js App | http://localhost:3000 | Planned |
| Airflow UI | http://localhost:8080 | Planned |
| Spark Master UI | http://localhost:8081 | Planned |

## Development

```bash
make up        # Start all available services
make seed      # Ingest CSVs from raw_source/ into Postgres
make test      # Run test suite in container
make down      # Stop all services
make logs      # Tail all service logs
make clean     # Stop everything and wipe volumes
```

## License

MIT
