"""Cross-dataset analysis: compute rental yields by joining transaction and rent trends."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from spark_helpers import JDBC_PROPERTIES, read_table, write_table
from transforms import compute_rental_yields


def main():
    spark = SparkSession.builder.appName("cross_dataset_analysis").getOrCreate()

    trends = read_table(spark, "area_trends")
    result = compute_rental_yields(trends)

    # Clear existing yields
    import psycopg2
    conn = psycopg2.connect(
        host="postgres", port=5432, dbname="dubai_re",
        user=JDBC_PROPERTIES["user"], password=JDBC_PROPERTIES["password"],
    )
    cur = conn.cursor()
    cur.execute("DELETE FROM rental_yields")
    conn.commit()
    cur.close()
    conn.close()

    write_table(result, "rental_yields", mode="append")

    count = result.count()
    print(f"Wrote {count} rental yield rows to rental_yields")

    spark.stop()


if __name__ == "__main__":
    main()
