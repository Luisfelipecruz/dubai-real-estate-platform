"""Aggregate raw_rent_contracts into area_trends by area/year/quarter."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from spark_helpers import JDBC_PROPERTIES, read_table, write_table
from transforms import compute_rent_trends


def main():
    spark = SparkSession.builder.appName("aggregate_rents").getOrCreate()

    df = read_table(spark, "raw_rent_contracts")
    result = compute_rent_trends(df)

    # Clear existing rent trends
    import psycopg2
    conn = psycopg2.connect(
        host="postgres", port=5432, dbname="dubai_re",
        user=JDBC_PROPERTIES["user"], password=JDBC_PROPERTIES["password"],
    )
    cur = conn.cursor()
    cur.execute("DELETE FROM area_trends WHERE dataset = 'rents'")
    conn.commit()
    cur.close()
    conn.close()

    write_table(result, "area_trends", mode="append")

    count = result.count()
    print(f"Wrote {count} rent trend rows to area_trends")

    spark.stop()


if __name__ == "__main__":
    main()
