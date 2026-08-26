"""Load the DLD *portal UI* exports (rents / valuations / transactions).

    python load_portal_exports.py <file.csv> [<file.csv> ...]

Why this exists separately from `ingest.py`
-------------------------------------------
`ingest.py` handles the DLD **bulk open-data** files -- snake_case headers, a real
`transaction_id` / `contract_id`, an `area_id` foreign key. The files you get from the
portal's interactive export at dubailand.gov.ae/en/open-data/real-estate-data are a
*different schema wearing the same name*:

  * headers are UPPERCASE and abbreviated -- `AREA_EN` not `area_name_en`,
    `TRANS_VALUE` not `actual_worth`
  * the file starts with a UTF-8 BOM, so the first header is `﻿TRANSACTION_NUMBER`
    and any naive equality check on it fails
  * there is no `area_id` at all -- areas are only ever named
  * **rents carry no contract identifier whatsoever**, and the table requires one

Rather than teach `ingest.py` two dialects and risk the bulk path that 68 tests cover,
this maps the portal dialect onto the same tables with the same ON CONFLICT semantics.

The synthetic rent key
----------------------
`raw_rent_contracts` is `(contract_id, line_number)` NOT NULL UNIQUE, and the portal
export has neither. Dropping the constraint would have been the easy fix and the wrong
one: it is what makes re-ingestion idempotent, which is the property this whole project
is built around.

Instead the key is *derived* -- `md5` over the columns that identify a contract in the
real world (registration date, both contract dates, area, both amounts, area, project),
with `line_number` disambiguating rows whose natural key is genuinely identical. Two
consequences worth knowing:

  * re-running this script over the same file inserts **0** rows, because the same
    content hashes to the same key and ON CONFLICT absorbs it
  * a *corrected* row upstream (same contract, amended amount) hashes differently and
    lands as a new row. A derived key cannot track an update it was never given an
    identifier for. That is a real limitation, not an oversight.
"""

import csv
import hashlib
import os
import sys
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values

DB = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "dbname": os.getenv("POSTGRES_DB", "dubai_re"),
    "user": os.getenv("POSTGRES_USER", "dubai_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "dubai_pass"),
}

# Portal-dialect signatures. Deliberately distinct from ingest.py's, which keys off the
# bulk files' snake_case columns.
SIGNATURES = {
    "rents": {"REGISTRATION_DATE", "ANNUAL_AMOUNT", "CONTRACT_AMOUNT"},
    "valuations": {"PROCEDURE_NUMBER", "PROPERTY_TOTAL_VALUE"},
    "transactions": {"TRANSACTION_NUMBER", "TRANS_VALUE"},
}

RENT_MAP = {
    "START_DATE": "contract_start_date",
    "END_DATE": "contract_end_date",
    "VERSION_EN": "contract_reg_type_en",
    "CONTRACT_AMOUNT": "contract_amount",
    "ANNUAL_AMOUNT": "annual_amount",
    "PROP_TYPE_EN": "ejari_property_type_en",
    "PROP_SUB_TYPE_EN": "ejari_property_sub_type_en",
    "USAGE_EN": "property_usage_en",
    "IS_FREE_HOLD_EN": "is_free_hold",
    "AREA_EN": "area_name_en",
    "PROJECT_EN": "project_name_en",
    "MASTER_PROJECT_EN": "master_project_en",
    "TOTAL_PROPERTIES": "no_of_prop",
    "ACTUAL_AREA": "actual_area",
    "NEAREST_METRO_EN": "nearest_metro_en",
    "NEAREST_MALL_EN": "nearest_mall_en",
    "NEAREST_LANDMARK_EN": "nearest_landmark_en",
    "REGISTRATION_DATE": "load_timestamp",
}

VALUATION_MAP = {
    "PROCEDURE_NUMBER": "procedure_number",
    "INSTANCE_DATE": "instance_date",
    "PROCEDURE_YEAR": "procedure_year",
    "PROPERTY_TYPE_EN": "property_type_en",
    "PROP_SUB_TYPE_EN": "property_sub_type_en",
    "AREA_EN": "area_name_en",
    "PROCEDURE_AREA": "procedure_area",
    "ACTUAL_AREA": "actual_area",
    "ACTUAL_WORTH": "actual_worth",
    "PROPERTY_TOTAL_VALUE": "property_total_value",
}

# Columns whose combination identifies a rent contract in the absence of an id.
RENT_NATURAL_KEY = [
    "REGISTRATION_DATE", "START_DATE", "END_DATE", "AREA_EN",
    "CONTRACT_AMOUNT", "ANNUAL_AMOUNT", "ACTUAL_AREA", "PROJECT_EN",
    "PROP_TYPE_EN", "PROP_SUB_TYPE_EN",
]

NULLS = {"", "NA", "N/A", "NULL", "None", "-", "nan"}
BATCH = 5000


def clean(v):
    if v is None:
        return None
    v = v.strip()
    return None if v in NULLS else v


def as_num(v):
    v = clean(v)
    if v is None:
        return None
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


def as_int(v):
    n = as_num(v)
    return int(n) if n is not None else None


def as_date(v):
    """Portal timestamps are 'YYYY-MM-DD HH:MM:SS'. Postgres parses them; we only
    need to reject the empties so the driver does not send an empty string to a
    date column."""
    return clean(v)


def as_bool(v):
    v = clean(v)
    if v is None:
        return None
    return v.strip().upper() in {"FREE HOLD", "TRUE", "YES", "Y", "1"}


def detect(headers):
    have = {h.strip().lstrip("﻿").upper() for h in headers}
    for name, sig in SIGNATURES.items():
        if sig <= have:
            return name
    return None


def rent_key(row):
    raw = "|".join((clean(row.get(c)) or "") for c in RENT_NATURAL_KEY)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:32]


def load_rents(rows):
    seen = defaultdict(int)
    out = []
    for r in rows:
        key = rent_key(r)
        seen[key] += 1
        out.append((
            key, seen[key],
            as_date(r.get("START_DATE")), as_date(r.get("END_DATE")),
            clean(r.get("VERSION_EN")),
            as_num(r.get("CONTRACT_AMOUNT")), as_num(r.get("ANNUAL_AMOUNT")),
            clean(r.get("PROP_TYPE_EN")), clean(r.get("PROP_SUB_TYPE_EN")),
            clean(r.get("USAGE_EN")), as_bool(r.get("IS_FREE_HOLD_EN")),
            clean(r.get("AREA_EN")), clean(r.get("PROJECT_EN")),
            clean(r.get("MASTER_PROJECT_EN")), as_int(r.get("TOTAL_PROPERTIES")),
            as_num(r.get("ACTUAL_AREA")),
            clean(r.get("NEAREST_METRO_EN")), clean(r.get("NEAREST_MALL_EN")),
            clean(r.get("NEAREST_LANDMARK_EN")), as_date(r.get("REGISTRATION_DATE")),
        ))
    cols = ("contract_id, line_number, contract_start_date, contract_end_date, "
            "contract_reg_type_en, contract_amount, annual_amount, "
            "ejari_property_type_en, ejari_property_sub_type_en, property_usage_en, "
            "is_free_hold, area_name_en, project_name_en, master_project_en, "
            "no_of_prop, actual_area, nearest_metro_en, nearest_mall_en, "
            "nearest_landmark_en, load_timestamp")
    return "raw_rent_contracts", cols, "contract_id, line_number", out


def load_valuations(rows):
    out = []
    for r in rows:
        pn = as_int(r.get("PROCEDURE_NUMBER"))
        dt = as_date(r.get("INSTANCE_DATE"))
        if pn is None or dt is None:
            continue  # both are NOT NULL and form the unique key
        out.append((
            pn, dt, as_int(r.get("PROCEDURE_YEAR")),
            clean(r.get("PROPERTY_TYPE_EN")), clean(r.get("PROP_SUB_TYPE_EN")),
            clean(r.get("AREA_EN")),
            as_num(r.get("PROCEDURE_AREA")), as_num(r.get("ACTUAL_AREA")),
            as_num(r.get("ACTUAL_WORTH")), as_num(r.get("PROPERTY_TOTAL_VALUE")),
        ))
    cols = ("procedure_number, instance_date, procedure_year, property_type_en, "
            "property_sub_type_en, area_name_en, procedure_area, actual_area, "
            "actual_worth, property_total_value")
    return "raw_valuations", cols, "procedure_number, instance_date", out


LOADERS = {"rents": load_rents, "valuations": load_valuations}


def process(path, conn):
    name = os.path.basename(path)
    print(f"\nProcessing: {name}")
    # utf-8-sig strips the BOM; without it the first header keeps a ﻿ prefix
    # and every lookup against it silently misses.
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        kind = detect(reader.fieldnames or [])
        if kind is None:
            print(f"  ERROR: unrecognised portal export. Headers: {reader.fieldnames}")
            return
        print(f"  Detected: {kind}")
        if kind not in LOADERS:
            print(f"  SKIPPED: {kind} is not loaded by this script -- see the module docstring.")
            return
        rows = list(reader)

    table, cols, conflict, tuples = LOADERS[kind](rows)
    print(f"  Rows read: {len(rows)}  ->  rows prepared: {len(tuples)}")

    before = count(conn, table)
    sql = f"INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT ({conflict}) DO NOTHING"
    with conn.cursor() as cur:
        for i in range(0, len(tuples), BATCH):
            execute_values(cur, sql, tuples[i:i + BATCH])
    conn.commit()
    after = count(conn, table)

    inserted = after - before
    print(f"  Inserted: {inserted}   Absorbed by ON CONFLICT: {len(tuples) - inserted}")
    print(f"  {table}: {before} -> {after}")


def count(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    conn = psycopg2.connect(**DB)
    try:
        for path in sys.argv[1:]:
            process(path, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
