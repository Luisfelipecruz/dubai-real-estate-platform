#!/usr/bin/env bash
set -e

# Initialize the Airflow metadata database
airflow db migrate

# Create admin user if it doesn't exist
airflow users list | grep -q admin || \
  airflow users create \
    --username admin \
    --password admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com

# Create Spark connection if it doesn't exist
airflow connections get spark_default >/dev/null 2>&1 || \
  airflow connections add spark_default \
    --conn-type spark \
    --conn-host spark://spark-master \
    --conn-port 7077

# Start the webserver and scheduler
airflow webserver --port 8080 &
exec airflow scheduler
