"""Inventory observations and a simple, explicitly bounded coverage estimate."""

from .common import (
    base_result, coverage, daily_status, default_window, records, window,
)
from .data_loader import CsvDataStore
from .sales_service import get_sales_data


def get_inventory_data(store: CsvDataStore, sku: str,
                       start_date: str | None = None,
                       end_date: str | None = None) -> dict:
    """Return end-of-window stock, observed history and sales-based stock days.

    Default window is the last 30 dataset days. Never carry an older stock
    observation forward as if it were an observation on the requested day.
    """
    start, end = default_window(store, start_date, end_date)
    result = base_result(store, sku)
    result.update(start_date=start.isoformat(), end_date=end.isoformat(),
                  current_inventory=None, current_inventory_date=None,
                  inventory_change=None, trend=None, history=[],
                  average_daily_units=None, estimated_stock_days=None)
    if result["status"] == "not_found":
        return result
    frame = window(store.table("inventory"), result["sku"], start, end)
    info = coverage(frame, start, end)
    result.update(status=daily_status(frame, info), coverage=info,
                  history=records(frame), source="inventory.csv")
    if not frame.empty and frame.iloc[-1]["date"].date() == end:
        result["current_inventory"] = int(frame.iloc[-1]["inventory"])
        result["current_inventory_date"] = end.isoformat()
    if info["complete"] and len(frame) >= 2:
        delta = int(frame.iloc[-1]["inventory"] - frame.iloc[0]["inventory"])
        result.update(inventory_change=delta,
                      trend="up" if delta > 0 else "down" if delta < 0 else "flat")
    sales = get_sales_data(store, sku, start.isoformat(), end.isoformat())
    result["sales_coverage"] = sales.get("coverage")
    if sales["status"] != "ok":
        reason = "sales_data_incomplete"
    elif result["current_inventory"] is None:
        reason = "missing_end_date_inventory"
    elif sales["metrics"]["units"] == 0:
        result["average_daily_units"] = 0.0
        reason = "zero_sales"
    else:
        daily_units = sales["metrics"]["units"] / info["expected_days"]
        result["average_daily_units"] = daily_units
        result["estimated_stock_days"] = result["current_inventory"] / daily_units
        reason = None
    result["estimate_unavailable_reason"] = reason
    result["message"] = {"ok": "", "no_data": "当前区间没有库存数据。",
                         "partial": "库存日期不完整；不推断缺失时点的库存。"}[result["status"]]
    result["limitations"] = [
        "trend只描述区间首尾库存净变化，不表示每天都同向变化。",
        "可售天数假定未来销量与所选区间日均销量相同，未考虑在途补货或需求变化。",
    ]
    return result
