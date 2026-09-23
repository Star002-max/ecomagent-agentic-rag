"""Load a validated, read-only-in-practice snapshot of the four V1 CSVs."""

import math
from pathlib import Path

import pandas as pd


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
COLUMNS = {
    "products": ["sku", "product_name", "category", "price", "rating", "review_count"],
    "sales": ["date", "sku", "orders", "units", "revenue", "sessions", "conversion_rate"],
    "inventory": ["date", "sku", "inventory"],
    "reviews": ["date", "sku", "rating", "review_text"],
}
NUMBERS = {
    "products": ["price", "rating", "review_count"],
    "sales": ["orders", "units", "revenue", "sessions", "conversion_rate"],
    "inventory": ["inventory"], "reviews": ["rating"],
}


class DataValidationError(ValueError):
    """The data source violates a structural or numeric contract."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise DataValidationError(message)


class CsvDataStore:
    """Read CSVs once per instance; create a new instance after editing files.

    Unlike Phase 1 acceptance, this loader does not assume 15 SKUs, 180 days,
    two daily reviews or any planted anomaly. Missing days are reported by
    query services instead of being silently filled with zeros.
    """

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir).resolve()
        self._tables: dict[str, pd.DataFrame] = {}
        for name, columns in COLUMNS.items():
            path = self.data_dir / f"{name}.csv"
            try:
                frame = pd.read_csv(path, dtype={"sku": str})
            except (OSError, ValueError, pd.errors.ParserError) as exc:
                raise DataValidationError(f"无法读取 {path}: {exc}") from exc
            check(set(frame.columns) == set(columns), f"{name}: 字段不符合V1定义。")
            # Undefined conversion is permitted only for zero-session days.
            required = [col for col in columns if col != "conversion_rate"]
            check(not frame[required].isna().any().any(), f"{name}: 必填字段缺失。")
            for col in set(columns) - set(NUMBERS[name]) - {"date"}:
                check(frame[col].astype(str).str.strip().ne("").all(),
                      f"{name}.{col}: 不能是空文本。")
            check(frame["sku"].str.fullmatch(r"SKU\d{3}").all(),
                  f"{name}: SKU必须是SKU加三位数字。")
            if "date" in columns:
                check(frame["date"].astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}").all(),
                      f"{name}: 日期必须为YYYY-MM-DD。")
                try:
                    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d")
                except ValueError as exc:
                    raise DataValidationError(f"{name}: 无效日期。") from exc
            for col in NUMBERS[name]:
                try:
                    frame[col] = pd.to_numeric(frame[col], errors="raise")
                except (ValueError, TypeError) as exc:
                    raise DataValidationError(f"{name}.{col}: 必须是数值。") from exc
                values = frame[col].dropna() if col == "conversion_rate" else frame[col]
                check(values.map(math.isfinite).all() and values.ge(0).all(),
                      f"{name}.{col}: 必须是有限非负数。")
                if col in {"orders", "units", "sessions", "inventory", "review_count"} or (
                    name == "reviews" and col == "rating"
                ):
                    check(values.mod(1).eq(0).all(), f"{name}.{col}: 必须是整数。")
            key = ["sku"] if name == "products" else ["sku", "date"]
            if name != "reviews":
                check(not frame.duplicated(key).any(), f"{name}: 主键重复。")
            if "rating" in frame:
                check(frame["rating"].between(1, 5).all(), f"{name}: 评分应在1至5之间。")
            self._tables[name] = frame.sort_values(key).reset_index(drop=True)

        self._validate_relationships()

    def _validate_relationships(self) -> None:
        products, sales = self._tables["products"], self._tables["sales"]
        known_skus = set(products["sku"])
        for name, frame in self._tables.items():
            check(set(frame["sku"]).issubset(known_skus), f"{name}: 引用了未知SKU。")
        check(products["price"].gt(0).all(), "products: 价格必须大于0。")
        for frame, col in ((products, "price"), (sales, "revenue")):
            check((frame[col] * 100 - (frame[col] * 100).round()).abs().lt(1e-6).all(),
                  f"{col}: 金额最多保留两位小数。")
        check(sales["orders"].le(sales["sessions"]).all(), "sales: 订单超过访问量。")
        check(sales["units"].ge(sales["orders"]).all(), "sales: 件数少于订单。")
        check(sales.loc[sales["orders"].eq(0), "units"].eq(0).all(),
              "sales: 零订单不能有售出件数。")
        positive = sales["sessions"].gt(0)
        expected = sales.loc[positive, "orders"] / sales.loc[positive, "sessions"]
        check((sales.loc[positive, "conversion_rate"] - expected).abs().le(5.1e-11).all(),
              "sales: conversion_rate与orders/sessions不一致。")
        check(sales.loc[~positive, "conversion_rate"].isna().all(),
              "sales: 零访问时conversion_rate必须留空，表示未定义。")
        joined = sales.merge(products[["sku", "price"]], on="sku", validate="many_to_one")
        check(((joined["revenue"] * 100).round() -
               joined["units"] * (joined["price"] * 100).round()).abs().lt(1e-6).all(),
              "sales: 收入不等于件数乘固定单价。")

    @property
    def as_of_date(self) -> str:
        """Use latest observed daily-data date; never use the computer clock."""
        dates = [frame["date"].max() for name, frame in self._tables.items()
                 if name != "products" and not frame.empty]
        if not dates:
            raise DataValidationError("没有带日期的数据，无法确定分析基准日。")
        return max(dates).date().isoformat()

    def table(self, name: str) -> pd.DataFrame:
        """Return a copy so a caller cannot mutate the shared snapshot."""
        return self._tables[name].copy(deep=True)
