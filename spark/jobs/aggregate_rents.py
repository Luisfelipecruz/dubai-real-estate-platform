"""Aggregate raw_rent_contracts into area_trends by area/year/quarter."""

import sys
sys.path.insert(0, "/opt/spark/jobs")

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from spark_helpers import JDBC_URL, JDBC_PROPERTIES, read_table, write_table


def main():
    spark = SparkSession.builder.appName("aggregate_rents").getOrCreate()

    df = read_table(spark, "raw_rent_contracts")

    # Filter rows with valid dates and amounts
    df = df.filter(
        F.col("contract_start_date").isNotNull()
        & F.col("annual_amount").isNotNull()
        & (F.col("annual_amount") > 0)
    )

    # Extract year and quarter from contract start date
    df = df.withColumn("year", F.year("contract_start_date"))
    df = df.withColumn("quarter", F.quarter("contract_start_date"))

    # Aggregate by area, year, quarter
    agg = (
        df.groupBy("area_name_en", "area_id", "year", "quarter")
        .agg(
            F.avg(
                F.when(
                    F.col("actual_area").isNotNull() & (F.col("actual_area") > 0),
                    F.col("annual_amount") / F.col("actual_area"),
                )
            ).alias("avg_price_sqm"),
            F.expr("percentile_approx(annual_amount, 0.5)").alias("median_price"),
            F.count("*").alias("transaction_count"),
            F.sum("annual_amount").alias("total_volume"),
        )
    )

    # Dominant property type per group
    type_counts = (
        df.groupBy("area_name_en", "year", "quarter", "ejari_property_type_en")
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
            F.col("ejari_property_type_en").alias("dominant_property_type"),
        )
    )

    agg = agg.join(dominant, on=["area_name_en", "year", "quarter"], how="left")

    # YoY change
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

    result = agg.withColumn("dataset", F.lit("rents"))

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
