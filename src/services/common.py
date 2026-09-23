"""Small shared date, coverage and result helpers; no business routing."""

import re
from datetime import date, timedelta

import pandas as pd

from .data_loader import CsvDataStore


def parse_date(value: str) -> date:
    """Accept an explicit calendar date only, not a timestamp or relative text."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期必须为YYYY-MM-DD字符串。")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"无效日期：{value}") from exc


def date_range(start_date: str, end_date: str) -> tuple[date, date]:
    start, end = parse_date(start_date), parse_date(end_date)
    if start > end:
        raise ValueError("start_date不能晚于end_date。")
    if (end - start).days >= 3660:
        raise ValueError("单次查询范围不能超过3660天。")
    return start, end


def normalize_sku(sku: str) -> str:
    if not isinstance(sku, str) or not re.fullmatch(r"SKU\d{3}", sku.strip().upper()):
        raise ValueError("sku必须为SKU加三位数字，例如SKU001。")
    return sku.strip().upper()


def base_result(store: CsvDataStore, sku: str) -> dict:
    sku = normalize_sku(sku)
    found = store.table("products")["sku"].eq(sku).any()
    return {"status": "ok" if found else "not_found", "sku": sku,
            "message": "" if found else "当前数据源中没有找到该商品。"}


def window(frame: pd.DataFrame, sku: str, start: date, end: date) -> pd.DataFrame:
    return frame[frame["sku"].eq(sku) & frame["date"].between(
        pd.Timestamp(start), pd.Timestamp(end)
    )].sort_values("date")


def coverage(frame: pd.DataFrame, start: date, end: date) -> dict:
    expected = pd.date_range(start, end)
    missing = expected.difference(pd.DatetimeIndex(frame["date"]))
    return {"expected_days": len(expected), "observed_days": frame["date"].nunique(),
            "complete": len(missing) == 0,
            "missing_dates": [stamp.date().isoformat() for stamp in missing]}


def daily_status(frame: pd.DataFrame, info: dict) -> str:
    return "no_data" if frame.empty else "ok" if info["complete"] else "partial"


def records(frame: pd.DataFrame) -> list[dict]:
    copied = frame.copy()
    copied["date"] = copied["date"].dt.strftime("%Y-%m-%d")
    return copied.to_dict(orient="records")


def default_window(store: CsvDataStore, start_date: str | None,
                   end_date: str | None) -> tuple[date, date]:
    end = parse_date(end_date if end_date is not None else store.as_of_date)
    start = start_date if start_date is not None else (end - timedelta(days=29)).isoformat()
    return date_range(start, end.isoformat())


def change(current: int | float | None, previous: int | float | None) -> dict:
    difference = None if current is None or previous is None else current - previous
    return {"absolute_change": difference,
            "relative_change": None if difference is None or previous == 0
            else difference / previous,
            "relative_change_reason": "missing_value" if difference is None
            else "zero_baseline" if previous == 0 else None}
