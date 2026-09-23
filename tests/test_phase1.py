"""Test data contracts, negative cases and deterministic generation offline."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.generate_mock_data import DEFAULT_END_DATE, build_tables, generate
from scripts.validate_mock_data import (
    period_summary, relative_change, validate_directory, validate_tables,
)


class Phase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = build_tables(42, DEFAULT_END_DATE)

    def changed_tables(self):
        return {name: frame.copy(deep=True) for name, frame in self.tables.items()}

    def test_default_data_satisfies_all_contracts(self) -> None:
        report = validate_tables(self.tables, DEFAULT_END_DATE)
        self.assertEqual(len(report), 15)

    def test_weighted_conversion_not_daily_average(self) -> None:
        frame = pd.DataFrame({
            "orders": [1, 9], "sessions": [10, 900], "units": [2, 10],
            "revenue": [20, 100], "conversion_rate": [0.10, 0.01],
        })
        rate = period_summary(frame)["conversion_rate"]
        self.assertAlmostEqual(rate, 10 / 910)
        self.assertNotAlmostEqual(rate, frame["conversion_rate"].mean())
        self.assertNotAlmostEqual(rate, 12 / 910)

    def test_empty_and_zero_denominators_are_undefined(self) -> None:
        empty = self.tables["sales"].iloc[:0]
        self.assertTrue(all(value is None for value in period_summary(empty).values()))
        zero = pd.DataFrame({"orders": [0], "units": [0], "revenue": [0],
                             "sessions": [0]})
        self.assertIsNone(period_summary(zero)["conversion_rate"])
        self.assertIsNone(relative_change(20, 0))
        self.assertIsNone(relative_change(0, 0))
        self.assertEqual(relative_change(0, 10), -1)

    def test_bad_conversion_rejected(self) -> None:
        tables = self.changed_tables()
        tables["sales"].loc[0, "conversion_rate"] = 0.99
        with self.assertRaisesRegex(ValueError, "conversion_rate"):
            validate_tables(tables, DEFAULT_END_DATE)

    def test_missing_day_and_duplicate_key_rejected(self) -> None:
        tables = self.changed_tables()
        tables["sales"] = tables["sales"].iloc[1:]
        with self.assertRaisesRegex(ValueError, "日期不完整"):
            validate_tables(tables, DEFAULT_END_DATE)
        tables = self.changed_tables()
        tables["inventory"] = pd.concat([
            tables["inventory"], tables["inventory"].iloc[:1]
        ])
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_tables(tables, DEFAULT_END_DATE)

    def test_bad_revenue_and_rating_summary_rejected(self) -> None:
        tables = self.changed_tables()
        tables["sales"].loc[0, "revenue"] += 1
        with self.assertRaisesRegex(ValueError, "revenue"):
            validate_tables(tables, DEFAULT_END_DATE)
        tables = self.changed_tables()
        tables["products"].loc[0, "rating"] = 1
        with self.assertRaisesRegex(ValueError, "均值"):
            validate_tables(tables, DEFAULT_END_DATE)

    def test_inventory_and_invalid_numbers_rejected(self) -> None:
        tables = self.changed_tables()
        tables["inventory"].loc[1, "inventory"] = 0
        with self.assertRaisesRegex(ValueError, "库存流转"):
            validate_tables(tables, DEFAULT_END_DATE)
        tables = self.changed_tables()
        tables["sales"].loc[0, "revenue"] = float("inf")
        with self.assertRaisesRegex(ValueError, "非有限数"):
            validate_tables(tables, DEFAULT_END_DATE)

    def test_pattern_regression_rejected_even_with_consistent_metrics(self) -> None:
        tables = self.changed_tables()
        # Replace SKU001 recent sales with its previous 30 days. Individual
        # formulas remain valid, but the designed traffic decline disappears.
        sales = tables["sales"]
        positions = sales.index[sales["sku"] == "SKU001"]
        columns = [col for col in sales.columns if col not in ("date", "sku")]
        sales.loc[positions[-30:], columns] = sales.loc[
            positions[-60:-30], columns].to_numpy()
        # Supply consistent replenishment so the failure targets the pattern.
        tables["inventory"].loc[tables["inventory"]["sku"] == "SKU001",
                                 "inventory"] = 1800
        with self.assertRaisesRegex(ValueError, "SKU001 流量下降"):
            validate_tables(tables, DEFAULT_END_DATE)

    def test_two_30_day_windows_have_correct_boundaries(self) -> None:
        report = validate_tables(self.tables, DEFAULT_END_DATE)
        sales = self.tables["sales"]
        sku = sales[sales["sku"] == "SKU001"]
        recent = sku[sku["date"].between("2026-08-24", "2026-09-22")]
        previous = sku[sku["date"].between("2026-07-25", "2026-08-23")]
        self.assertEqual(len(recent), 30)
        self.assertEqual(len(previous), 30)
        self.assertEqual(report.loc["SKU001", "recent_units"], recent["units"].sum())
        self.assertEqual(report.loc["SKU001", "previous_units"], previous["units"].sum())

    def test_seed_and_date_options(self) -> None:
        alternate = build_tables(7, date(2025, 12, 31))
        validate_tables(alternate, date(2025, 12, 31))
        self.assertFalse(alternate["sales"].equals(self.tables["sales"]))

    def test_csv_roundtrip_reproducibility_and_overwrite_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "a", Path(directory) / "b"
            generate(first, 42, DEFAULT_END_DATE)
            generate(second, 42, DEFAULT_END_DATE)
            for path in first.iterdir():
                self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())
            validate_directory(first)
            with self.assertRaises(FileExistsError):
                generate(first, 42, DEFAULT_END_DATE)
            generate(first, 42, DEFAULT_END_DATE, overwrite=True)
            validate_directory(first)


if __name__ == "__main__":
    unittest.main()
