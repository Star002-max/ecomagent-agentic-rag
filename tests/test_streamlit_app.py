"""Offline tests for the real-Agent Streamlit runtime assembly."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

import streamlit_app
from src.agent.memory import ConversationMemory
from src.agent.runner import ProductAgent
from src.config import EmbeddingSettings, Settings, load_embedding_settings
from src.services import CsvDataStore
from src.tools import build_tools


def call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class ScriptedModel:
    """Test-only fake for exercising the existing ProductAgent loop offline."""

    def __init__(self) -> None:
        self.responses = iter((
            AIMessage(content="", tool_calls=[
                call("get_inventory_data", {"sku": "SKU003"}, "ui-inventory"),
                call("search_operation_knowledge", {
                    "query": "库存风险规则", "k": 1,
                }, "ui-rag"),
            ]),
            AIMessage(content="离线测试回答。"),
            AIMessage(content="", tool_calls=[
                call("get_inventory_data", {"sku": "SKU003"}, "ui-inventory-second"),
            ]),
            AIMessage(content="第二轮离线测试回答。"),
        ))

    def bind_tools(self, definitions: list[dict]) -> "ScriptedModel":
        self.definitions = definitions
        return self

    def invoke(self, messages: list) -> AIMessage:
        return next(self.responses)


class FakeKnowledgeBase:
    def search(self, query: str, *, k: int = 3) -> dict:
        return {"query": query, "matches": [{
            "content": "库存证据片段。", "source": "inventory_management.md",
            "title": "库存管理规则", "section": "风险分级", "chunk_id": 0,
        }][:k]}


class StreamlitRuntimeTests(unittest.TestCase):
    def test_page_renders_dashboard_and_requires_explicit_aliyun_confirmation(self) -> None:
        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
            default_timeout=30,
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual([tab.label for tab in app.get("tab")], ["AI Chat", "Dashboard"])
        self.assertIn("期末库存", [metric.label for metric in app.metric])

        app.radio[0].set_value("aliyun").run()
        self.assertFalse(app.exception)
        button = next(item for item in app.button if item.label == "确认并初始化 Aliyun")
        self.assertTrue(button.disabled)

    def test_provider_override_uses_env_credentials_without_mutating_env(self) -> None:
        values = {
            "EMBEDDING_PROVIDER": "local_hash",
            "EMBEDDING_API_KEY": "test-embedding-key",
            "EMBEDDING_BASE_URL": "https://test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        }
        before = os.environ.get("EMBEDDING_PROVIDER")
        with patch.dict(os.environ, values), patch(
                "src.config.dotenv_values", return_value={}):
            settings = load_embedding_settings(provider_override="aliyun")
        self.assertEqual(settings.provider, "aliyun")
        self.assertEqual(settings.dimensions, 1024)
        self.assertEqual(os.environ.get("EMBEDDING_PROVIDER"), before)

    def test_runtime_runs_real_product_agent_loop_and_captures_rag_evidence(self) -> None:
        model = ScriptedModel()
        knowledge_base = FakeKnowledgeBase()
        store = CsvDataStore()
        with patch.object(streamlit_app, "load_settings", return_value=Settings(
                "test-chat-key", "https://example.invalid/v1", "test-qwen-model")), \
                patch.object(streamlit_app, "load_embedding_settings",
                             return_value=EmbeddingSettings(provider="local_hash")), \
                patch.object(streamlit_app, "create_model", return_value=model), \
                patch.object(streamlit_app, "build_knowledge_base",
                             return_value=knowledge_base):
            runtime = streamlit_app.build_runtime("local_hash", store)
            result = runtime.agent.run("SKU003库存风险规则是什么？")

        self.assertEqual(result.answer, "离线测试回答。")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_calls, 2)
        self.assertEqual([item["name"] for item in result.tool_calls], [
            "get_inventory_data", "search_operation_knowledge",
        ])
        evidence = result.tool_calls[1]["result"]["data"]["matches"][0]
        self.assertEqual(evidence["source"], "inventory_management.md")
        self.assertEqual(evidence["section"], "风险分级")
        self.assertEqual(evidence["content"], "库存证据片段。")
        self.assertEqual(len(runtime.memory.turns), 1)

        runtime.clear_memory()
        self.assertEqual(runtime.memory.turns, ())

    def test_chat_input_stays_available_across_turns_and_reuses_memory(self) -> None:
        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
            default_timeout=30,
        ).run()
        self.assertFalse(app.exception)

        store = CsvDataStore()
        knowledge_base = FakeKnowledgeBase()
        model = ScriptedModel()
        memory = ConversationMemory()
        tools = build_tools(store, knowledge_base)
        agent = ProductAgent(model, tools, store.as_of_date, memory=memory)
        runtime = streamlit_app.AgentRuntime(
            Settings("test-chat-key", "https://example.invalid/v1", "test-qwen-model"),
            EmbeddingSettings(provider="local_hash"), model, store,
            knowledge_base, tools, memory, agent,
        )
        app.session_state["agent_runtimes"] = {"local_hash": runtime}
        app.session_state["embedding_provider"] = "local_hash"
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_input), 1)
        app.chat_input[0].set_value("SKU003 库存风险是什么？").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_input), 1)
        self.assertEqual(len(runtime.memory.turns), 1)
        self.assertEqual(runtime.memory.turns[0].question, "SKU003 库存风险是什么？")

        app.chat_input[0].set_value("那第二轮再查一次库存。").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_input), 1)
        self.assertEqual(len(runtime.memory.turns), 2)
        self.assertIs(runtime.memory, memory)
        self.assertEqual(runtime.memory.turns[1].question, "那第二轮再查一次库存。")
        self.assertEqual(runtime.memory.turns[0].answer, "离线测试回答。")
        self.assertEqual(runtime.memory.turns[1].answer, "第二轮离线测试回答。")
        self.assertEqual(
            [item["content"] for item in app.session_state["chat_history_local_hash"]],
            ["SKU003 库存风险是什么？", "离线测试回答。",
             "那第二轮再查一次库存。", "第二轮离线测试回答。"],
        )

    def test_local_provider_override_never_loads_cloud_key(self) -> None:
        values = {
            "EMBEDDING_PROVIDER": "aliyun",
            "EMBEDDING_API_KEY": "test-embedding-key",
            "EMBEDDING_BASE_URL": "https://test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        }
        with patch.dict(os.environ, values), patch(
                "src.config.dotenv_values", return_value={}):
            settings = load_embedding_settings(provider_override="local_hash")
        self.assertEqual(settings.provider, "local_hash")
        self.assertEqual(settings.api_key, "")


if __name__ == "__main__":
    unittest.main()
