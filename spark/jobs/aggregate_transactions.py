"""Aggregate raw_transactions into area_trends by area/year/quarter."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from spark_helpers import JDBC_PROPERTIES, read_table, write_table
from transforms import compute_transaction_trends


def main():
    spark = SparkSession.builder.appName("aggregate_transactions").getOrCreate()

    df = read_table(spark, "raw_transactions")
    result = compute_transaction_trends(df)

    # Delete existing transaction trends, then write
    import psycopg2
    conn = psycopg2.connect(
        host=JDBC_PROPERTIES.get("host", "postgres"),
        port=5432,
        dbname="dubai_re",
        user=JDBC_PROPERTIES["user"],
        password=JDBC_PROPERTIES["password"],
    )
    cur = conn.cursor()
    cur.execute("DELETE FROM area_trends WHERE dataset = 'transactions'")
    conn.commit()
    cur.close()
    conn.close()

    write_table(result, "area_trends", mode="append")

    count = result.count()
    print(f"Wrote {count} transaction trend rows to area_trends")

    spark.stop()


if __name__ == "__main__":
    main()
