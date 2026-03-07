# Changelog

## v0.1.0 - Foundation (2026-03-07)

### Added
- Docker Compose with PostgreSQL 16 service, health check, named volume and network
- Database schema for 3 DLD datasets: raw_transactions, raw_rent_contracts, raw_valuations
- Analytics table (area_trends) and ingestion tracking (upload_log)
- Ingestion script with CSV auto-detection, null normalization, and deduplication
- Seed profile container for loading data from raw_source/
- Makefile with docker compose wrappers
- Project documentation: architecture, data model
