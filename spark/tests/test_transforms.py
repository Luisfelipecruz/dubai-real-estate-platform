"""Tests for PySpark transformation functions."""

import sys
import os
from datetime import date, datetime
from decimal import Decimal

import pytest
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType, DateType,
    TimestampType, LongType,
)

# Add jobs directory to path so transforms can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))

from transforms import (
    filter_valid_transactions,
    filter_valid_rents,
    filter_valid_valuations,
    compute_transaction_trends,
    compute_rent_trends,
    compute_valuation_trends,
    compute_rental_yields,
)


# ── Filter Tests ──────────────────────────────────────────────────


class TestFilterValidTransactions:
    def test_removes_null_dates(self, spark):
        df = spark.createDataFrame(
            [(None, 100.0), (date(2024, 1, 15), 200.0)],
            ["instance_date", "actual_worth"],
        )
        result = filter_valid_transactions(df)
        assert result.count() == 1
        assert result.first()["actual_worth"] == 200.0

    def test_removes_zero_worth(self, spark):
        df = spark.createDataFrame(
            [(date(2024, 1, 1), 0.0), (date(2024, 1, 1), 500.0)],
            ["instance_date", "actual_worth"],
        )
        result = filter_valid_transactions(df)
        assert result.count() == 1

    def test_removes_null_worth(self, spark):
        df = spark.createDataFrame(
            [(date(2024, 1, 1), None), (date(2024, 1, 1), 100.0)],
            ["instance_date", "actual_worth"],
        )
        result = filter_valid_transactions(df)
        assert result.count() == 1

    def test_keeps_valid_rows(self, spark):
        df = spark.createDataFrame(
            [
                (date(2024, 1, 1), 100.0),
                (date(2024, 6, 15), 200.0),
                (date(2024, 12, 31), 300.0),
            ],
            ["instance_date", "actual_worth"],
        )
        result = filter_valid_transactions(df)
        assert result.count() == 3


class TestFilterValidRents:
    def test_removes_null_dates(self, spark):
        df = spark.createDataFrame(
            [(None, 50000.0), (date(2024, 3, 1), 60000.0)],
            ["contract_start_date", "annual_amount"],
        )
        result = filter_valid_rents(df)
        assert result.count() == 1

    def test_removes_zero_amount(self, spark):
        df = spark.createDataFrame(
            [(date(2024, 1, 1), 0.0), (date(2024, 1, 1), 50000.0)],
            ["contract_start_date", "annual_amount"],
        )
        result = filter_valid_rents(df)
        assert result.count() == 1


class TestFilterValidValuations:
    def test_removes_null_dates(self, spark):
        df = spark.createDataFrame(
            [(None, 100.0), (datetime(2024, 1, 15, 10, 0), 200.0)],
            ["instance_date", "actual_worth"],
        )
        result = filter_valid_valuations(df)
        assert result.count() == 1

    def test_removes_zero_worth(self, spark):
        df = spark.createDataFrame(
            [(datetime(2024, 1, 1, 0, 0), 0.0), (datetime(2024, 1, 1, 0, 0), 500.0)],
            ["instance_date", "actual_worth"],
        )
        result = filter_valid_valuations(df)
        assert result.count() == 1


# ── Aggregation Tests ─────────────────────────────────────────────


class TestComputeTransactionTrends:
    def _make_transactions(self, spark, rows):
        """Create a transactions DataFrame from simplified rows."""
        return spark.createDataFrame(
            rows,
            [
                "transaction_id", "instance_date", "actual_worth",
                "meter_sale_price", "property_type_en", "area_name_en",
                "area_id",
            ],
        )

    def test_groups_by_area_and_quarter(self, spark):
        df = self._make_transactions(spark, [
            ("T1", date(2024, 1, 15), 1000000.0, 5000.0, "Unit", "Marina", 1),
            ("T2", date(2024, 2, 20), 2000000.0, 6000.0, "Unit", "Marina", 1),
            ("T3", date(2024, 4, 10), 1500000.0, 5500.0, "Villa", "JBR", 2),
        ])
        result = compute_transaction_trends(df)
        rows = {r["area_name_en"]: r for r in result.collect()}

        assert len(rows) == 2
        assert rows["Marina"]["transaction_count"] == 2
        assert rows["Marina"]["quarter"] == 1
        assert rows["JBR"]["transaction_count"] == 1
        assert rows["JBR"]["quarter"] == 2

    def test_computes_avg_price_sqm(self, spark):
        df = self._make_transactions(spark, [
            ("T1", date(2024, 1, 1), 1000000.0, 5000.0, "Unit", "Marina", 1),
            ("T2", date(2024, 1, 1), 2000000.0, 7000.0, "Unit", "Marina", 1),
        ])
        result = compute_transaction_trends(df)
        row = result.first()
        assert float(row["avg_price_sqm"]) == 6000.0

    def test_computes_total_volume(self, spark):
        df = self._make_transactions(spark, [
            ("T1", date(2024, 1, 1), 1000000.0, 5000.0, "Unit", "Marina", 1),
            ("T2", date(2024, 1, 1), 2000000.0, 7000.0, "Unit", "Marina", 1),
        ])
        result = compute_transaction_trends(df)
        row = result.first()
        assert float(row["total_volume"]) == 3000000.0

    def test_dataset_label_is_transactions(self, spark):
        df = self._make_transactions(spark, [
            ("T1", date(2024, 1, 1), 1000000.0, 5000.0, "Unit", "Marina", 1),
        ])
        result = compute_transaction_trends(df)
        assert result.first()["dataset"] == "transactions"

    def test_dominant_property_type(self, spark):
        df = self._make_transactions(spark, [
            ("T1", date(2024, 1, 1), 1000000.0, 5000.0, "Unit", "Marina", 1),
            ("T2", date(2024, 2, 1), 2000000.0, 6000.0, "Unit", "Marina", 1),
            ("T3", date(2024, 3, 1), 1500000.0, 5500.0, "Villa", "Marina", 1),
        ])
        result = compute_transaction_trends(df)
        assert result.first()["dominant_property_type"] == "Unit"

    def test_yoy_price_change(self, spark):
        df = self._make_transactions(spark, [
            ("T1", date(2023, 1, 1), 1000000.0, 5000.0, "Unit", "Marina", 1),
            ("T2", date(2024, 1, 1), 1000000.0, 10000.0, "Unit", "Marina", 1),
        ])
        result = compute_transaction_trends(df)
        rows = sorted(result.collect(), key=lambda r: r["year"])
        # 2023 Q1: no previous year → null
        assert rows[0]["yoy_price_change"] is None
        # 2024 Q1: (10000 - 5000) / 5000 * 100 = 100%
        assert float(rows[1]["yoy_price_change"]) == 100.0

    def test_empty_input_returns_empty(self, spark):
        schema = StructType([
            StructField("transaction_id", StringType()),
            StructField("instance_date", DateType()),
            StructField("actual_worth", DoubleType()),
            StructField("meter_sale_price", DoubleType()),
            StructField("property_type_en", StringType()),
            StructField("area_name_en", StringType()),
            StructField("area_id", IntegerType()),
        ])
        df = spark.createDataFrame([], schema)
        result = compute_transaction_trends(df)
        assert result.count() == 0


class TestComputeRentTrends:
    def _make_rents(self, spark, rows):
        return spark.createDataFrame(
            rows,
            [
                "contract_id", "contract_start_date", "annual_amount",
                "actual_area", "ejari_property_type_en", "area_name_en",
                "area_id",
            ],
        )

    def test_groups_by_area_and_quarter(self, spark):
        df = self._make_rents(spark, [
            ("C1", date(2024, 1, 1), 60000.0, 100.0, "Flat", "Marina", 1),
            ("C2", date(2024, 1, 15), 80000.0, 120.0, "Flat", "Marina", 1),
            ("C3", date(2024, 7, 1), 50000.0, 80.0, "Office", "JBR", 2),
        ])
        result = compute_rent_trends(df)
        assert result.count() == 2

    def test_computes_price_per_sqm(self, spark):
        df = self._make_rents(spark, [
            ("C1", date(2024, 1, 1), 100000.0, 100.0, "Flat", "Marina", 1),
        ])
        result = compute_rent_trends(df)
        row = result.first()
        # 100000 / 100 = 1000 per sqm
        assert float(row["avg_price_sqm"]) == 1000.0

    def test_dataset_label_is_rents(self, spark):
        df = self._make_rents(spark, [
            ("C1", date(2024, 1, 1), 60000.0, 100.0, "Flat", "Marina", 1),
        ])
        result = compute_rent_trends(df)
        assert result.first()["dataset"] == "rents"

    def test_null_area_excluded_from_price_sqm(self, spark):
        df = self._make_rents(spark, [
            ("C1", date(2024, 1, 1), 60000.0, None, "Flat", "Marina", 1),
            ("C2", date(2024, 1, 1), 80000.0, 80.0, "Flat", "Marina", 1),
        ])
        result = compute_rent_trends(df)
        row = result.first()
        # Only C2 contributes: 80000/80 = 1000
        assert float(row["avg_price_sqm"]) == 1000.0


class TestComputeValuationTrends:
    def _make_valuations(self, spark, rows):
        return spark.createDataFrame(
            rows,
            [
                "procedure_number", "instance_date", "actual_worth",
                "procedure_area", "property_type_en", "area_name_en",
                "area_id",
            ],
        )

    def test_groups_by_area_and_quarter(self, spark):
        df = self._make_valuations(spark, [
            (1, datetime(2024, 1, 1, 0, 0), 500000.0, 100.0, "Unit", "Marina", 1),
            (2, datetime(2024, 4, 1, 0, 0), 600000.0, 120.0, "Land", "JBR", 2),
        ])
        result = compute_valuation_trends(df)
        assert result.count() == 2

    def test_dataset_label_is_valuations(self, spark):
        df = self._make_valuations(spark, [
            (1, datetime(2024, 1, 1, 0, 0), 500000.0, 100.0, "Unit", "Marina", 1),
        ])
        result = compute_valuation_trends(df)
        assert result.first()["dataset"] == "valuations"

    def test_price_per_sqm_calculation(self, spark):
        df = self._make_valuations(spark, [
            (1, datetime(2024, 1, 1, 0, 0), 500000.0, 100.0, "Unit", "Marina", 1),
        ])
        result = compute_valuation_trends(df)
        # 500000 / 100 = 5000
        assert float(result.first()["avg_price_sqm"]) == 5000.0


# ── Cross-Dataset Tests ───────────────────────────────────────────


class TestComputeRentalYields:
    TRENDS_SCHEMA = StructType([
        StructField("area_name_en", StringType()),
        StructField("year", IntegerType()),
        StructField("quarter", IntegerType()),
        StructField("dataset", StringType()),
        StructField("avg_price_sqm", DoubleType()),
        StructField("median_price", DoubleType()),
        StructField("transaction_count", LongType()),
        StructField("total_volume", DoubleType()),
        StructField("dominant_property_type", StringType()),
        StructField("yoy_price_change", DoubleType()),
        StructField("area_id", IntegerType()),
    ])

    def _make_trends(self, spark, rows):
        return spark.createDataFrame(rows, self.TRENDS_SCHEMA)

    def test_computes_rental_yield(self, spark):
        df = self._make_trends(spark, [
            ("Marina", 2024, 1, "transactions", 5000.0, 1000000.0, 10, 10000000.0, "Unit", None, 1),
            ("Marina", 2024, 1, "rents", 500.0, 50000.0, 20, 1000000.0, "Flat", None, 1),
        ])
        result = compute_rental_yields(df)
        row = result.first()
        # avg_sale = 10000000/10 = 1000000, avg_rent = 1000000/20 = 50000
        # yield = (50000/1000000)*100 = 5.0%
        assert float(row["rental_yield_pct"]) == 5.0
        assert row["transaction_count"] == 10
        assert row["rent_count"] == 20

    def test_no_match_returns_empty(self, spark):
        df = self._make_trends(spark, [
            ("Marina", 2024, 1, "transactions", 5000.0, 1000000.0, 10, 10000000.0, "Unit", None, 1),
            ("JBR", 2024, 1, "rents", 500.0, 50000.0, 20, 1000000.0, "Flat", None, 2),
        ])
        result = compute_rental_yields(df)
        assert result.count() == 0

    def test_multiple_areas(self, spark):
        df = self._make_trends(spark, [
            ("Marina", 2024, 1, "transactions", 5000.0, 1000000.0, 10, 10000000.0, "Unit", None, 1),
            ("Marina", 2024, 1, "rents", 500.0, 50000.0, 20, 1000000.0, "Flat", None, 1),
            ("JBR", 2024, 1, "transactions", 4000.0, 800000.0, 5, 4000000.0, "Villa", None, 2),
            ("JBR", 2024, 1, "rents", 400.0, 40000.0, 10, 400000.0, "Villa", None, 2),
        ])
        result = compute_rental_yields(df)
        assert result.count() == 2
        rows = {r["area_name_en"]: r for r in result.collect()}
        # JBR: avg_sale=800000, avg_rent=40000, yield=5.0%
        assert float(rows["JBR"]["rental_yield_pct"]) == 5.0

    def test_valuations_ignored(self, spark):
        df = self._make_trends(spark, [
            ("Marina", 2024, 1, "transactions", 5000.0, 1000000.0, 10, 10000000.0, "Unit", None, 1),
            ("Marina", 2024, 1, "rents", 500.0, 50000.0, 20, 1000000.0, "Flat", None, 1),
            ("Marina", 2024, 1, "valuations", 4500.0, 900000.0, 15, 13500000.0, "Unit", None, 1),
        ])
        result = compute_rental_yields(df)
        assert result.count() == 1
