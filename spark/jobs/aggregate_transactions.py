"""Aggregate raw_transactions into area_trends by area/year/quarter."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from spark_helpers import JDBC_URL, JDBC_PROPERTIES, read_table, write_table


def main():
    spark = SparkSession.builder.appName("aggregate_transactions").getOrCreate()

    df = read_table(spark, "raw_transactions")

    # Filter rows with valid date and worth
    df = df.filter(
        F.col("instance_date").isNotNull()
        & F.col("actual_worth").isNotNull()
        & (F.col("actual_worth") > 0)
    )

    # Extract year and quarter
    df = df.withColumn("year", F.year("instance_date"))
    df = df.withColumn("quarter", F.quarter("instance_date"))

    # Aggregate by area, year, quarter
    agg = (
        df.groupBy("area_name_en", "area_id", "year", "quarter")
        .agg(
            F.avg("meter_sale_price").alias("avg_price_sqm"),
            F.expr("percentile_approx(actual_worth, 0.5)").alias("median_price"),
            F.count("*").alias("transaction_count"),
            F.sum("actual_worth").alias("total_volume"),
            F.first(
                F.col("property_type_en"),
            ).alias("dominant_property_type"),
        )
    )

    # Compute dominant property type per group (mode)
    type_counts = (
        df.groupBy("area_name_en", "year", "quarter", "property_type_en")
        .count()
    )
    w = Window.partitionBy("area_name_en", "year", "quarter").orderBy(F.desc("count"))
    dominant = (
        type_counts.withColumn("rn", F.row_number().over(w))
        .filter(F.col("rn") == 1)
        .select(
            "area_name_en",
            "year",
            "quarter",
            F.col("property_type_en").alias("dominant_type"),
        )
    )

    agg = agg.drop("dominant_property_type").join(
        dominant, on=["area_name_en", "year", "quarter"], how="left"
    ).withColumnRenamed("dominant_type", "dominant_property_type")

    # Compute YoY price change
    prev_year = agg.select(
        "area_name_en",
        "quarter",
        F.col("year").alias("prev_year"),
        F.col("avg_price_sqm").alias("prev_avg"),
    )
    agg = agg.join(
        prev_year,
        on=[
            agg.area_name_en == prev_year.area_name_en,
            agg.quarter == prev_year.quarter,
            agg.year == prev_year.prev_year + 1,
        ],
        how="left",
    ).select(
        agg["*"],
        F.when(
            F.col("prev_avg").isNotNull() & (F.col("prev_avg") > 0),
            F.round(
                ((agg.avg_price_sqm - F.col("prev_avg")) / F.col("prev_avg")) * 100,
                2,
            ),
        ).alias("yoy_price_change"),
    )

    # Add dataset label
    result = agg.withColumn("dataset", F.lit("transactions"))

    # Select columns matching area_trends schema
    result = result.select(
        "area_id",
        "area_name_en",
        "year",
        "quarter",
        "dataset",
        F.round("avg_price_sqm", 2).alias("avg_price_sqm"),
        F.round("median_price", 2).alias("median_price"),
        "transaction_count",
        F.round("total_volume", 2).alias("total_volume"),
        "dominant_property_type",
        "yoy_price_change",
    )

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
