"""Run deterministic Phase 2 service examples without a model or API key."""

import json
from datetime import timedelta

from src.services import (
    CsvDataStore, compare_sales_periods, get_inventory_data, get_product_info,
    get_review_data, get_sales_data,
)
from src.services.common import parse_date


def main() -> None:
    store = CsvDataStore()
    end = parse_date(store.as_of_date)
    start = end - timedelta(days=29)
    previous_start, previous_end = end - timedelta(days=59), start - timedelta(days=1)
    examples = {
        "商品信息": get_product_info(store, "SKU001"),
        "销售汇总": get_sales_data(store, "SKU001", start.isoformat(), end.isoformat()),
        "两期比较": compare_sales_periods(
            store, "SKU002", start.isoformat(), end.isoformat(),
            previous_start.isoformat(), previous_end.isoformat(),
        ),
        "库存估算": get_inventory_data(store, "SKU003"),
        "评价变化": get_review_data(store, "SKU005"),
        "不存在的商品": get_product_info(store, "SKU999"),
        "无数据区间": get_sales_data(store, "SKU001", "2020-01-01", "2020-01-02"),
    }
    print(json.dumps(examples, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
