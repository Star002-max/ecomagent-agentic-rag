"""Phase 6 offline tests for loading, Chroma retrieval, Tool, and Agent integration."""

import json
import builtins
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.embeddings import Embeddings

from src.agent.runner import ProductAgent
from src.config import EmbeddingSettings, load_embedding_settings
from src.rag.knowledge_base import (LocalHashEmbeddings, build_knowledge_base,
                                    create_embeddings, load_markdown_documents,
                                    split_markdown_documents)
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


class Fake1024Embeddings(Embeddings):
    """Deterministic local stand-in for the cloud vector dimension."""

    dimensions = 1024
    provider = "aliyun"
    model = "text-embedding-v4"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1024


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class RagPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge_base = build_knowledge_base(
            settings=EmbeddingSettings(provider="local_hash"))

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

    def test_default_provider_is_local_without_cloud_credentials(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = load_embedding_settings(Path("missing-embedding.env"))
        self.assertEqual(settings.provider, "local_hash")
        self.assertIsInstance(create_embeddings(settings), LocalHashEmbeddings)

    def test_aliyun_requires_independent_key_and_base_url(self) -> None:
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "aliyun"}, clear=True):
            with self.assertRaisesRegex(ValueError, "EMBEDDING_API_KEY"):
                load_embedding_settings(Path("missing-embedding.env"))
        with patch.dict("os.environ", {
            "EMBEDDING_PROVIDER": "aliyun", "EMBEDDING_API_KEY": "fake-key",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "EMBEDDING_BASE_URL"):
                load_embedding_settings(Path("missing-embedding.env"))

    def test_aliyun_base_url_must_be_beijing_openai_compatible_endpoint(self) -> None:
        for url in ("https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
                    "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"):
            with patch.dict("os.environ", {
                "EMBEDDING_PROVIDER": "aliyun", "EMBEDDING_API_KEY": "fake-key",
                "EMBEDDING_BASE_URL": url,
            }, clear=True):
                with self.assertRaisesRegex(ValueError, "北京地域"):
                    load_embedding_settings(Path("missing-embedding.env"))

    def test_aliyun_embeddings_are_configured_without_network_call(self) -> None:
        settings = EmbeddingSettings(
            provider="aliyun", api_key="fake-key",
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
        with patch("src.rag.knowledge_base.OpenAIEmbeddings") as constructor:
            create_embeddings(settings)
        self.assertEqual(constructor.call_count, 1)
        params = constructor.call_args.kwargs
        self.assertEqual(params["model"], "text-embedding-v4")
        self.assertEqual(params["dimensions"], 1024)
        self.assertEqual(params["base_url"], settings.base_url)
        self.assertEqual(params["api_key"], "fake-key")
        self.assertEqual(params["timeout"], 20)
        self.assertEqual(params["max_retries"], 0)
        self.assertEqual(params["chunk_size"], 10)
        self.assertFalse(params["tiktoken_enabled"])
        self.assertFalse(params["check_embedding_ctx_length"])

    def test_aliyun_index_and_query_use_raw_text_without_transformers(self) -> None:
        settings = EmbeddingSettings(
            provider="aliyun", api_key="fake-key",
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
        embeddings = create_embeddings(settings)
        requests = []

        def fake_create(*, input, **kwargs):
            requests.append(input)
            items = input if isinstance(input, list) else [input]
            return {"data": [{"embedding": [0.0] * 1024} for _ in items]}

        original_import = builtins.__import__

        def reject_transformers(name, *args, **kwargs):
            if name == "transformers" or name.startswith("transformers."):
                raise AssertionError("transformers import was attempted")
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "guide.md").write_text(
                "# 库存指南\n## 风险规则\n可售天数低于七天需要核对补货。",
                encoding="utf-8",
            )
            with patch.object(embeddings._inner.client, "create",
                              side_effect=fake_create), \
                    patch("builtins.__import__", side_effect=reject_transformers):
                knowledge_base = build_knowledge_base(
                    directory=Path(directory), embeddings=embeddings,
                    settings=settings,
                )
                results = knowledge_base.search("库存补货风险", k=1)
                self.assertEqual(len(results["matches"]), 1)
                before_oversize = len(requests)
                with self.assertRaisesRegex(ValueError, "UTF-8字节限制"):
                    embeddings.embed_query("x" * 4097)

        self.assertEqual(len(requests), 2)
        self.assertTrue(all(isinstance(request, list) for request in requests))
        self.assertTrue(all(isinstance(item, str)
                            for request in requests for item in request))
        self.assertEqual(len(requests), before_oversize)

    def test_embedding_dimensions_and_provider_use_separate_collections(self) -> None:
        local = build_knowledge_base(
            embeddings=LocalHashEmbeddings(),
            settings=EmbeddingSettings(provider="local_hash"),
        )
        aliyun = build_knowledge_base(
            embeddings=Fake1024Embeddings(),
            settings=EmbeddingSettings(provider="aliyun", api_key="fake",
                                       base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"),
        )
        self.assertEqual(local.embedding_dimensions, 384)
        self.assertEqual(aliyun.embedding_dimensions, 1024)
        self.assertNotEqual(local.vector_store._collection.name,
                            aliyun.vector_store._collection.name)

    def test_injected_embedding_provider_or_dimension_mismatch_is_rejected(self) -> None:
        aliyun_settings = EmbeddingSettings(provider="aliyun", api_key="fake",
                                            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
        with self.assertRaisesRegex(ValueError, "必须与aliyun provider"):
            build_knowledge_base(embeddings=LocalHashEmbeddings(),
                                 settings=aliyun_settings)
        with self.assertRaisesRegex(ValueError, "local_hash配置必须使用"):
            build_knowledge_base(embeddings=Fake1024Embeddings(),
                                 settings=EmbeddingSettings(provider="local_hash"))
        with self.assertRaisesRegex(ValueError, "必须同时提供"):
            build_knowledge_base(embeddings=Fake1024Embeddings())
        with self.assertRaisesRegex(ValueError, "北京地域"):
            build_knowledge_base(
                embeddings=Fake1024Embeddings(),
                settings=EmbeddingSettings(provider="aliyun", api_key="fake",
                                           base_url="https://example.invalid/v1"),
            )

    def test_embedding_api_errors_redact_embedding_key(self) -> None:
        secret = "embedding-secret-value"

        class FailingEmbeddings(Fake1024Embeddings):
            def embed_query(self, text: str) -> list[float]:
                raise RuntimeError(f"authorization failed: {secret}")

        settings = EmbeddingSettings(provider="aliyun", api_key=secret,
                                     base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
        with patch("src.rag.knowledge_base.OpenAIEmbeddings",
                   return_value=FailingEmbeddings()):
            protected = create_embeddings(settings)
        with self.assertRaises(RuntimeError) as caught:
            protected.embed_query("库存风险")
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))


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
