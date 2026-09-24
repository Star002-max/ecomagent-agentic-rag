"""Inspect tool definitions and manually invoke tools offline, not via an LLM."""

import argparse
import json

from src.services import CsvDataStore
from src.tools import build_tools, describe_tools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schemas-only", action="store_true")
    args = parser.parse_args()
    tools = build_tools(CsvDataStore())
    if args.schemas_only:
        print(json.dumps(describe_tools(tools), ensure_ascii=False, indent=2))
        return
    by_name = {tool.name: tool for tool in tools}
    examples = [
        ("get_product_info", {"sku": "SKU001"}),
        ("get_sales_data", {"sku": "SKU001", "start_date": "2026-08-24",
                            "end_date": "2026-09-22"}),
        ("compare_sales_periods", {"sku": "SKU002", "current_start": "2026-08-24",
                                   "current_end": "2026-09-22",
                                   "previous_start": "2026-07-25",
                                   "previous_end": "2026-08-23"}),
        ("get_inventory_data", {"sku": "SKU003"}),
        ("get_review_data", {"sku": "SKU005", "low_rating_limit": 2}),
        ("get_product_info", {"sku": "SKU999"}),
        ("get_sales_data", {"sku": "SKU001"}),
    ]
    print("以下工具名和参数由演示脚本明确指定，不是LLM自主选择。")
    for name, arguments in examples:
        result = by_name[name].invoke(arguments)
        print(json.dumps({"name": name, "arguments": arguments,
                          "result": json.loads(result)}, ensure_ascii=False, indent=2))
    # A synthetic tool_call demonstrates LangChain's transport wrapper only.
    message = by_name["get_inventory_data"].invoke({
        "type": "tool_call", "id": "manual-demo-001",
        "name": "get_inventory_data", "args": {"sku": "SKU003"},
    })
    print("人工构造tool_call后的ToolMessage：")
    print(message.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
