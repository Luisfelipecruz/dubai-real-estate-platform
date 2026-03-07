.PHONY: up down logs seed test clean

up:                                ## Start all available services
	docker compose up -d

down:                              ## Stop all services
	docker compose down

logs:                              ## Tail all service logs
	docker compose logs -f

seed:                              ## Ingest CSVs from raw_source/ into Postgres
	docker compose --profile tools run --rm seed

test:                              ## Run test suite in container
	docker compose --profile tools run --rm test

clean:                             ## Stop everything and wipe volumes
	docker compose down -v --remove-orphans
