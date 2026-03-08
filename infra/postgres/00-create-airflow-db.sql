-- Create Airflow metadata database (runs before init.sql due to alphabetical ordering)
CREATE DATABASE airflow_metadata;
GRANT ALL PRIVILEGES ON DATABASE airflow_metadata TO dubai_user;
