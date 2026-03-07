# Data Model

## Source: Dubai Land Department

Data downloaded from [data.dubai](https://data.dubai) > Data and Statistics > Dubai Land Department.

## Raw Tables

### raw_transactions

Sales, mortgages, and gift transactions.

| Column | Type | Notes |
|--------|------|-------|
| transaction_id | VARCHAR(50) | **Unique key**. Format: `1-41-2011-1593` |
| instance_date | DATE | Transaction date. Range: 1994-2026 |
| trans_group_en | VARCHAR(50) | Sales (77%), Mortgages (20%), Gifts (3%) |
| property_type_en | VARCHAR(50) | Unit, Villa, Land, Building |
| property_sub_type_en | VARCHAR(100) | Flat, Villa, Office, etc. (~12% null) |
| property_usage_en | VARCHAR(50) | Residential (84%), Commercial (11%), Hospitality |
| reg_type_en | VARCHAR(50) | Existing Properties (65%), Off-Plan (35%) |
| area_name_en | VARCHAR(100) | 152 unique areas |
| actual_worth | NUMERIC(18,2) | Transaction value in AED. Range: 9,766 - 2,000,000,000 |
| procedure_area | NUMERIC(14,2) | Size in sqm |
| meter_sale_price | NUMERIC(12,2) | Price per sqm (null for non-sale transactions) |
| rooms_en | VARCHAR(50) | 1 B/R, 2 B/R, Studio, etc. (~22% null) |

### raw_rent_contracts

Ejari rental contract registrations.

| Column | Type | Notes |
|--------|------|-------|
| contract_id | VARCHAR(50) | **Composite key** with line_number. Prefixes: CNT, CRT |
| line_number | INT | Line item within contract |
| contract_start_date | DATE | Range: 2010-2026 |
| contract_end_date | DATE | Range: 2011-2034 |
| contract_reg_type_en | VARCHAR(50) | New (52%), Renew (48%) |
| annual_amount | NUMERIC(18,2) | Annual rent in AED |
| ejari_property_type_en | VARCHAR(100) | Flat, Office, Labor Camps, Shop, Villa |
| tenant_type_en | VARCHAR(50) | Authority (52%), Person (48%) |
| is_free_hold | BOOLEAN | 37% freehold |
| area_name_en | VARCHAR(100) | 154 unique areas |

### raw_valuations

Property evaluations performed by DLD.

| Column | Type | Notes |
|--------|------|-------|
| procedure_number | INT | **Composite key** with instance_date |
| instance_date | TIMESTAMP | Evaluation date. Range: 2000-2026 |
| procedure_year | INT | Year of evaluation (2000-2026) |
| property_type_en | VARCHAR(50) | Land (70%), Unit (27%), Building (3%) |
| property_sub_type_en | VARCHAR(100) | Commercial, Residential, Flat, etc. |
| actual_worth | NUMERIC(18,2) | Assessed value in AED |
| row_status_code | VARCHAR(20) | COMPLETED (99.4%), COMMITTED, ENTERED |
| area_name_en | VARCHAR(100) | 179 unique areas |

## Analytics Tables

### area_trends (populated by Spark)

| Column | Type | Notes |
|--------|------|-------|
| area_name_en | VARCHAR(100) | Area name |
| year | INT | Year |
| quarter | INT | Quarter (1-4) |
| dataset | VARCHAR(20) | transactions, rents, valuations |
| avg_price_sqm | NUMERIC(12,2) | Average price per sqm |
| transaction_count | INT | Number of records |
| yoy_price_change | NUMERIC(6,2) | Year-over-year % change |

### upload_log

| Column | Type | Notes |
|--------|------|-------|
| dataset_type | VARCHAR(20) | transactions, rents, valuations |
| filename | VARCHAR(255) | Original CSV filename |
| rows_received | INT | Total rows in CSV |
| rows_inserted | INT | New rows inserted |
| rows_duplicate | INT | Rows skipped (already exist) |
| status | VARCHAR(20) | success, partial, failed |

## Cross-Dataset Join

All three datasets share `area_id` and `area_name_en`. 119 areas appear across all three datasets.

## Data Quality Notes

- DLD uses the string `"null"` instead of actual NULLs. The ingestion script normalizes these.
- Date formats differ between datasets (DATE vs TIMESTAMP). Normalized on ingestion.
- `has_parking` and `is_free_hold` are stored as `"0"`/`"1"` strings in CSVs. Converted to boolean.
- Some rent contracts have suspiciously low values (1 AED). These are kept as-is for transparency.
