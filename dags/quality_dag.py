"""DAG that runs data quality checks on the Dubai RE platform datasets.

Checks:
- Row count: each raw table has > 0 rows
- Null rate: critical columns have < 5% nulls
- Value range: amounts within reasonable bounds
- Freshness: recent successful upload exists
- Cross-dataset: area coverage between transactions and rents
"""

import os
import uuid
from datetime import datetime

import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator


DB_URL = os.environ.get(
    "DUBAI_RE_DB_URL",
    "postgresql://dubai_user:dubai_pass@postgres:5432/dubai_re",
)


def _get_conn():
    return psycopg2.connect(DB_URL)


def _save_result(cur, run_id, check_name, category, dataset, status, message, value=None, threshold=None):
    cur.execute(
        """INSERT INTO quality_checks
           (check_name, category, dataset, status, message, value, threshold, run_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (check_name, category, dataset, status, message, value, threshold, run_id),
    )


def run_quality_checks(**context):
    run_id = str(uuid.uuid4())[:8]
    conn = _get_conn()
    cur = conn.cursor()
    failures = 0

    # ── Row Count Checks ────────────────────────────────────
    tables = {
        "raw_transactions": "transactions",
        "raw_rent_contracts": "rents",
        "raw_valuations": "valuations",
    }
    for table, dataset in tables.items():
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        if count > 0:
            _save_result(cur, run_id, f"row_count_{dataset}", "row_count", dataset,
                        "pass", f"{table} has {count:,} rows", count, 1)
        else:
            _save_result(cur, run_id, f"row_count_{dataset}", "row_count", dataset,
                        "fail", f"{table} is empty", count, 1)
            failures += 1

    # ── Null Rate Checks ────────────────────────────────────
    null_checks = [
        ("raw_transactions", "transactions", "area_name_en"),
        ("raw_transactions", "transactions", "actual_worth"),
        ("raw_transactions", "transactions", "instance_date"),
        ("raw_rent_contracts", "rents", "area_name_en"),
        ("raw_rent_contracts", "rents", "annual_amount"),
        ("raw_rent_contracts", "rents", "contract_start_date"),
        ("raw_valuations", "valuations", "area_name_en"),
        ("raw_valuations", "valuations", "actual_worth"),
        ("raw_valuations", "valuations", "instance_date"),
    ]
    threshold_pct = 5.0
    for table, dataset, column in null_checks:
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE {column} IS NULL) * 100.0 / NULLIF(COUNT(*), 0)
            FROM {table}
        """)
        null_pct = cur.fetchone()[0] or 0.0
        if null_pct <= threshold_pct:
            _save_result(cur, run_id, f"null_rate_{dataset}_{column}", "null_rate", dataset,
                        "pass", f"{column}: {null_pct:.1f}% nulls", float(null_pct), threshold_pct)
        else:
            _save_result(cur, run_id, f"null_rate_{dataset}_{column}", "null_rate", dataset,
                        "fail", f"{column}: {null_pct:.1f}% nulls exceeds {threshold_pct}% threshold",
                        float(null_pct), threshold_pct)
            failures += 1

    # ── Value Range Checks ──────────────────────────────────
    range_checks = [
        ("raw_transactions", "transactions", "actual_worth", 0, 5_000_000_000),
        ("raw_rent_contracts", "rents", "annual_amount", 0, 100_000_000),
        ("raw_valuations", "valuations", "actual_worth", 0, 5_000_000_000),
    ]
    for table, dataset, column, min_val, max_val in range_checks:
        cur.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE {column} IS NOT NULL AND ({column} < {min_val} OR {column} > {max_val})
        """)
        out_of_range = cur.fetchone()[0]
        if out_of_range == 0:
            _save_result(cur, run_id, f"range_{dataset}_{column}", "value_range", dataset,
                        "pass", f"All {column} values within [{min_val:,}, {max_val:,}]",
                        0, max_val)
        else:
            _save_result(cur, run_id, f"range_{dataset}_{column}", "value_range", dataset,
                        "warn", f"{out_of_range} rows with {column} outside [{min_val:,}, {max_val:,}]",
                        out_of_range, max_val)

    # ── Freshness Check ─────────────────────────────────────
    cur.execute("""
        SELECT MAX(uploaded_at) FROM upload_log WHERE status = 'success'
    """)
    last_upload = cur.fetchone()[0]
    if last_upload:
        hours_ago = (datetime.utcnow() - last_upload).total_seconds() / 3600
        if hours_ago <= 168:  # 7 days
            _save_result(cur, run_id, "freshness", "freshness", None,
                        "pass", f"Last successful upload {hours_ago:.0f}h ago",
                        hours_ago, 168)
        else:
            _save_result(cur, run_id, "freshness", "freshness", None,
                        "warn", f"Last successful upload {hours_ago:.0f}h ago (>{168}h)",
                        hours_ago, 168)
    else:
        _save_result(cur, run_id, "freshness", "freshness", None,
                    "warn", "No successful uploads found", None, 168)

    # ── Cross-Dataset Coverage ──────────────────────────────
    cur.execute("""
        SELECT
            COUNT(DISTINCT t.area_name_en) AS tx_areas,
            COUNT(DISTINCT r.area_name_en) AS rent_areas,
            COUNT(DISTINCT CASE WHEN t.area_name_en IS NOT NULL AND r.area_name_en IS NOT NULL
                  THEN t.area_name_en END) AS shared_areas
        FROM (SELECT DISTINCT area_name_en FROM raw_transactions) t
        FULL OUTER JOIN (SELECT DISTINCT area_name_en FROM raw_rent_contracts) r
            ON t.area_name_en = r.area_name_en
    """)
    tx_areas, rent_areas, shared = cur.fetchone()
    coverage = (shared / max(tx_areas, 1)) * 100
    _save_result(cur, run_id, "cross_dataset_coverage", "coverage", None,
                "pass" if coverage >= 50 else "warn",
                f"{shared} shared areas out of {tx_areas} transaction areas ({coverage:.0f}% overlap)",
                coverage, 50)

    conn.commit()
    cur.close()
    conn.close()

    summary = f"Quality run {run_id}: {failures} failures"
    print(summary)
    return {"run_id": run_id, "failures": failures}


with DAG(
    dag_id="quality_checks",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["quality"],
    doc_md="""
    ### Data Quality Checks

    Validates data integrity across all datasets:
    - **Row count**: tables are non-empty
    - **Null rate**: critical columns < 5% nulls
    - **Value range**: amounts within reasonable bounds
    - **Freshness**: recent successful upload
    - **Coverage**: cross-dataset area overlap
    """,
) as dag:

    check = PythonOperator(
        task_id="run_quality_checks",
        python_callable=run_quality_checks,
    )
