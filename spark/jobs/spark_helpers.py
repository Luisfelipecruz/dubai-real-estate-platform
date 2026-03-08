"""Shared helpers for PySpark jobs."""

import os

# JDBC connection properties from environment
JDBC_URL = os.environ.get(
    "JDBC_URL",
    "jdbc:postgresql://postgres:5432/dubai_re",
)
JDBC_PROPERTIES = {
    "user": os.environ.get("DB_USER", "dubai_user"),
    "password": os.environ.get("DB_PASSWORD", "dubai_pass"),
    "driver": "org.postgresql.Driver",
}


def read_table(spark, table_name):
    """Read a Postgres table into a Spark DataFrame via JDBC."""
    return (
        spark.read.jdbc(
            url=JDBC_URL,
            table=table_name,
            properties=JDBC_PROPERTIES,
        )
    )


def write_table(df, table_name, mode="append"):
    """Write a Spark DataFrame to a Postgres table via JDBC."""
    (
        df.write.jdbc(
            url=JDBC_URL,
            table=table_name,
            mode=mode,
            properties=JDBC_PROPERTIES,
        )
    )
