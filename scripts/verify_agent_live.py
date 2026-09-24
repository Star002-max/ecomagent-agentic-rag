"""Explicit opt-in live acceptance; consumes real API calls and stops on errors."""

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.agent.model import create_model, redact
from src.agent.runner import ProductAgent
from src.config import PROJECT_ROOT, load_settings
from src.services import CsvDataStore
from src.tools import build_tools


CASES = [
    ("inventory", "SKU003现在有多少库存？", "get_inventory_data"),
    ("sales", "查询SKU001最近30天的销量、销售额和转化率。", "get_sales_data"),
    ("comparison", "比较SKU002最近30天和之前30天的销售表现。", "compare_sales_periods"),
    ("missing_product", "查询SKU999的商品基本信息。", "get_product_info"),
]


def check_case(case: str, result: dict, expected_tool: str) -> list[str]:
    """Check the known fixture, not choose tools or manufacture model answers."""
    if result["status"] != "completed":
        raise ValueError(f"{case}: loop没有完成。")
    calls = [item for item in result["tool_calls"] if item["name"] == expected_tool]
    if not calls:
        raise ValueError(f"{case}: 模型没有调用预期的{expected_tool}。")
    payload = calls[-1]["result"]
    data = payload["data"]
    answer = result["answer"].replace(",", "").replace("，", "")
    if case == "inventory":
        valid = data["current_inventory"] == 50 and "50" in answer
    elif case == "sales":
        valid = (data["start_date"] == "2026-08-24" and data["end_date"] == "2026-09-22"
                 and data["metrics"]["units"] == 1205 and "1205" in answer)
    elif case == "comparison":
        valid = (data["current"]["start_date"] == "2026-08-24"
                 and data["current"]["end_date"] == "2026-09-22"
                 and data["previous"]["start_date"] == "2026-07-25"
                 and data["previous"]["end_date"] == "2026-08-23"
                 and data["changes"]["units"]["relative_change"] < -0.35
                 and not any(word in answer for word in ("主要原因", "导致")))
    else:
        valid = payload["status"] == "not_found" and any(
            word in answer for word in ("不存在", "未找到", "没有找到", "未查到", "无此")
        )
    if not valid:
        raise ValueError(f"{case}: 实际工具数据或关键回答不符合验收条件。")
    return ["loop完成", "模型调用预期工具", "关键数据/日期检查通过"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=PROJECT_ROOT / "docs" / "phase4_live_results.json")
    args = parser.parse_args()
    settings = load_settings()
    store = CsvDataStore()
    agent = ProductAgent(create_model(settings), build_tools(store), store.as_of_date,
                         api_key=settings.api_key)
    report = {"tested_at_utc": datetime.now(timezone.utc).isoformat(),
              "model": settings.model, "data_as_of": store.as_of_date,
              "mode": "real_api", "cases": [],
              "limitations": "固定模拟数据的集成验收，不是完整的自然语言事实核验。"}
    try:
        for case, question, expected in CASES:
            result = asdict(agent.run(question))
            report["cases"].append({"case": case, "question": question, **result})
            report["cases"][-1]["checks"] = check_case(case, result, expected)
            print(f"PASS {case}: model_calls={result['model_calls']}")
        report["status"] = "passed"
    except Exception as exc:
        # Save only a redacted summary; no traceback, HTTP headers or raw responses.
        report["status"] = "failed"
        report["error"] = redact(str(exc), settings.api_key)
        print(f"STOP {report['error']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(redact(json.dumps(report, ensure_ascii=False, indent=2,
                                            allow_nan=False), settings.api_key) + "\n",
                           encoding="utf-8")
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
