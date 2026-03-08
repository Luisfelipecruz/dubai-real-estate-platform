"""Aggregate raw_valuations into area_trends by area/year/quarter."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from spark_helpers import JDBC_PROPERTIES, read_table, write_table
from transforms import compute_valuation_trends


def main():
    spark = SparkSession.builder.appName("aggregate_valuations").getOrCreate()

    df = read_table(spark, "raw_valuations")
    result = compute_valuation_trends(df)

    # Clear existing valuation trends
    import psycopg2
    conn = psycopg2.connect(
        host="postgres", port=5432, dbname="dubai_re",
        user=JDBC_PROPERTIES["user"], password=JDBC_PROPERTIES["password"],
    )
    cur = conn.cursor()
    cur.execute("DELETE FROM area_trends WHERE dataset = 'valuations'")
    conn.commit()
    cur.close()
    conn.close()

    write_table(result, "area_trends", mode="append")

    count = result.count()
    print(f"Wrote {count} valuation trend rows to area_trends")

    spark.stop()


if __name__ == "__main__":
    main()
