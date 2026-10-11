"""Run one real Phase 6 business-data plus knowledge-retrieval acceptance."""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from src.agent.model import create_model, redact
from src.agent.runner import ProductAgent
from src.config import PROJECT_ROOT, load_settings
from src.rag import build_knowledge_base
from src.services import CsvDataStore
from src.tools import build_tools


QUESTION = "分析 SKU003 当前库存风险，并根据我们的库存管理规则给出建议。"


def validate(result: dict) -> list[str]:
    if result["status"] != "completed":
        raise ValueError("Agent未完成回答。")
    names = [item["name"] for item in result["tool_calls"]]
    if "get_inventory_data" not in names or "search_operation_knowledge" not in names:
        raise ValueError("未同时调用库存数据Tool和运营知识Tool。")
    inventory = next(item["result"]["data"] for item in result["tool_calls"]
                     if item["name"] == "get_inventory_data"
                     and item["result"]["status"] == "ok")
    knowledge = next(item["result"]["data"] for item in result["tool_calls"]
                     if item["name"] == "search_operation_knowledge"
                     and item["result"]["status"] == "ok")
    if inventory["current_inventory"] != 50 or inventory["estimated_stock_days"] >= 7:
        raise ValueError("SKU003库存事实不符合Mock Data设计。")
    if not any(match["source"] == "inventory_management.md"
               for match in knowledge["matches"]):
        raise ValueError("知识检索未返回库存管理规则。")
    answer = result["answer"]
    if "高风险" not in answer or "inventory_management.md" not in answer:
        raise ValueError("最终回答未结合风险等级或知识来源。")
    return ["库存业务数据Tool成功", "库存知识检索Tool成功", "Qwen综合回答并引用source"]


def main() -> None:
    settings = load_settings()
    store = CsvDataStore()
    agent = ProductAgent(
        create_model(settings), build_tools(store, build_knowledge_base()),
        store.as_of_date, api_key=settings.api_key,
    )
    output = {
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": settings.model,
        "data_as_of": store.as_of_date,
        "mode": "real_api",
        "question": QUESTION,
        "status": "running",
    }
    try:
        result = asdict(agent.run(QUESTION))
        output.update(result)
        output["checks"] = validate(result)
        output["status"] = "passed"
        print(f"PASS: model_calls={result['model_calls']}, "
              f"tool_calls={len(result['tool_calls'])}")
    except Exception as exc:
        output["status"] = "failed"
        output["error"] = redact(str(exc), settings.api_key)
        print(f"STOP {output['error']}")
    path = PROJECT_ROOT / "docs" / "phase6_live_results.json"
    path.write_text(redact(json.dumps(output, ensure_ascii=False, indent=2,
                                      allow_nan=False), settings.api_key) + "\n",
                    encoding="utf-8")
    if output["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
