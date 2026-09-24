"""Run one real model question. No API credentials are accepted on the CLI."""

import argparse
import json

from src.agent.model import ModelRequestError, create_model, redact
from src.agent.runner import AgentExecutionError, ProductAgent
from src.config import load_settings
from src.services import CsvDataStore
from src.tools import build_tools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="商品查询或周期比较问题")
    parser.add_argument("--show-tools", action="store_true", help="显示工具名、参数和状态")
    args = parser.parse_args()
    settings = None
    try:
        settings = load_settings()
        store = CsvDataStore()
        agent = ProductAgent(create_model(settings), build_tools(store), store.as_of_date,
                             api_key=settings.api_key)
        result = agent.run(args.question)
    except (ValueError, ModelRequestError, AgentExecutionError) as exc:
        parser.exit(1, redact(str(exc), settings.api_key if settings else "") + "\n")
    print(result.answer)
    if args.show_tools:
        print(json.dumps({"status": result.status, "model_calls": result.model_calls,
                          "tools": [{"name": item["name"], "arguments": item["arguments"],
                                     "status": item["result"]["status"]}
                                    for item in result.tool_calls]},
                         ensure_ascii=False, indent=2))
    if result.status != "completed":
        parser.exit(1)


if __name__ == "__main__":
    main()
