"""Cross-dataset analysis: compute rental yields by joining transaction and rent trends."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from spark_helpers import JDBC_URL, JDBC_PROPERTIES, read_table, write_table


def main():
    spark = SparkSession.builder.appName("cross_dataset_analysis").getOrCreate()

    trends = read_table(spark, "area_trends")

    # Split into transaction and rent trends
    tx = trends.filter(F.col("dataset") == "transactions").select(
        "area_name_en",
        "year",
        "quarter",
        F.col("avg_price_sqm").alias("avg_sale_price_sqm"),
        F.col("total_volume").alias("avg_sale_price"),
        F.col("transaction_count").alias("tx_count"),
    )
    # For sale price, use total_volume / transaction_count as average sale price
    tx = tx.withColumn(
        "avg_sale_price",
        F.when(F.col("tx_count") > 0, F.col("avg_sale_price") / F.col("tx_count")).otherwise(None),
    )

    rents = trends.filter(F.col("dataset") == "rents").select(
        "area_name_en",
        "year",
        "quarter",
        F.col("total_volume").alias("total_rent_volume"),
        F.col("transaction_count").alias("rent_count"),
    )
    rents = rents.withColumn(
        "avg_annual_rent",
        F.when(F.col("rent_count") > 0, F.col("total_rent_volume") / F.col("rent_count")).otherwise(None),
    )

    # Join on area/year/quarter
    joined = tx.join(
        rents,
        on=["area_name_en", "year", "quarter"],
        how="inner",
    )

    # Compute rental yield: (avg_annual_rent / avg_sale_price) * 100
    result = joined.withColumn(
        "rental_yield_pct",
        F.when(
            F.col("avg_sale_price").isNotNull()
            & (F.col("avg_sale_price") > 0)
            & F.col("avg_annual_rent").isNotNull(),
            F.round((F.col("avg_annual_rent") / F.col("avg_sale_price")) * 100, 2),
        ),
    )

    result = result.select(
        "area_name_en",
        "year",
        "quarter",
        F.round("avg_sale_price", 2).alias("avg_sale_price"),
        F.round("avg_annual_rent", 2).alias("avg_annual_rent"),
        "rental_yield_pct",
        F.col("tx_count").alias("transaction_count"),
        "rent_count",
    )

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
