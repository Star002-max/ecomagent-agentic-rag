"""Small hand-calculated fixtures and real-data acceptance for Phase 2."""

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.services import (
    CsvDataStore, DataValidationError, compare_sales_periods,
    get_inventory_data, get_product_info, get_review_data, get_sales_data,
)


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.tables = {
            "products": pd.DataFrame([
                ["SKU001", "测试商品", "测试", 10.0, 2.3333, 6],
                ["SKU002", "无明细商品", "测试", 20.0, 5.0, 0],
            ], columns=["sku", "product_name", "category", "price", "rating", "review_count"]),
            "sales": pd.DataFrame([
                ["2026-01-01", "SKU001", 1, 2, 20.0, 10, 0.1],
                ["2026-01-02", "SKU001", 9, 10, 100.0, 900, 0.01],
                ["2026-01-03", "SKU001", 2, 2, 20.0, 100, 0.02],
                ["2026-01-04", "SKU001", 4, 5, 50.0, 100, 0.04],
            ], columns=["date", "sku", "orders", "units", "revenue", "sessions",
                        "conversion_rate"]),
            "inventory": pd.DataFrame([
                [f"2026-01-0{i}", "SKU001", stock]
                for i, stock in enumerate([20, 10, 8, 3], 1)
            ], columns=["date", "sku", "inventory"]),
            "reviews": pd.DataFrame([
                ["2026-01-01", "SKU001", 5, "好"],
                ["2026-01-02", "SKU001", 1, "差1"],
                ["2026-01-02", "SKU001", 1, "差2"],
                ["2026-01-02", "SKU001", 1, "差3"],
                ["2026-01-03", "SKU001", 4, "不错"],
                ["2026-01-04", "SKU001", 2, "待改善"],
            ], columns=["date", "sku", "rating", "review_text"]),
        }

    def load(self) -> CsvDataStore:
        for name, frame in self.tables.items():
            frame.to_csv(self.path / f"{name}.csv", index=False)
        return CsvDataStore(self.path)

    def test_product_normalization_and_missing_sku(self) -> None:
        store = self.load()
        self.assertEqual(get_product_info(store, " sku001 ")["product"]["price"], 10)
        self.assertEqual(get_product_info(store, "SKU999")["status"], "not_found")
        with self.assertRaises(ValueError):
            get_product_info(store, "001")

    def test_weighted_sales_conversion_and_currency(self) -> None:
        result = get_sales_data(self.load(), "SKU001", "2026-01-01", "2026-01-02")
        self.assertEqual(result["metrics"]["units"], 12)
        self.assertEqual(result["metrics"]["revenue"], 120)
        self.assertAlmostEqual(result["metrics"]["conversion_rate"], 10 / 910)
        self.assertNotAlmostEqual(result["metrics"]["conversion_rate"], 0.055)
        self.assertEqual(result["coverage"]["observed_days"], 2)

    def test_single_day_inclusive_boundary(self) -> None:
        result = get_sales_data(self.load(), "SKU001", "2026-01-02", "2026-01-02")
        self.assertEqual(result["metrics"]["orders"], 9)
        self.assertTrue(result["coverage"]["complete"])

    def test_no_rows_is_not_zero(self) -> None:
        store = self.load()
        for sku in ("SKU001", "SKU002"):
            result = get_sales_data(store, sku, "2020-01-01", "2020-01-02")
            self.assertEqual(result["status"], "no_data")
            self.assertTrue(all(value is None for value in result["metrics"].values()))

    def test_partial_dates_and_no_silent_fill(self) -> None:
        self.tables["sales"] = self.tables["sales"].drop(index=1)
        store = self.load()
        result = get_sales_data(store, "SKU001", "2026-01-01", "2026-01-02")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["missing_dates"], ["2026-01-02"])
        self.assertEqual(result["metrics"]["orders"], 1)
        comparison = compare_sales_periods(
            store, "SKU001", "2026-01-03", "2026-01-04", "2026-01-01", "2026-01-02"
        )
        self.assertEqual(comparison["status"], "insufficient_data")
        self.assertIsNone(comparison["changes"])

    def test_invalid_dates_and_reverse_range(self) -> None:
        store = self.load()
        for start, end in [("2026-02-30", "2026-03-01"), ("2026-1-1", "2026-01-02"),
                           ("2026-01-04", "2026-01-01"), ("today", "2026-01-04")]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                get_sales_data(store, "SKU001", start, end)

    def test_comparison_hand_calculated_changes_and_percentage_points(self) -> None:
        result = compare_sales_periods(
            self.load(), "SKU001", "2026-01-03", "2026-01-04", "2026-01-01", "2026-01-02"
        )
        self.assertEqual(result["changes"]["orders"]["absolute_change"], -4)
        self.assertAlmostEqual(result["changes"]["orders"]["relative_change"], -0.4)
        self.assertAlmostEqual(result["conversion_rate_percentage_point_change"],
                               (6 / 200 - 10 / 910) * 100)
        self.assertEqual(result["current"]["daily_averages"]["units"], 3.5)

    def test_overlapping_or_reversed_comparisons_rejected(self) -> None:
        store = self.load()
        for dates in [("2026-01-02", "2026-01-04", "2026-01-01", "2026-01-02"),
                      ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04")]:
            with self.assertRaises(ValueError):
                compare_sales_periods(store, "SKU001", *dates)

    def test_unequal_windows_warn_and_supply_daily_averages(self) -> None:
        result = compare_sales_periods(
            self.load(), "SKU001", "2026-01-03", "2026-01-04", "2026-01-01", "2026-01-01"
        )
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["previous"]["daily_averages"]["orders"], 1)

    def test_zero_baseline_and_zero_sessions(self) -> None:
        sales = self.tables["sales"]
        sales.loc[:1, ["orders", "units", "revenue", "sessions"]] = 0
        sales.loc[:1, "conversion_rate"] = float("nan")
        result = compare_sales_periods(
            self.load(), "SKU001", "2026-01-03", "2026-01-04", "2026-01-01", "2026-01-02"
        )
        self.assertIsNone(result["previous"]["metrics"]["conversion_rate"])
        self.assertIsNone(result["changes"]["orders"]["relative_change"])
        self.assertEqual(result["changes"]["orders"]["relative_change_reason"], "zero_baseline")
        json.dumps(result, allow_nan=False)

    def test_zero_orders_with_visits_is_zero_conversion(self) -> None:
        self.tables["sales"].loc[:, ["orders", "units", "revenue", "conversion_rate"]] = 0
        result = get_sales_data(self.load(), "SKU001", "2026-01-01", "2026-01-04")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["conversion_rate"], 0)

    def test_inventory_uses_endpoint_and_complete_sales_average(self) -> None:
        result = get_inventory_data(self.load(), "SKU001", "2026-01-01", "2026-01-04")
        self.assertEqual(result["current_inventory"], 3)
        self.assertEqual(result["inventory_change"], -17)
        self.assertEqual(result["trend"], "down")
        self.assertAlmostEqual(result["estimated_stock_days"], 3 / (19 / 4))
        self.assertEqual(len(result["history"]), 4)

    def test_inventory_missing_endpoint_not_carried_forward(self) -> None:
        self.tables["inventory"] = self.tables["inventory"].iloc[:3]
        result = get_inventory_data(self.load(), "SKU001", "2026-01-01", "2026-01-04")
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["current_inventory"])
        self.assertIsNone(result["estimated_stock_days"])
        self.assertEqual(result["estimate_unavailable_reason"], "missing_end_date_inventory")

    def test_inventory_missing_sales_suppresses_estimate(self) -> None:
        self.tables["sales"] = self.tables["sales"].drop(index=1)
        result = get_inventory_data(self.load(), "SKU001", "2026-01-01", "2026-01-04")
        self.assertIsNone(result["estimated_stock_days"])
        self.assertEqual(result["estimate_unavailable_reason"], "sales_data_incomplete")

    def test_inventory_zero_sales(self) -> None:
        self.tables["sales"].loc[:, ["orders", "units", "revenue", "conversion_rate"]] = 0
        result = get_inventory_data(self.load(), "SKU001", "2026-01-01", "2026-01-04")
        self.assertIsNone(result["estimated_stock_days"])
        self.assertEqual(result["estimate_unavailable_reason"], "zero_sales")

    def test_zero_inventory_with_positive_sales_means_zero_stock_days(self) -> None:
        self.tables["inventory"].loc[3, "inventory"] = 0
        result = get_inventory_data(self.load(), "SKU001", "2026-01-01", "2026-01-04")
        self.assertEqual(result["current_inventory"], 0)
        self.assertEqual(result["estimated_stock_days"], 0)
        self.assertIsNone(result["estimate_unavailable_reason"])

    def test_review_event_weighting_and_change(self) -> None:
        result = get_review_data(self.load(), "SKU001", "2026-01-03", "2026-01-04")
        self.assertEqual(result["previous"]["metrics"]["average_rating"], 2)
        self.assertEqual(result["metrics"]["average_rating"], 3)
        self.assertEqual(result["rating_change"], 1)

    def test_low_ratings_sorted_and_truncation_disclosed(self) -> None:
        result = get_review_data(self.load(), "SKU001", "2026-01-01", "2026-01-04", 2)
        self.assertEqual(result["metrics"]["low_rating_count"], 4)
        self.assertEqual(len(result["low_rating_reviews"]), 2)
        self.assertEqual(result["low_rating_reviews"][0]["date"], "2026-01-04")
        self.assertTrue(result["low_rating_reviews_truncated"])

    def test_reviews_empty_and_outside_span(self) -> None:
        store = self.load()
        empty = get_review_data(store, "SKU002", "2026-01-01", "2026-01-04")
        self.assertEqual(empty["status"], "no_data")
        self.assertIsNone(empty["metrics"]["average_rating"])
        partial = get_review_data(store, "SKU001", "2025-12-01", "2026-01-04")
        self.assertEqual(partial["status"], "partial")
        self.assertIsNone(partial["rating_change"])

    def test_sparse_review_days_are_not_missing_daily_rows(self) -> None:
        self.tables["reviews"] = self.tables["reviews"].drop(index=4)
        result = get_review_data(self.load(), "SKU001", "2026-01-03", "2026-01-04")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["review_count"], 1)

    def test_bad_review_limit(self) -> None:
        store = self.load()
        for limit in (0, 101, True, 1.5):
            with self.assertRaises(ValueError):
                get_review_data(store, "SKU001", low_rating_limit=limit)

    def test_unknown_sku_consistent_and_json_serializable(self) -> None:
        store = self.load()
        results = [get_product_info(store, "SKU999"),
                   get_sales_data(store, "SKU999", "2026-01-01", "2026-01-04"),
                   get_inventory_data(store, "SKU999"), get_review_data(store, "SKU999")]
        for result in results:
            self.assertEqual(result["status"], "not_found")
        json.dumps(results, allow_nan=False)

    def test_snapshot_copy_and_date_anchor(self) -> None:
        store = self.load()
        frame = store.table("sales")
        frame.loc[:, "orders"] = 999
        self.assertEqual(store.table("sales").iloc[0]["orders"], 1)
        self.assertEqual(store.as_of_date, "2026-01-04")

    def test_reject_duplicate_unknown_reference_and_bad_schema(self) -> None:
        for name, mutation, expected in [
            ("sales", lambda frame: pd.concat([frame, frame.iloc[:1]]), "主键重复"),
            ("reviews", lambda frame: frame.assign(sku="SKU999"), "未知SKU"),
            ("products", lambda frame: frame.drop(columns="price"), "字段"),
        ]:
            original = self.tables[name]
            self.tables[name] = mutation(original)
            with self.subTest(name=name), self.assertRaisesRegex(DataValidationError, expected):
                self.load()
            self.tables[name] = original

    def test_reject_invalid_numeric_and_daily_formula(self) -> None:
        for column, value, pattern in [("units", -1, "非负"), ("orders", 1.5, "整数"),
                                       ("revenue", float("inf"), "有限"),
                                       ("conversion_rate", 0.8, "不一致"),
                                       ("revenue", 21, "收入")]:
            original = self.tables["sales"].copy()
            self.tables["sales"][column] = self.tables["sales"][column].astype(float)
            self.tables["sales"].loc[0, column] = value
            with self.subTest(column=column), self.assertRaisesRegex(DataValidationError, pattern):
                self.load()
            self.tables["sales"] = original

    def test_missing_file_error_includes_filename(self) -> None:
        self.load()
        (self.path / "sales.csv").unlink()
        with self.assertRaisesRegex(DataValidationError, "sales.csv"):
            CsvDataStore(self.path)


class RealDatasetTests(unittest.TestCase):
    def test_real_scenarios_and_json_outputs(self) -> None:
        store = CsvDataStore()
        current_start, end = "2026-08-24", "2026-09-22"
        old_start, old_end = "2026-07-25", "2026-08-23"
        for sku in ("SKU001", "SKU002", "SKU004"):
            result = compare_sales_periods(store, sku, current_start, end, old_start, old_end)
            self.assertEqual(result["status"], "ok")
            json.dumps(result, allow_nan=False)
            if sku == "SKU001":
                self.assertLess(result["changes"]["sessions"]["relative_change"], -0.3)
            if sku == "SKU002":
                self.assertLess(result["changes"]["conversion_rate"]["relative_change"], -0.35)
            if sku == "SKU004":
                self.assertGreater(result["changes"]["units"]["relative_change"], 0.28)
        inventory = get_inventory_data(store, "SKU003")
        self.assertEqual(inventory["current_inventory"], 50)
        self.assertAlmostEqual(inventory["estimated_stock_days"], 50 / (2312 / 30))
        reviews = get_review_data(store, "SKU005")
        self.assertAlmostEqual(reviews["metrics"]["average_rating"], 2.1)
        self.assertLess(reviews["rating_change"], -1.5)
        json.dumps([inventory, reviews, get_product_info(store, "SKU001")], allow_nan=False)


if __name__ == "__main__":
    unittest.main()
