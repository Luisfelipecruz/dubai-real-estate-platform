# Postgres 16 with BOTH PostGIS and pgvector.
#
# Neither published image has both. `postgis/postgis:16-3.4` ships PostGIS and no
# vector type; `pgvector/pgvector:pg16` ships the vector type and no PostGIS. Six
# endpoints and the entire map layer depend on PostGIS, so swapping the base is not
# an option -- the combined image is built here instead.
#
# pgvector is installed from the PGDG apt repository that the base image already
# configures, rather than compiled from source. Same artefact upstream publishes,
# and the build takes seconds rather than pulling in build-essential and the
# postgresql-server-dev headers for a from-source `make install`.
#
# `postgresql-16-pgvector` tracks the 0.8.x series. Pinning the exact patch is left
# to apt deliberately: pgvector 0.8 has not broken the `vector` type or the HNSW
# operator classes across patch releases, and an over-tight pin here fails the build
# on a machine whose apt mirror has rotated the old version out.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
