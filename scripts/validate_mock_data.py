"""Independently verify CSV integrity, metric definitions and designed patterns.

This is a Phase 1 acceptance script, not a data service or an Agent tool.
"""

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "products": ["sku", "product_name", "category", "price", "rating",
                 "review_count"],
    "sales": ["date", "sku", "orders", "units", "revenue", "sessions",
              "conversion_rate"],
    "inventory": ["date", "sku", "inventory"],
    "reviews": ["date", "sku", "rating", "review_text"],
}


def require(condition: bool, message: str) -> None:
    """Fail loudly even when Python runs with optimization enabled."""
    if not condition:
        raise ValueError(message)


def period_summary(frame: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Calculate acceptance metrics from totals, never mean daily rates.

    An empty window means no observations. A zero denominator is undefined.
    Neither case is silently converted to a zero conversion rate.
    """
    if frame.empty:
        return {key: None for key in
                ("orders", "units", "revenue", "sessions", "conversion_rate")}
    result = {key: float(frame[key].sum()) for key in
              ("orders", "units", "revenue", "sessions")}
    result["conversion_rate"] = (
        result["orders"] / result["sessions"] if result["sessions"] else None
    )
    return result


def relative_change(current: float, previous: float) -> Optional[float]:
    """Return fractional change; zero baseline has no defined growth rate."""
    return current / previous - 1 if previous else None


def validate_tables(tables: Dict[str, pd.DataFrame],
                    end_date: date) -> pd.DataFrame:
    """Validate four tables and return measured evidence for all 15 SKUs."""
    require(set(tables) == set(SCHEMAS), "只能包含四类 V1 数据。")
    expected_skus = {f"SKU{i:03d}" for i in range(1, 16)}
    dates = {(end_date - timedelta(days=i)).isoformat() for i in range(180)}
    for name, columns in SCHEMAS.items():
        frame = tables[name]
        require(list(frame.columns) == columns, f"{name}: 字段或字段顺序错误。")
        require(not frame.isna().any().any(), f"{name}: 存在缺失值。")
        require(set(frame["sku"]) == expected_skus, f"{name}: SKU 不完整或未知。")
        for column in frame.select_dtypes(include="object"):
            require(frame[column].astype(str).str.strip().ne("").all(),
                    f"{name}.{column}: 存在空文本。")
        if "date" in columns:
            require(set(frame["date"]) == dates, f"{name}: 日期范围不符合180天。")
            for sku, group in frame.groupby("sku"):
                require(set(group["date"]) == dates,
                        f"{name}.{sku}: 日期不完整。")
        if name in ("sales", "inventory"):
            require(not frame.duplicated(["date", "sku"]).any(),
                    f"{name}: date/sku 重复。")
            require(len(frame) == 2700, f"{name}: 应为2700行。")

    numeric_columns = {
        "products": ["price", "rating", "review_count"],
        "sales": ["orders", "units", "revenue", "sessions", "conversion_rate"],
        "inventory": ["inventory"], "reviews": ["rating"],
    }
    for name, columns in numeric_columns.items():
        for column in columns:
            values = pd.to_numeric(tables[name][column], errors="raise")
            require(values.map(math.isfinite).all(), f"{name}.{column}: 非有限数。")
            require(values.ge(0).all(), f"{name}.{column}: 不能为负数。")
            if column in ("orders", "units", "sessions", "review_count",
                          "inventory") or (name == "reviews" and column == "rating"):
                require(values.mod(1).eq(0).all(), f"{name}.{column}: 必须为整数。")

    products = tables["products"]
    sales = tables["sales"]
    inventory = tables["inventory"]
    reviews = tables["reviews"]
    require(len(products) == 15 and not products["sku"].duplicated().any(),
            "products: 每个SKU必须只有一行。")
    require(products["price"].gt(0).all(), "products: 价格必须为正。")
    require((products["price"] * 100 - (products["price"] * 100).round())
            .abs().lt(1e-6).all(), "products: 价格最多两位小数。")
    require(products["rating"].between(1, 5).all(), "products: 评分越界。")
    require(reviews["rating"].between(1, 5).all(), "reviews: 评分越界。")
    require(len(reviews) == 5400 and
            reviews.groupby(["sku", "date"]).size().eq(2).all(),
            "reviews: 每个商品每天应有两条评价。")
    require(sales["sessions"].gt(0).all(), "sales: 本模拟集每天访问量应大于0。")
    require(sales["orders"].le(sales["sessions"]).all(), "订单不能超过访问量。")
    require(sales["units"].ge(sales["orders"]).all(), "件数不能少于订单数。")
    calculated_rates = sales["orders"] / sales["sessions"]
    require((calculated_rates - sales["conversion_rate"]).abs().le(5.1e-11).all(),
            "sales: conversion_rate 必须为 orders/sessions。")
    joined = sales.merge(products[["sku", "price"]], on="sku", validate="many_to_one")
    require((joined["revenue"] * 100 - (joined["revenue"] * 100).round())
            .abs().lt(1e-6).all(), "sales: 金额最多两位小数。")
    require(((joined["price"] * 100).round() * joined["units"] -
             (joined["revenue"] * 100).round()).abs().lt(1e-6).all(),
            "sales: revenue 必须等于 units × price。")
    review_stats = reviews.groupby("sku")["rating"].agg(["mean", "count"])
    product_stats = products.set_index("sku").join(review_stats)
    require(product_stats["review_count"].eq(product_stats["count"]).all(),
            "products: review_count 与评价明细不一致。")
    require((product_stats["rating"] - product_stats["mean"].round(4))
            .abs().lt(1e-8).all(), "products: rating 与评价明细均值不一致。")

    latest_start = (end_date - timedelta(days=29)).isoformat()
    previous_start = (end_date - timedelta(days=59)).isoformat()
    evidence = []
    for sku in sorted(expected_skus):
        sku_sales = sales[sales["sku"] == sku]
        recent = period_summary(sku_sales[sku_sales["date"] >= latest_start])
        previous = period_summary(sku_sales[
            (sku_sales["date"] >= previous_start) &
            (sku_sales["date"] < latest_start)
        ])
        require(recent["units"] > 0 and previous["units"] > 0
                and previous["orders"] > 0,
                f"{sku}: 本模拟场景两期应均有销售，不能估算零销量可售天数。")
        row = {"sku": sku}
        for metric in ("orders", "units", "revenue", "sessions", "conversion_rate"):
            row[f"previous_{metric}"] = previous[metric]
            row[f"recent_{metric}"] = recent[metric]
            row[f"{metric}_change"] = relative_change(recent[metric], previous[metric])
        row["conversion_pp_change"] = (
            recent["conversion_rate"] - previous["conversion_rate"]
        ) * 100
        sku_inventory = inventory[inventory["sku"] == sku].sort_values("date")
        stock_sales = sku_inventory.merge(sku_sales[["date", "units"]], on="date")
        # A nonnegative implied replenishment checks physical consistency.
        implied_receipts = stock_sales["inventory"].diff() + stock_sales["units"]
        require(implied_receipts.iloc[1:].ge(0).all(), f"{sku}: 库存流转不一致。")
        row["current_inventory"] = int(sku_inventory.iloc[-1]["inventory"])
        row["stock_days"] = row["current_inventory"] / (recent["units"] / 30)
        if sku == "SKU003":
            require(implied_receipts.iloc[1:].eq(0).all(), "SKU003 应无补货。")
            require(row["current_inventory"] == 50 and row["stock_days"] < 3,
                    "SKU003 应库存50件且可售天数小于3。")
        else:
            require(row["stock_days"] > 7, f"{sku}: 非预期库存风险。")
        sku_reviews = reviews[reviews["sku"] == sku]
        row["recent_rating"] = float(sku_reviews[
            sku_reviews["date"] >= latest_start]["rating"].mean())
        row["previous_rating"] = float(sku_reviews[
            (sku_reviews["date"] >= previous_start) &
            (sku_reviews["date"] < latest_start)]["rating"].mean())
        row["rating_change"] = row["recent_rating"] - row["previous_rating"]
        evidence.append(row)

    report = pd.DataFrame(evidence).set_index("sku")
    for sku, row in report.iterrows():
        traffic = row["sessions_change"]
        conversion = row["conversion_rate_change"]
        units = row["units_change"]
        if sku == "SKU001":
            require(-0.40 < traffic < -0.30 and abs(conversion) < 0.05
                    and -0.42 < units < -0.28, "SKU001 流量下降设计未达标。")
        elif sku in ("SKU002", "SKU005"):
            require(abs(traffic) < 0.05 and -0.45 < conversion < -0.35
                    and -0.47 < units < -0.33, f"{sku} 转化下降设计未达标。")
        elif sku == "SKU004":
            require(0.30 < traffic < 0.40 and abs(conversion) < 0.05
                    and 0.28 < units < 0.42, "SKU004 增长设计未达标。")
        else:
            require(abs(traffic) < 0.05 and abs(conversion) < 0.05
                    and abs(units) < 0.08, f"{sku} 正常波动设计未达标。")
        require(row["rating_change"] < -1.5 if sku == "SKU005"
                else abs(row["rating_change"]) < 0.5,
                f"{sku} 评分设计未达标。")
    return report


def validate_directory(data_dir: Path) -> pd.DataFrame:
    """Read exported CSVs back and verify them against their manifest."""
    manifest = json.loads((data_dir / "dataset_manifest.json").read_text("utf-8"))
    end_date = date.fromisoformat(manifest["end_date"])
    require(manifest["days"] == 180 and manifest["sku_count"] == 15
            and manifest["recent_days"] == 30 and manifest["synthetic"] is True
            and manifest["schema_version"] == 1 and manifest["currency"] == "CNY",
            "manifest: 数据规格错误。")
    require(manifest["start_date"] == (end_date - timedelta(days=179)).isoformat(),
            "manifest: 起止日期不一致。")
    require({p.stem for p in data_dir.glob("*.csv")} == set(SCHEMAS),
            "data目录必须恰好包含四个规定的CSV。")
    tables = {name: pd.read_csv(data_dir / f"{name}.csv") for name in SCHEMAS}
    require(manifest["rows"] == {key: len(value) for key, value in tables.items()},
            "manifest: 行数与文件不一致。")
    return validate_tables(tables, end_date)


def main() -> None:
    """Print measured comparisons; optionally save the full evidence CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = validate_directory(args.data_dir)
        print("PASS：四表结构、180天完整性、指标口径、库存及15个SKU现象全部通过。")
        print(report[["sessions_change", "units_change", "conversion_rate_change",
                      "rating_change", "stock_days"]].round(4).to_string())
        print("change列为小数比例：-0.35表示下降35%；rating_change为评分差。")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            report.to_csv(args.report, encoding="utf-8")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"验证失败：{exc}\n")


if __name__ == "__main__":
    main()
