-- Dubai Real Estate Platform - Database Schema
-- Runs automatically on first postgres boot via docker-entrypoint-initdb.d
-- Tables match DLD CSV exports from data.dubai

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
    yoy_price_change NUMERIC(6,2),
    UNIQUE(area_name_en, year, quarter, dataset)
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

-- ── Indexes ──────────────────────────────────────────────────────

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
