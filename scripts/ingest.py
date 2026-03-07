"""
Ingest DLD CSV files into Postgres with auto-detection, null normalization,
and deduplication.

Usage:
    python ingest.py /path/to/csv/directory/
    python ingest.py /path/to/single_file.csv
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dubai_user:dubai_pass@localhost:5432/dubai_re",
)

# Columns that identify each dataset type
DATASET_SIGNATURES = {
    "transactions": {"transaction_id", "trans_group_en"},
    "rents": {"contract_id", "ejari_property_type_en"},
    "valuations": {"procedure_number", "property_total_value"},
}

# Columns to keep per dataset (CSV column -> DB column)
TRANSACTION_COLUMNS = {
    "transaction_id": "transaction_id",
    "instance_date": "instance_date",
    "procedure_name_en": "procedure_name_en",
    "trans_group_en": "trans_group_en",
    "property_type_en": "property_type_en",
    "property_sub_type_en": "property_sub_type_en",
    "property_usage_en": "property_usage_en",
    "reg_type_en": "reg_type_en",
    "area_id": "area_id",
    "area_name_en": "area_name_en",
    "building_name_en": "building_name_en",
    "project_name_en": "project_name_en",
    "master_project_en": "master_project_en",
    "rooms_en": "rooms_en",
    "procedure_area": "procedure_area",
    "actual_worth": "actual_worth",
    "meter_sale_price": "meter_sale_price",
    "meter_rent_price": "meter_rent_price",
    "has_parking": "has_parking",
    "nearest_metro_en": "nearest_metro_en",
    "nearest_mall_en": "nearest_mall_en",
    "nearest_landmark_en": "nearest_landmark_en",
    "no_of_parties_role_1": "no_of_parties_role_1",
    "no_of_parties_role_2": "no_of_parties_role_2",
    "no_of_parties_role_3": "no_of_parties_role_3",
    "load_timestamp": "load_timestamp",
}

RENT_COLUMNS = {
    "contract_id": "contract_id",
    "line_number": "line_number",
    "contract_start_date": "contract_start_date",
    "contract_end_date": "contract_end_date",
    "contract_reg_type_en": "contract_reg_type_en",
    "contract_amount": "contract_amount",
    "annual_amount": "annual_amount",
    "ejari_property_type_en": "ejari_property_type_en",
    "ejari_property_sub_type_en": "ejari_property_sub_type_en",
    "ejari_bus_property_type_en": "ejari_bus_property_type_en",
    "property_usage_en": "property_usage_en",
    "tenant_type_en": "tenant_type_en",
    "is_free_hold": "is_free_hold",
    "area_id": "area_id",
    "area_name_en": "area_name_en",
    "project_name_en": "project_name_en",
    "master_project_en": "master_project_en",
    "no_of_prop": "no_of_prop",
    "actual_area": "actual_area",
    "nearest_metro_en": "nearest_metro_en",
    "nearest_mall_en": "nearest_mall_en",
    "nearest_landmark_en": "nearest_landmark_en",
    "load_timestamp": "load_timestamp",
}

VALUATION_COLUMNS = {
    "procedure_number": "procedure_number",
    "instance_date": "instance_date",
    "procedure_name_en": "procedure_name_en",
    "procedure_year": "procedure_year",
    "property_type_en": "property_type_en",
    "property_sub_type_en": "property_sub_type_en",
    "area_id": "area_id",
    "area_name_en": "area_name_en",
    "procedure_area": "procedure_area",
    "actual_area": "actual_area",
    "actual_worth": "actual_worth",
    "property_total_value": "property_total_value",
    "row_status_code": "row_status_code",
    "load_timestamp": "load_timestamp",
}

DATASET_CONFIG = {
    "transactions": {
        "table": "raw_transactions",
        "columns": TRANSACTION_COLUMNS,
        "conflict_key": "transaction_id",
        "bool_columns": ["has_parking"],
        "date_columns": ["instance_date"],
        "timestamp_columns": ["load_timestamp"],
        "int_columns": [
            "area_id", "no_of_parties_role_1",
            "no_of_parties_role_2", "no_of_parties_role_3",
        ],
        "numeric_columns": [
            "procedure_area", "actual_worth",
            "meter_sale_price", "meter_rent_price",
        ],
    },
    "rents": {
        "table": "raw_rent_contracts",
        "columns": RENT_COLUMNS,
        "conflict_key": "contract_id, line_number",
        "bool_columns": ["is_free_hold"],
        "date_columns": ["contract_start_date", "contract_end_date"],
        "timestamp_columns": ["load_timestamp"],
        "int_columns": ["area_id", "line_number", "no_of_prop"],
        "numeric_columns": ["contract_amount", "annual_amount", "actual_area"],
    },
    "valuations": {
        "table": "raw_valuations",
        "columns": VALUATION_COLUMNS,
        "conflict_key": "procedure_number, instance_date",
        "bool_columns": [],
        "date_columns": [],
        "timestamp_columns": ["instance_date", "load_timestamp"],
        "int_columns": ["procedure_number", "procedure_year", "area_id"],
        "numeric_columns": [
            "procedure_area", "actual_area",
            "actual_worth", "property_total_value",
        ],
    },
}


def detect_dataset(columns: list[str]) -> str | None:
    col_set = set(columns)
    for dataset_type, signature in DATASET_SIGNATURES.items():
        if signature.issubset(col_set):
            return dataset_type
    return None


def normalize_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Replace 'null' strings and empty strings with None."""
    df = df.replace({"null": None, "": None})
    return df


def convert_types(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Convert columns to appropriate types."""
    for col in config["bool_columns"]:
        if col in df.columns:
            df[col] = df[col].map({"1": True, "0": False, 1: True, 0: False})

    for col in config["date_columns"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    for col in config["timestamp_columns"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in config["int_columns"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            # Convert to Python int to avoid numpy int64 overflow in psycopg2
            df[col] = df[col].apply(
                lambda x: int(x) if pd.notna(x) else None
            )

    for col in config["numeric_columns"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            # Convert to Python float to avoid numpy type issues in psycopg2
            df[col] = df[col].apply(
                lambda x: float(x) if pd.notna(x) else None
            )

    return df


def ingest_file(filepath: str, conn) -> dict:
    """Ingest a single CSV file. Returns stats dict."""
    filename = os.path.basename(filepath)
    print(f"\nProcessing: {filename}")

    df = pd.read_csv(filepath, dtype=str)
    rows_received = len(df)
    print(f"  Rows read: {rows_received}")

    dataset_type = detect_dataset(df.columns.tolist())
    if dataset_type is None:
        print(f"  ERROR: Unrecognized CSV format. Skipping.")
        return {
            "dataset_type": "unknown",
            "filename": filename,
            "rows_received": rows_received,
            "rows_inserted": 0,
            "rows_duplicate": 0,
            "rows_rejected": rows_received,
            "status": "failed",
            "error": "Unrecognized CSV format",
        }

    print(f"  Detected: {dataset_type}")
    config = DATASET_CONFIG[dataset_type]

    # Select and rename columns
    available_cols = {k: v for k, v in config["columns"].items() if k in df.columns}
    df = df[list(available_cols.keys())].rename(columns=available_cols)

    # Normalize nulls and convert types
    df = normalize_nulls(df)
    df = convert_types(df, config)

    # Replace NaN/NaT with None for psycopg2
    df = df.where(df.notna(), None)

    # Build insert query with ON CONFLICT DO NOTHING
    db_columns = list(df.columns)
    table = config["table"]
    conflict = config["conflict_key"]

    col_names = ", ".join(db_columns)
    placeholders = ", ".join(["%s"] * len(db_columns))
    query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO NOTHING"

    # Convert to list of tuples with Python native types
    def to_native(val):
        if val is None:
            return None
        # Handle NaN/NaT (pandas/numpy missing values)
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            pass
        if hasattr(val, "item"):
            return val.item()
        if isinstance(val, pd.Timestamp):
            return val.to_pydatetime()
        return val

    values = [
        tuple(to_native(v) for v in row)
        for row in df.itertuples(index=False, name=None)
    ]

    # Count existing rows before insert
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count_before = cursor.fetchone()[0]

    try:
        cursor.executemany(query, values)
        conn.commit()

        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count_after = cursor.fetchone()[0]
        rows_inserted = count_after - count_before
    except Exception as e:
        conn.rollback()
        print(f"  ERROR: {e}")
        return {
            "dataset_type": dataset_type,
            "filename": filename,
            "rows_received": rows_received,
            "rows_inserted": 0,
            "rows_duplicate": 0,
            "rows_rejected": rows_received,
            "status": "failed",
            "error": str(e),
        }

    rows_duplicate = rows_received - rows_inserted
    status = "success" if rows_inserted > 0 or rows_duplicate > 0 else "partial"

    print(f"  Inserted: {rows_inserted}")
    print(f"  Duplicates skipped: {rows_duplicate}")

    # Log to upload_log
    cursor.execute(
        """
        INSERT INTO upload_log
            (dataset_type, filename, rows_received, rows_inserted, rows_duplicate, rows_rejected, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (dataset_type, filename, rows_received, rows_inserted, rows_duplicate, 0, status),
    )
    conn.commit()
    cursor.close()

    return {
        "dataset_type": dataset_type,
        "filename": filename,
        "rows_received": rows_received,
        "rows_inserted": rows_inserted,
        "rows_duplicate": rows_duplicate,
        "rows_rejected": 0,
        "status": status,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <path_to_csv_or_directory>")
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        csv_files = [target]
    elif target.is_dir():
        csv_files = sorted(target.glob("*.csv"))
    else:
        print(f"Error: {target} is not a file or directory")
        sys.exit(1)

    if not csv_files:
        print(f"No CSV files found in {target}")
        sys.exit(1)

    print(f"Found {len(csv_files)} CSV file(s)")

    conn = psycopg2.connect(DATABASE_URL)

    results = []
    for csv_file in csv_files:
        result = ingest_file(str(csv_file), conn)
        results.append(result)

    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    total_inserted = 0
    total_duplicate = 0
    for r in results:
        total_inserted += r["rows_inserted"]
        total_duplicate += r["rows_duplicate"]
        status_icon = "OK" if r["status"] == "success" else "FAIL"
        print(
            f"  [{status_icon}] {r['filename']}: "
            f"{r['rows_inserted']} inserted, "
            f"{r['rows_duplicate']} duplicates, "
            f"{r['rows_rejected']} rejected"
        )
    print(f"\nTotal: {total_inserted} inserted, {total_duplicate} duplicates")


if __name__ == "__main__":
    main()
