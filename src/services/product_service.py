"""Product snapshot lookup."""

from .common import base_result
from .data_loader import CsvDataStore


def get_product_info(store: CsvDataStore, sku: str) -> dict:
    """Return the current snapshot; it must not be treated as historical data."""
    result = base_result(store, sku)
    result["product"] = None
    if result["status"] == "not_found":
        return result
    frame = store.table("products")
    result["product"] = frame[frame["sku"].eq(result["sku"])].to_dict("records")[0]
    result["snapshot_note"] = "商品表是当前快照；历史评分请查询评价明细。"
    return result
