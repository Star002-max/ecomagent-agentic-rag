"""Sales aggregation and explicit-period comparison."""

import pandas as pd

from .common import base_result, change, coverage, daily_status, date_range, window
from .data_loader import CsvDataStore


def summarize_sales(frame: pd.DataFrame) -> dict:
    """Sum counts and integer cents; recompute conversion from the totals."""
    if frame.empty:
        return dict.fromkeys(("orders", "units", "revenue", "sessions", "conversion_rate"))
    orders = int(frame["orders"].sum())
    sessions = int(frame["sessions"].sum())
    cents = int((frame["revenue"] * 100).round().sum())
    return {"orders": orders, "units": int(frame["units"].sum()),
            "revenue": cents / 100, "sessions": sessions,
            "conversion_rate": orders / sessions if sessions else None}


def get_sales_data(store: CsvDataStore, sku: str,
                   start_date: str, end_date: str) -> dict:
    """Query an inclusive window. Partial totals cover observed rows only."""
    start, end = date_range(start_date, end_date)
    result = base_result(store, sku)
    result.update(start_date=start.isoformat(), end_date=end.isoformat(), metrics=None)
    if result["status"] == "not_found":
        return result
    frame = window(store.table("sales"), result["sku"], start, end)
    info = coverage(frame, start, end)
    result.update(status=daily_status(frame, info), coverage=info,
                  metrics=summarize_sales(frame), source="sales.csv")
    result["message"] = {"ok": "", "no_data": "当前区间没有销售数据。",
                         "partial": "日期不完整；指标仅汇总已有记录，缺失日未补零。"}[result["status"]]
    return result


def compare_sales_periods(store: CsvDataStore, sku: str, current_start: str,
                          current_end: str, previous_start: str,
                          previous_end: str) -> dict:
    """Compare non-overlapping windows; suppress changes if either is incomplete."""
    start, end = date_range(current_start, current_end)
    old_start, old_end = date_range(previous_start, previous_end)
    if max(start, old_start) <= min(end, old_end):
        raise ValueError("两个比较区间不能重叠。")
    if old_end >= start:
        raise ValueError("previous区间必须早于current区间。")
    current = get_sales_data(store, sku, current_start, current_end)
    previous = get_sales_data(store, sku, previous_start, previous_end)
    result = {"sku": current["sku"], "current": current, "previous": previous,
              "changes": None, "warnings": [], "status": "ok"}
    if current["status"] == "not_found":
        result.update(status="not_found", message=current["message"])
        return result
    if current["status"] != "ok" or previous["status"] != "ok":
        result.update(status="insufficient_data", message="比较期数据不完整，不计算变化率。")
        return result
    if (end - start).days != (old_end - old_start).days:
        result["warnings"].append("两个区间天数不同；总量变化受时长影响，请同时参考日均指标。")
    result["changes"] = {
        metric: change(value, previous["metrics"][metric])
        for metric, value in current["metrics"].items()
    }
    rate_difference = result["changes"]["conversion_rate"]["absolute_change"]
    result["conversion_rate_percentage_point_change"] = (
        rate_difference * 100 if rate_difference is not None else None
    )
    for period in (current, previous):
        days = period["coverage"]["expected_days"]
        period["daily_averages"] = {
            metric: period["metrics"][metric] / days
            for metric in ("orders", "units", "revenue", "sessions")
        }
    return result
