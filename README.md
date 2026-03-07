# Dubai Real Estate Market Intelligence Platform

> End-to-end data platform processing Dubai Land Department transactions.
> One `docker compose up` boots the full stack: Airflow, Spark, FastAPI, and Kepler GL.

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Orchestration | Docker Compose | Central platform orchestration, service networking, health checks |
| Pipeline | Apache Airflow 2.x | DAG scheduling, task dependencies, retry logic |
| Processing | PySpark | Distributed transformation of property transactions |
| Storage | PostgreSQL 16, Parquet | Analytics tables, intermediate datasets |
| API | FastAPI, Pydantic | REST endpoints with auto-generated OpenAPI docs |
| Visualization | Kepler GL | Interactive geospatial map with time animation |

## Architecture

```
┌─────────────────────────────── docker compose ───────────────────────────────┐
│                                                                              │
│  ┌──────────┐    triggers    ┌──────────────┐    writes    ┌──────────┐     │
│  │ Airflow  │───────────────>│ Spark Master │─────────────>│ Postgres │     │
│  │ :8080    │                │ + Workers    │              │ :5432    │     │
│  └──────────┘                └──────────────┘              └────┬─────┘     │
│                                                                 │           │
│                                                            reads│           │
│                                                                 v           │
│                              ┌──────────┐    fetches    ┌──────────┐        │
│                              │ Kepler   │──────────────>│ FastAPI  │        │
│                              │ :3000    │               │ :8000    │        │
│                              └──────────┘               └──────────┘        │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

Prerequisites: Docker and Docker Compose.

```bash
git clone https://github.com/lfcruz2/dubai-real-estate-platform.git
cd dubai-real-estate-platform
cp .env.example .env
docker compose up -d postgres    # Boots the database
```

## Current Phase: Foundation

The project is being built incrementally. Each phase adds services to Docker Compose.

**Phase 1 (current):** PostgreSQL with schema, sample data, and seed tooling.

```bash
docker compose up -d postgres                        # Start database
docker compose --profile tools run --rm seed          # Load sample data
```

| Service | URL | Status |
|---------|-----|--------|
| PostgreSQL | localhost:5432 | Available |
| Airflow UI | http://localhost:8080 | Planned |
| Spark Master UI | http://localhost:8081 | Planned |
| FastAPI Docs | http://localhost:8000/docs | Planned |
| Kepler GL Map | http://localhost:3000 | Planned |

## Development

```bash
make up        # Start available services
make seed      # Load sample data into Postgres
make down      # Stop all services
make clean     # Stop everything and wipe volumes
```

## Data Source

Dubai Land Department open data via Dubai Pulse.

## License

MIT
