"""Pure transformation functions for PySpark aggregation jobs.

These functions take DataFrames as input and return DataFrames as output,
with no I/O side effects. This makes them testable with local SparkSessions.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window


def filter_valid_transactions(df: DataFrame) -> DataFrame:
    """Filter transactions with valid date and positive worth."""
    return df.filter(
        F.col("instance_date").isNotNull()
        & F.col("actual_worth").isNotNull()
        & (F.col("actual_worth") > 0)
    )


def filter_valid_rents(df: DataFrame) -> DataFrame:
    """Filter rent contracts with valid date and positive annual amount."""
    return df.filter(
        F.col("contract_start_date").isNotNull()
        & F.col("annual_amount").isNotNull()
        & (F.col("annual_amount") > 0)
    )


def filter_valid_valuations(df: DataFrame) -> DataFrame:
    """Filter valuations with valid date and positive worth."""
    return df.filter(
        F.col("instance_date").isNotNull()
        & F.col("actual_worth").isNotNull()
        & (F.col("actual_worth") > 0)
    )


def aggregate_by_area_quarter(df: DataFrame, date_col: str, amount_col: str,
                               area_col: str, property_type_col: str,
                               price_per_sqm_expr) -> DataFrame:
    """Aggregate a dataset by area/year/quarter with standard metrics.

    Returns DataFrame with columns:
        area_id, area_name_en, year, quarter, avg_price_sqm, median_price,
        transaction_count, total_volume, dominant_property_type, yoy_price_change
    """
    df = df.withColumn("year", F.year(date_col))
    df = df.withColumn("quarter", F.quarter(date_col))

    agg = (
        df.groupBy("area_name_en", "area_id", "year", "quarter")
        .agg(
            F.avg(price_per_sqm_expr).alias("avg_price_sqm"),
            F.expr(f"percentile_approx({amount_col}, 0.5)").alias("median_price"),
            F.count("*").alias("transaction_count"),
            F.sum(amount_col).alias("total_volume"),
        )
    )

    # Dominant property type (mode)
    type_counts = (
        df.groupBy("area_name_en", "year", "quarter", property_type_col)
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
            F.col(property_type_col).alias("dominant_property_type"),
        )
    )

    agg = agg.join(dominant, on=["area_name_en", "year", "quarter"], how="left")

    # YoY price change
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

    return agg


def compute_transaction_trends(df: DataFrame) -> DataFrame:
    """Transform raw transactions into area trends."""
    df = filter_valid_transactions(df)
    result = aggregate_by_area_quarter(
        df,
        date_col="instance_date",
        amount_col="actual_worth",
        area_col="area_name_en",
        property_type_col="property_type_en",
        price_per_sqm_expr=F.col("meter_sale_price"),
    )
    return result.withColumn("dataset", F.lit("transactions")).select(
        "area_id", "area_name_en", "year", "quarter", "dataset",
        F.round("avg_price_sqm", 2).alias("avg_price_sqm"),
        F.round("median_price", 2).alias("median_price"),
        "transaction_count",
        F.round("total_volume", 2).alias("total_volume"),
        "dominant_property_type",
        "yoy_price_change",
    )


def compute_rent_trends(df: DataFrame) -> DataFrame:
    """Transform raw rent contracts into area trends."""
    df = filter_valid_rents(df)
    result = aggregate_by_area_quarter(
        df,
        date_col="contract_start_date",
        amount_col="annual_amount",
        area_col="area_name_en",
        property_type_col="ejari_property_type_en",
        price_per_sqm_expr=F.when(
            F.col("actual_area").isNotNull() & (F.col("actual_area") > 0),
            F.col("annual_amount") / F.col("actual_area"),
        ),
    )
    return result.withColumn("dataset", F.lit("rents")).select(
        "area_id", "area_name_en", "year", "quarter", "dataset",
        F.round("avg_price_sqm", 2).alias("avg_price_sqm"),
        F.round("median_price", 2).alias("median_price"),
        "transaction_count",
        F.round("total_volume", 2).alias("total_volume"),
        "dominant_property_type",
        "yoy_price_change",
    )


def compute_valuation_trends(df: DataFrame) -> DataFrame:
    """Transform raw valuations into area trends."""
    df = filter_valid_valuations(df)
    result = aggregate_by_area_quarter(
        df,
        date_col="instance_date",
        amount_col="actual_worth",
        area_col="area_name_en",
        property_type_col="property_type_en",
        price_per_sqm_expr=F.when(
            F.col("procedure_area").isNotNull() & (F.col("procedure_area") > 0),
            F.col("actual_worth") / F.col("procedure_area"),
        ),
    )
    return result.withColumn("dataset", F.lit("valuations")).select(
        "area_id", "area_name_en", "year", "quarter", "dataset",
        F.round("avg_price_sqm", 2).alias("avg_price_sqm"),
        F.round("median_price", 2).alias("median_price"),
        "transaction_count",
        F.round("total_volume", 2).alias("total_volume"),
        "dominant_property_type",
        "yoy_price_change",
    )


def compute_rental_yields(trends_df: DataFrame) -> DataFrame:
    """Join transaction and rent trends to compute rental yield percentages."""
    tx = trends_df.filter(F.col("dataset") == "transactions").select(
        "area_name_en", "year", "quarter",
        F.col("total_volume").alias("tx_total_volume"),
        F.col("transaction_count").alias("tx_count"),
    )
    tx = tx.withColumn(
        "avg_sale_price",
        F.when(F.col("tx_count") > 0, F.col("tx_total_volume") / F.col("tx_count")).otherwise(None),
    )

    rents = trends_df.filter(F.col("dataset") == "rents").select(
        "area_name_en", "year", "quarter",
        F.col("total_volume").alias("rent_total_volume"),
        F.col("transaction_count").alias("rent_count"),
    )
    rents = rents.withColumn(
        "avg_annual_rent",
        F.when(F.col("rent_count") > 0, F.col("rent_total_volume") / F.col("rent_count")).otherwise(None),
    )

    joined = tx.join(rents, on=["area_name_en", "year", "quarter"], how="inner")

    result = joined.withColumn(
        "rental_yield_pct",
        F.when(
            F.col("avg_sale_price").isNotNull()
            & (F.col("avg_sale_price") > 0)
            & F.col("avg_annual_rent").isNotNull(),
            F.round((F.col("avg_annual_rent") / F.col("avg_sale_price")) * 100, 2),
        ),
    )

    return result.select(
        "area_name_en", "year", "quarter",
        F.round("avg_sale_price", 2).alias("avg_sale_price"),
        F.round("avg_annual_rent", 2).alias("avg_annual_rent"),
        "rental_yield_pct",
        F.col("tx_count").alias("transaction_count"),
        "rent_count",
    )
