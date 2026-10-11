"""Phase 6 offline tests for loading, Chroma retrieval, Tool, and Agent integration."""

import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.runner import ProductAgent
from src.rag.knowledge_base import (LocalHashEmbeddings, build_knowledge_base,
                                    load_markdown_documents, split_markdown_documents)
from src.services import CsvDataStore
from src.tools import build_tools, describe_tools


class ScriptedRagModel:
    """Test-only model; it checks protocol mechanics without calling an LLM."""

    def __init__(self, *responses: AIMessage) -> None:
        self.responses = iter(responses)
        self.inputs: list[list] = []

    def bind_tools(self, definitions: list[dict]) -> "ScriptedRagModel":
        self.definitions = definitions
        return self

    def invoke(self, messages: list) -> AIMessage:
        self.inputs.append(list(messages))
        return next(self.responses)


class FakeKnowledgeSearcher:
    def search(self, query: str, *, k: int = 3) -> dict:
        return {"query": query, "matches": [{
            "content": "可售天数小于7天为高风险。",
            "source": "inventory_management.md", "title": "库存管理规则",
            "section": "风险分级", "chunk_id": 0,
        }][:k]}


class BrokenKnowledgeSearcher:
    def search(self, query: str, *, k: int = 3) -> dict:
        raise RuntimeError("test retrieval failure")


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class RagPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge_base = build_knowledge_base()

    def test_four_markdown_documents_load_with_sources(self) -> None:
        documents = load_markdown_documents(Path("knowledge"))
        self.assertEqual(len(documents), 4)
        self.assertEqual({doc.metadata["source"] for doc in documents}, {
            "product_analysis_sop.md", "sales_analysis_rules.md",
            "inventory_management.md", "review_management.md",
        })

    def test_markdown_sections_split_into_bounded_chunks(self) -> None:
        documents = load_markdown_documents(Path("knowledge"))
        chunks = split_markdown_documents(documents, chunk_size=220, chunk_overlap=30)
        self.assertGreater(len(chunks), len(documents))
        self.assertTrue(all(len(chunk.page_content) <= 220 for chunk in chunks))
        self.assertEqual([chunk.metadata["chunk_id"] for chunk in chunks],
                         list(range(len(chunks))))
        self.assertTrue(all("source" in chunk.metadata for chunk in chunks))

    def test_empty_temporary_knowledge_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "没有可加载"):
                load_markdown_documents(Path(directory))

    def test_retriever_returns_relevant_inventory_sections(self) -> None:
        docs = self.knowledge_base.retriever.invoke("库存风险、可售天数和补货建议")
        self.assertEqual(len(docs), 3)
        self.assertEqual(docs[0].metadata["source"], "inventory_management.md")
        self.assertIn("可售天数", docs[0].page_content)

    def test_local_embeddings_are_deterministic_and_normalized(self) -> None:
        embeddings = LocalHashEmbeddings(64)
        first = embeddings.embed_query("库存风险")
        self.assertEqual(first, embeddings.embed_documents(["库存风险"])[0])
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)


class RagToolAndAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = CsvDataStore()

    def tools(self, searcher: object) -> list:
        return build_tools(self.store, searcher)

    def test_rag_tool_has_query_schema_and_stable_result(self) -> None:
        tools = {tool.name: tool for tool in self.tools(FakeKnowledgeSearcher())}
        self.assertEqual(len(tools), 6)
        result = json.loads(tools["search_operation_knowledge"].invoke({
            "query": "库存风险规则", "k": 1,
        }))
        self.assertEqual(set(result), {"schema_version", "tool", "status", "data", "error"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["matches"][0]["source"],
                         "inventory_management.md")
        definition = describe_tools(list(tools.values()))[-1]["function"]
        self.assertEqual(set(definition["parameters"]["properties"]), {"query", "k"})
        self.assertNotIn("sku", definition["parameters"]["properties"])

    def test_agent_can_call_only_rag_tool(self) -> None:
        model = ScriptedRagModel(
            AIMessage(content="", tool_calls=[tool_call(
                "search_operation_knowledge", {"query": "库存风险规则"}, "rag-1")]),
            AIMessage(content="库存规则来自 inventory_management.md。"),
        )
        result = ProductAgent(model, self.tools(FakeKnowledgeSearcher()),
                              self.store.as_of_date).run("我们的库存风险规则是什么？")
        self.assertEqual([item["name"] for item in result.tool_calls],
                         ["search_operation_knowledge"])
        messages = [item for item in model.inputs[1] if isinstance(item, ToolMessage)]
        self.assertEqual(messages[0].tool_call_id, "rag-1")

    def test_agent_can_call_business_and_rag_tools_together(self) -> None:
        model = ScriptedRagModel(
            AIMessage(content="", tool_calls=[
                tool_call("get_inventory_data", {"sku": "SKU003"}, "inventory-1"),
                tool_call("search_operation_knowledge", {
                    "query": "库存风险分级和处理建议"}, "rag-1"),
            ]),
            AIMessage(content="SKU003库存数据与库存规则已综合。"),
        )
        result = ProductAgent(model, self.tools(FakeKnowledgeSearcher()),
                              self.store.as_of_date).run("分析SKU003库存风险并按规则建议")
        self.assertEqual([item["name"] for item in result.tool_calls],
                         ["get_inventory_data", "search_operation_knowledge"])
        messages = [item for item in model.inputs[1] if isinstance(item, ToolMessage)]
        self.assertEqual([item.tool_call_id for item in messages], ["inventory-1", "rag-1"])

    def test_agent_can_call_business_and_rag_tools_across_rounds(self) -> None:
        model = ScriptedRagModel(
            AIMessage(content="", tool_calls=[tool_call(
                "get_inventory_data", {"sku": "SKU003"}, "inventory-1")]),
            AIMessage(content="", tool_calls=[tool_call(
                "search_operation_knowledge", {"query": "库存补货建议"}, "rag-1")]),
            AIMessage(content="完成综合回答。"),
        )
        result = ProductAgent(model, self.tools(FakeKnowledgeSearcher()),
                              self.store.as_of_date).run("分析SKU003库存风险并按规则建议")
        self.assertEqual(result.model_calls, 3)
        self.assertEqual(len(result.tool_calls), 2)

    def test_rag_failure_returns_error_tool_message_and_agent_can_finish(self) -> None:
        model = ScriptedRagModel(
            AIMessage(content="", tool_calls=[tool_call(
                "search_operation_knowledge", {"query": "库存规则"}, "rag-error")]),
            AIMessage(content="知识检索失败，无法引用内部规则。"),
        )
        result = ProductAgent(model, self.tools(BrokenKnowledgeSearcher()),
                              self.store.as_of_date).run("查询库存规则")
        trace = result.tool_calls[0]
        self.assertEqual(trace["execution_status"], "error")
        self.assertEqual(trace["result"]["error"]["code"], "retrieval_error")
        self.assertNotIn("test retrieval failure", json.dumps(trace))


if __name__ == "__main__":
    unittest.main()
