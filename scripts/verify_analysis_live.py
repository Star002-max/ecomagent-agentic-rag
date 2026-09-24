"""Run exactly two real Phase 5 analyses and save a redacted acceptance record."""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from src.agent.model import create_model, redact
from src.agent.runner import ProductAgent
from src.config import PROJECT_ROOT, load_settings
from src.services import CsvDataStore
from src.tools import build_tools


CASES = [
    ("sku001_sales", "分析SKU001最近30天表现，销量下降主要体现在哪些指标？"),
    ("sku005_sales_reviews", "分析SKU005最近30天的销售和评论变化，有什么值得关注的问题？"),
]


def latest_success(result: dict, name: str) -> dict:
    matches = [item["result"]["data"] for item in result["tool_calls"]
               if item["name"] == name and item["result"]["status"] == "ok"]
    if not matches:
        raise ValueError(f"没有成功调用{name}。")
    return matches[-1]


def validate_case(case: str, result: dict) -> list[str]:
    """Check known fixture facts and required evidence categories."""
    if result["status"] != "completed" or not result["structured_output"]:
        raise ValueError(f"{case}: 未返回完成的结构化结果。")
    report = result["structured_output"]
    comparison = latest_success(result, "compare_sales_periods")
    if comparison["current"]["start_date"] != "2026-08-24" or (
        comparison["previous"]["start_date"] != "2026-07-25"
    ):
        raise ValueError(f"{case}: 比较日期不正确。")
    factual_text = " ".join([report["summary"], *report["findings"]])
    causal_phrases = ("主要原因", "导致", "原因是", "驱动", "归因", "根因")
    if any(phrase in factual_text for phrase in causal_phrases):
        raise ValueError(f"{case}: 已确认事实包含未经证明的因果措辞。")
    limit_text = " ".join(report["evidence_limits"])
    if not any(phrase in limit_text for phrase in ("不能证明", "无法证明", "因果")):
        raise ValueError(f"{case}: 未明确说明因果证据限制。")
    if case == "sku001_sales":
        valid = (report["sku"] == "SKU001"
                 and comparison["changes"]["sessions"]["relative_change"] < -0.30
                 and abs(comparison["changes"]["conversion_rate"]["relative_change"]) < 0.05
                 and "访问" in factual_text and "转化" in factual_text)
    else:
        reviews = latest_success(result, "get_review_data")
        valid = (report["sku"] == "SKU005"
                 and comparison["changes"]["units"]["relative_change"] < -0.35
                 and reviews["rating_change"] < -1.5
                 and "评价" in factual_text and "销售" in factual_text)
    if not valid:
        raise ValueError(f"{case}: 工具事实或报告关注点不符合验收条件。")
    return ["结构化输出通过", "必要工具调用成功", "关键事实与证据限制通过"]


def main() -> None:
    settings = load_settings()
    store = CsvDataStore()
    agent = ProductAgent(create_model(settings), build_tools(store), store.as_of_date,
                         api_key=settings.api_key)
    output = {"tested_at_utc": datetime.now(timezone.utc).isoformat(),
              "model": settings.model, "data_as_of": store.as_of_date,
              "mode": "real_api", "status": "running", "cases": [],
              "planned_questions": len(CASES)}
    try:
        for case, question in CASES:
            result = asdict(agent.run_analysis(question))
            checks = validate_case(case, result)
            output["cases"].append({"case": case, "question": question,
                                    **result, "checks": checks})
            print(f"PASS {case}: model_calls={result['model_calls']}, "
                  f"tool_calls={len(result['tool_calls'])}")
        output["status"] = "passed"
        output["total_model_calls"] = sum(item["model_calls"] for item in output["cases"])
        output["total_tool_calls"] = sum(len(item["tool_calls"]) for item in output["cases"])
    except Exception as exc:
        output["status"] = "failed"
        output["error"] = redact(str(exc), settings.api_key)
        print(f"STOP {output['error']}")
    path = PROJECT_ROOT / "docs" / "phase5_live_results.json"
    path.write_text(redact(json.dumps(output, ensure_ascii=False, indent=2,
                                      allow_nan=False), settings.api_key) + "\n",
                    encoding="utf-8")
    if output["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
