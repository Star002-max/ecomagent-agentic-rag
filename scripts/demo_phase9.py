"""Run a deterministic, completely offline Agent → Tool → RAG demonstration."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.memory import ConversationMemory
from src.agent.runner import ProductAgent
from src.config import EmbeddingSettings
from src.rag import build_knowledge_base
from src.rag.knowledge_base import LocalHashEmbeddings
from src.services import CsvDataStore
from src.tools import build_tools


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class DemoFakeModel:
    """Scripted model protocol for teaching; it is not an LLM or quality test."""

    def bind_tools(self, definitions: list[dict]) -> "DemoFakeModel":
        self._tool_names = {item["function"]["name"] for item in definitions}
        return self

    def invoke(self, messages: list) -> AIMessage:
        current_question = next(
            message.content for message in reversed(messages)
            if isinstance(message, HumanMessage)
        )
        current_question_index = max(
            index for index, message in enumerate(messages)
            if isinstance(message, HumanMessage)
        )
        current_tool_messages = [
            message for message in messages[current_question_index + 1:]
            if isinstance(message, ToolMessage)
        ]
        if current_tool_messages:
            return AIMessage(content=(
                "【脚本化 Fake Model】本轮工具调用已完成。请以输出的真实离线工具结果和"
                "RAG 片段为准；这段固定文本不代表模型生成的业务结论。"
            ))

        if "search_operation_knowledge" not in self._tool_names:
            raise RuntimeError("离线 Demo 未注册知识检索工具。")
        if "还能卖多久" in current_question:
            return AIMessage(content="", tool_calls=[
                tool_call("get_inventory_data", {"sku": "SKU003"}, "demo-inventory-2"),
                tool_call("search_operation_knowledge", {
                    "query": "可售天数库存风险分级和处理建议", "k": 2,
                }, "demo-rag-2"),
            ])
        return AIMessage(content="", tool_calls=[
            tool_call("get_inventory_data", {"sku": "SKU003"}, "demo-inventory-1"),
        ])


def print_result(label: str, result) -> None:
    print(f"\n{label}\nFake Model回答：{result.answer}")
    for item in result.tool_calls:
        summary = {"tool": item["name"], "status": item["result"]["status"]}
        data = item["result"].get("data") or {}
        if item["name"] == "search_operation_knowledge":
            summary["matches"] = [
                {"source": match["source"], "section": match.get("section"),
                 "content": match["content"]}
                for match in data.get("matches", [])
            ]
        elif "current_inventory" in data:
            summary["current_inventory"] = data["current_inventory"]
            summary["days_of_supply"] = data.get("days_of_supply")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    # Explicit injection keeps this entry point offline even if the shell has
    # EMBEDDING_PROVIDER=aliyun or cloud credentials configured.
    settings = EmbeddingSettings(provider="local_hash")
    knowledge_base = build_knowledge_base(
        embeddings=LocalHashEmbeddings(), settings=settings)
    store = CsvDataStore()
    tools = build_tools(store, knowledge_base)
    memory = ConversationMemory()
    agent = ProductAgent(DemoFakeModel(), tools, store.as_of_date, memory=memory)

    print("离线演示：Fake Model + 本地 CSV Tools + LocalHash/Chroma RAG；不调用任何 API。")
    first = agent.run("SKU003现在有多少库存？")
    print_result("第1轮：查询库存", first)
    second = agent.run("它按最近销售速度还能卖多久？请结合库存规则。")
    print_result("第2轮：使用 Memory 指代并重新查询", second)
    print(f"\n同一 Memory 中保留 {len(memory.turns)} 轮完整对话。")
    print("注意：Fake Model 固定文本仅展示 Agent 控制流，不是 LLM 问答质量验收。")


if __name__ == "__main__":
    main()
