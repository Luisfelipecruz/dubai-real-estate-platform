"""PySpark reading the full 1.02 GB DLD transactions CSV.

Same aggregation as scripts/bench_pandas.py so the three runs are comparable:
    group by area_name_en, year, quarter -> count, sum(actual_worth), sum/count(meter_sale_price)

Usage:
    spark-submit --master spark://spark-master:7077 bench_transactions_csv.py /data/Transactions.csv
"""

import sys
import time

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

# Only the columns the aggregation needs -- the Spark equivalent of pandas `usecols`.
SCHEMA = StructType(
    [
        StructField("transaction_id", StringType(), True),
        StructField("instance_date", StringType(), True),
        StructField("area_name_en", StringType(), True),
        StructField("actual_worth", DoubleType(), True),
        StructField("meter_sale_price", DoubleType(), True),
    ]
)


def main(path: str) -> None:
    spark = SparkSession.builder.appName("bench_transactions_csv").getOrCreate()
    sc = spark.sparkContext
    print(f"Spark {spark.version} · master={sc.master} · defaultParallelism={sc.defaultParallelism}")

    t0 = time.perf_counter()

    # Read with the header, then project down to the five columns the aggregation needs.
    # inferSchema=False keeps this to a single pass -- inference costs a full extra scan.
    df = spark.read.option("header", True).csv(path, inferSchema=False)

    df = df.select(
        "transaction_id",
        "instance_date",
        "area_name_en",
        F.col("actual_worth").cast("double").alias("actual_worth"),
        F.col("meter_sale_price").cast("double").alias("meter_sale_price"),
    )

    t_plan = time.perf_counter() - t0
    print(f"plan built (lazy, nothing executed yet): {t_plan:.2f} s")

    # The DLD file is dd-MM-yyyy. to_date() defaults to yyyy-MM-dd and returns NULL
    # silently on mismatch -- without this format string the job produces 0 groups.
    d = F.to_date(F.col("instance_date"), "dd-MM-yyyy")
    result = (
        df.filter(F.col("actual_worth").isNotNull() & (F.col("actual_worth") > 0))
        .withColumn("year", F.year(d))
        .withColumn("quarter", F.quarter(d))
        .filter(F.col("year").isNotNull())
        .groupBy("area_name_en", "year", "quarter")
        .agg(
            F.count("*").alias("n"),
            F.sum("actual_worth").alias("total"),
            F.sum("meter_sale_price").alias("sum_sqm"),
            F.count("meter_sale_price").alias("cnt_sqm"),
        )
    )

    # The action -- this is where the job actually runs.
    t1 = time.perf_counter()
    rows = result.collect()
    t_action = time.perf_counter() - t1

    n_total = sum(r["n"] for r in rows)
    total = sum(r["total"] for r in rows)

    print(f"groups              : {len(rows):,}")
    print(f"action wall time    : {t_action:.1f} s")
    print(f"TOTAL wall time     : {time.perf_counter() - t0:.1f} s")
    print(f"CHECK rows={n_total:,} total={total:.0f}")
    print(f"shuffle partitions  : {spark.conf.get('spark.sql.shuffle.partitions')}")

    result.explain(mode="formatted")

    spark.stop()


if __name__ == "__main__":
    main(sys.argv[1])
