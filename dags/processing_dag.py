"""DAG that orchestrates Spark aggregation jobs for Dubai RE analytics.

Runs all 4 Spark jobs sequentially:
  aggregate_transactions >> aggregate_rents >> aggregate_valuations >> cross_dataset_analysis

Can be triggered manually from the Airflow UI or via API after a CSV upload.
"""

from datetime import datetime

from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator


SPARK_CONN_ID = "spark_default"
JOBS_DIR = "/opt/spark/jobs"
PY_FILES = f"{JOBS_DIR}/spark_helpers.py,{JOBS_DIR}/transforms.py"

with DAG(
    dag_id="processing_pipeline",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["pipeline", "spark"],
    doc_md="""
    ### Dubai RE Processing Pipeline

    Computes quarterly area trends and rental yields from raw DLD data.

    **Jobs:**
    1. `aggregate_transactions` — price/volume trends per area
    2. `aggregate_rents` — rent trends per area
    3. `aggregate_valuations` — valuation trends per area
    4. `cross_dataset_analysis` — rental yield = rent / sale price

    **Trigger:** Manual or after CSV upload.
    """,
) as dag:

    aggregate_transactions = SparkSubmitOperator(
        task_id="aggregate_transactions",
        conn_id=SPARK_CONN_ID,
        application=f"{JOBS_DIR}/aggregate_transactions.py",
        py_files=PY_FILES,
        name="aggregate_transactions",
        verbose=False,
    )

    aggregate_rents = SparkSubmitOperator(
        task_id="aggregate_rents",
        conn_id=SPARK_CONN_ID,
        application=f"{JOBS_DIR}/aggregate_rents.py",
        py_files=PY_FILES,
        name="aggregate_rents",
        verbose=False,
    )

    aggregate_valuations = SparkSubmitOperator(
        task_id="aggregate_valuations",
        conn_id=SPARK_CONN_ID,
        application=f"{JOBS_DIR}/aggregate_valuations.py",
        py_files=PY_FILES,
        name="aggregate_valuations",
        verbose=False,
    )

    cross_dataset = SparkSubmitOperator(
        task_id="cross_dataset_analysis",
        conn_id=SPARK_CONN_ID,
        application=f"{JOBS_DIR}/cross_dataset_analysis.py",
        py_files=PY_FILES,
        name="cross_dataset_analysis",
        verbose=False,
    )

    aggregate_transactions >> aggregate_rents >> aggregate_valuations >> cross_dataset
