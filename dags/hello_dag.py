"""Placeholder DAG to verify Airflow is running correctly."""

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def _hello():
    print("Airflow is running on Dubai RE Platform!")


with DAG(
    dag_id="hello_platform",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["test"],
) as dag:
    hello = PythonOperator(
        task_id="hello",
        python_callable=_hello,
    )
