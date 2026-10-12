"""Run one real Phase 5 comprehensive analysis and print validated JSON."""

import argparse
import json

from src.agent.model import ModelRequestError, create_model, redact
from src.agent.memory import ConversationMemory
from src.agent.runner import AgentExecutionError, ProductAgent
from src.config import load_settings
from src.rag import build_knowledge_base
from src.services import CsvDataStore
from src.tools import build_tools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="一个SKU的综合分析问题")
    parser.add_argument("--interactive", action="store_true",
                        help="进入连续分析对话，最多携带最近4轮已完成对话")
    parser.add_argument("--show-tools", action="store_true", help="显示实际工具名、参数和状态")
    args = parser.parse_args()
    if not args.interactive and args.question is None:
        parser.error("请提供问题，或使用--interactive进入连续对话。")
    settings = None
    try:
        settings = load_settings()
        store = CsvDataStore()
        memory = ConversationMemory()
        agent = ProductAgent(create_model(settings),
                             build_tools(store, build_knowledge_base()), store.as_of_date,
                             api_key=settings.api_key, memory=memory)
    except (ValueError, ModelRequestError, AgentExecutionError) as exc:
        parser.exit(1, redact(str(exc), settings.api_key if settings else "") + "\n")

    def answer(question: str) -> bool:
        try:
            result = agent.run_analysis(question)
        except (ValueError, ModelRequestError, AgentExecutionError) as exc:
            print(redact(str(exc), settings.api_key))
            return False
        print(json.dumps(result.structured_output, ensure_ascii=False, indent=2))
        if args.show_tools:
            print(json.dumps({"status": result.status, "model_calls": result.model_calls,
                              "tools": [{"name": item["name"], "arguments": item["arguments"],
                                         "status": item["result"]["status"]}
                                        for item in result.tool_calls]},
                             ensure_ascii=False, indent=2))
        return result.status == "completed"

    if args.interactive:
        print("连续分析对话已开始；输入空行或 /quit 结束。")
        while True:
            try:
                question = input("你：").strip()
            except EOFError:
                break
            if not question or question == "/quit":
                break
            answer(question)
    elif not answer(args.question):
        parser.exit(1)


if __name__ == "__main__":
    main()
