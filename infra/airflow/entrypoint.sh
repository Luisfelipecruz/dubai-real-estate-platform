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

# Start the webserver and scheduler
airflow webserver --port 8080 &
exec airflow scheduler
