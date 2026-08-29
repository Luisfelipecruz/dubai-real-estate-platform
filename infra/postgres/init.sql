-- Dubai Real Estate Platform - Database Schema
-- Runs automatically on first postgres boot via docker-entrypoint-initdb.d
-- Tables match DLD CSV exports from data.dubai

-- ── Extensions ───────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS postgis;

-- pgvector. Requires the custom image in infra/postgres/Dockerfile -- the stock
-- postgis/postgis:16-3.4 image does not carry the extension and this line fails
-- against it. Note that docker-entrypoint-initdb.d runs ONCE, on an empty data
-- directory: adding an extension here has no effect on a volume that already
-- exists. See docs/rag-corpus-design.md for the rebuild sequence.
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Raw Data Tables ──────────────────────────────────────────────

-- Transactions: sales, mortgages, gifts
CREATE TABLE IF NOT EXISTS raw_transactions (
    id SERIAL PRIMARY KEY,
    transaction_id VARCHAR(50) UNIQUE NOT NULL,
    instance_date DATE,
    procedure_name_en VARCHAR(100),
    trans_group_en VARCHAR(50),
    property_type_en VARCHAR(50),
    property_sub_type_en VARCHAR(100),
    property_usage_en VARCHAR(50),
    reg_type_en VARCHAR(50),
    area_id INT,
    area_name_en VARCHAR(100),
    building_name_en VARCHAR(200),
    project_name_en VARCHAR(200),
    master_project_en VARCHAR(200),
    rooms_en VARCHAR(50),
    procedure_area NUMERIC(14,2),
    actual_worth NUMERIC(18,2),
    meter_sale_price NUMERIC(12,2),
    meter_rent_price NUMERIC(12,2),
    has_parking BOOLEAN,
    nearest_metro_en VARCHAR(200),
    nearest_mall_en VARCHAR(200),
    nearest_landmark_en VARCHAR(200),
    no_of_parties_role_1 INT,
    no_of_parties_role_2 INT,
    no_of_parties_role_3 INT,
    load_timestamp TIMESTAMP,
    ingested_at TIMESTAMP DEFAULT NOW()
);

-- Rent Contracts: Ejari registration
CREATE TABLE IF NOT EXISTS raw_rent_contracts (
    id SERIAL PRIMARY KEY,
    contract_id VARCHAR(50) NOT NULL,
    line_number INT NOT NULL,
    UNIQUE(contract_id, line_number),
    contract_start_date DATE,
    contract_end_date DATE,
    contract_reg_type_en VARCHAR(50),
    contract_amount NUMERIC(18,2),
    annual_amount NUMERIC(18,2),
    ejari_property_type_en VARCHAR(100),
    ejari_property_sub_type_en VARCHAR(100),
    ejari_bus_property_type_en VARCHAR(50),
    property_usage_en VARCHAR(50),
    tenant_type_en VARCHAR(50),
    is_free_hold BOOLEAN,
    area_id INT,
    area_name_en VARCHAR(100),
    project_name_en VARCHAR(200),
    master_project_en VARCHAR(200),
    no_of_prop INT,
    actual_area NUMERIC(14,2),
    nearest_metro_en VARCHAR(200),
    nearest_mall_en VARCHAR(200),
    nearest_landmark_en VARCHAR(200),
    load_timestamp TIMESTAMP,
    ingested_at TIMESTAMP DEFAULT NOW()
);

-- Valuations: property evaluations
CREATE TABLE IF NOT EXISTS raw_valuations (
    id SERIAL PRIMARY KEY,
    procedure_number INT NOT NULL,
    instance_date TIMESTAMP NOT NULL,
    UNIQUE(procedure_number, instance_date),
    procedure_name_en VARCHAR(100),
    procedure_year INT,
    property_type_en VARCHAR(50),
    property_sub_type_en VARCHAR(100),
    area_id INT,
    area_name_en VARCHAR(100),
    procedure_area NUMERIC(14,2),
    actual_area NUMERIC(14,2),
    actual_worth NUMERIC(18,2),
    property_total_value NUMERIC(18,2),
    row_status_code VARCHAR(20),
    load_timestamp TIMESTAMP,
    ingested_at TIMESTAMP DEFAULT NOW()
);

-- ── Analytics Tables (populated by Spark) ────────────────────────

CREATE TABLE IF NOT EXISTS area_trends (
    id SERIAL PRIMARY KEY,
    area_id INT,
    area_name_en VARCHAR(100),
    year INT,
    quarter INT,
    dataset VARCHAR(20),
    avg_price_sqm NUMERIC(12,2),
    median_price NUMERIC(18,2),
    transaction_count INT,
    total_volume NUMERIC(20,2),
    dominant_property_type VARCHAR(50),
    yoy_price_change NUMERIC(10,2),
    UNIQUE(area_name_en, year, quarter, dataset)
);

CREATE TABLE IF NOT EXISTS rental_yields (
    id SERIAL PRIMARY KEY,
    area_name_en VARCHAR(100),
    year INT,
    quarter INT,
    avg_sale_price NUMERIC(18,2),
    avg_annual_rent NUMERIC(18,2),
    rental_yield_pct NUMERIC(6,2),
    transaction_count INT,
    rent_count INT,
    UNIQUE(area_name_en, year, quarter)
);

-- ── Quality Checks ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS quality_checks (
    id SERIAL PRIMARY KEY,
    check_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    dataset VARCHAR(20),
    status VARCHAR(10) NOT NULL,
    message TEXT,
    value NUMERIC(18,4),
    threshold NUMERIC(18,4),
    checked_at TIMESTAMP DEFAULT NOW(),
    run_id VARCHAR(50) NOT NULL
);

-- ── Ingestion Tracking ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS upload_log (
    id SERIAL PRIMARY KEY,
    dataset_type VARCHAR(20) NOT NULL,
    filename VARCHAR(255),
    uploaded_at TIMESTAMP DEFAULT NOW(),
    rows_received INT,
    rows_inserted INT,
    rows_duplicate INT,
    rows_rejected INT,
    status VARCHAR(20),
    error_details TEXT
);

-- ── Spatial Reference Data ───────────────────────────────────────

-- Dubai community boundaries, loaded from the DLD Community.kml export.
-- Replaces the hardcoded AREA_COORDS centroid dictionary that used to live
-- in api/routers/map_data.py: centroids are now derived with ST_Centroid.
CREATE TABLE IF NOT EXISTS communities (
    id SERIAL PRIMARY KEY,
    community_name_en VARCHAR(200) NOT NULL,
    community_name_norm VARCHAR(200) NOT NULL,  -- upper/trimmed, for joining to area_name_en
    community_number VARCHAR(50),
    geom geometry(MultiPolygon, 4326) NOT NULL,
    loaded_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (community_name_norm)
);

-- ── Indexes ──────────────────────────────────────────────────────

-- GiST over the geometry: turns the point-in-polygon scan into an index scan.
-- Capture EXPLAIN ANALYZE before and after creating this to see the difference.
CREATE INDEX idx_communities_geom ON communities USING GIST (geom);
CREATE INDEX idx_communities_name_norm ON communities(community_name_norm);

-- Functional index on the geography cast. Needed because ordering by distance in
-- real metres uses `geom::geography <-> point::geography`, and the geometry index
-- above cannot answer an operator on the geography type. Ordering by the geometry
-- `<->` instead would sort by planar degrees, which is not the same ordering at
-- Dubai's latitude.
CREATE INDEX idx_communities_geog ON communities USING GIST ((geom::geography));

CREATE INDEX idx_tx_area ON raw_transactions(area_name_en);
CREATE INDEX idx_tx_date ON raw_transactions(instance_date);
CREATE INDEX idx_tx_group ON raw_transactions(trans_group_en);
CREATE INDEX idx_tx_area_id ON raw_transactions(area_id);

CREATE INDEX idx_rent_area ON raw_rent_contracts(area_name_en);
CREATE INDEX idx_rent_start ON raw_rent_contracts(contract_start_date);
CREATE INDEX idx_rent_area_id ON raw_rent_contracts(area_id);

CREATE INDEX idx_val_area ON raw_valuations(area_name_en);
CREATE INDEX idx_val_date ON raw_valuations(instance_date);
CREATE INDEX idx_val_area_id ON raw_valuations(area_id);

CREATE INDEX idx_trends_area ON area_trends(area_name_en);
CREATE INDEX idx_trends_year ON area_trends(year, quarter);
CREATE INDEX idx_trends_dataset ON area_trends(dataset);

CREATE INDEX idx_yields_area ON rental_yields(area_name_en);
CREATE INDEX idx_yields_year ON rental_yields(year, quarter);

-- ── Retrieval Corpus (pgvector) ──────────────────────────────────

-- One row per chunk of retrievable TEXT. Deliberately not "the database, embedded":
-- transactions, rents and valuations stay in their typed columns and are answered by
-- SQL. Only three genuinely textual sources land here -- see docs/rag-corpus-design.md
-- for why a median price per m2 must never be answered from a vector index.
--
--   source_type = 'doc'         one chunk per section of docs/*.md
--   source_type = 'area_sheet'  one chunk per area, rendered from aggregates
--   source_type = 'note'        one chunk per analyst note in area_notes
CREATE TABLE IF NOT EXISTS doc_chunks (
    id              BIGSERIAL PRIMARY KEY,
    source_type     VARCHAR(20)  NOT NULL,
    source_id       VARCHAR(200) NOT NULL,
    chunk_index     INT          NOT NULL,
    -- 'changelog.md > v0.5.0 > The synthetic rent key'. Prepended to the embedded
    -- text so an isolated chunk keeps the context its position used to give it.
    heading_path    TEXT,
    content         TEXT         NOT NULL,
    -- sha256 of the content. Makes re-indexing a diff instead of a rebuild: a chunk
    -- whose hash is already present is skipped without being re-embedded.
    content_hash    CHAR(64)     NOT NULL,
    -- Token count as counted by the embedding model's own tokenizer and returned by
    -- the embeddings service -- not an estimate. The chunker uses a cheaper word-based
    -- approximation to pick boundaries; this column records what actually happened.
    token_count     INT          NOT NULL,
    -- Asserted at query time. Changing the embedding model invalidates every vector
    -- in this table, and a silent mismatch returns fluent nonsense rather than an
    -- error, so the model that produced each row is stored with it.
    embedding_model VARCHAR(80)  NOT NULL,
    embedding       vector(384)  NOT NULL,
    -- Heading path is folded into the lexical vector, not just the dense one. The
    -- identity tokens that dense retrieval loses -- 'v0.5.0', area names, column
    -- names -- live in headings at least as often as in body text.
    tsv             tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(heading_path, '') || ' ' || content)
                    ) STORED,
    generated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (source_type, source_id, content_hash)
);

-- HNSW over cosine distance. m=16 / ef_construction=64 are the pgvector defaults and
-- are kept on purpose.
--
-- Measured at the built corpus size of 295 chunks (docs/hybrid-retrieval-plans.md,
-- Experiment 1): this index is 3.5x FASTER than the sequential scan -- 0.131 ms and 340
-- buffers against 0.464 ms and 645 -- and the planner does not use it. pgvector prices
-- the HNSW descent at a startup cost of 302.21, five times the total cost of scanning
-- and sorting the entire table (69.27), so the seq scan wins the cost comparison it
-- loses on the clock. Expect the index to start being chosen somewhere near 1,500
-- chunks.
--
-- It is kept, at 600 kB, because it costs a millisecond per re-index and begins paying
-- on its own the moment the corpus grows. This is NOT the GiST outcome from
-- docs/postgis-query-plans.md, which it was expected to repeat: there the index really
-- was slower and the estimate was optimistic. Here it is faster and the estimate is
-- pessimistic. Both look like "small table, index not worth it" and they are not alike.
CREATE INDEX IF NOT EXISTS idx_chunks_hnsw ON doc_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Lexical half of hybrid retrieval. Not decoration: area names, CNT contract prefixes
-- and column names like meter_sale_price are identity tokens, and identity is exactly
-- what a 384-dimensional semantic space discards.
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON doc_chunks USING GIN (tsv);

CREATE INDEX IF NOT EXISTS idx_chunks_src ON doc_chunks (source_type, source_id);
