"""Offline tests for session-scoped ConversationMemory and interactive reuse."""

import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import scripts.run_agent as run_agent_cli
import scripts.run_analysis as run_analysis_cli
from src.agent.memory import ConversationMemory
from src.agent.model import ModelRequestError
from src.agent.runner import AgentExecutionError, ProductAgent
from src.config import Settings
from src.services import CsvDataStore
from src.tools import build_tools


def call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class ScriptedModel:
    def __init__(self, *responses: object) -> None:
        self.responses = iter(responses)
        self.inputs: list[list] = []

    def bind_tools(self, definitions: list[dict]) -> "ScriptedModel":
        self.definitions = definitions
        return self

    def invoke(self, messages: list) -> AIMessage:
        self.inputs.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ConversationMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = CsvDataStore()
        cls.tools = build_tools(cls.store)

    def agent(self, model: ScriptedModel, memory: ConversationMemory,
              **kwargs: object) -> ProductAgent:
        return ProductAgent(model, self.tools, self.store.as_of_date,
                            memory=memory, **kwargs)

    def test_followup_uses_history_but_requeries_current_business_fact(self) -> None:
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[call(
                "get_inventory_data", {"sku": "SKU003"}, "inventory-1")]),
            AIMessage(content="SKU003库存为50件。"),
            AIMessage(content="", tool_calls=[call(
                "get_inventory_data", {"sku": "SKU003"}, "inventory-2")]),
            AIMessage(content="它按最近30天销量估算约可售0.65天。"),
        )
        memory = ConversationMemory()
        agent = self.agent(model, memory)
        agent.run("SKU003现在有多少库存？")
        result = agent.run("它按最近销量还能卖多久？")

        second_turn_messages = model.inputs[2]
        self.assertEqual([message.content for message in second_turn_messages
                          if isinstance(message, HumanMessage)],
                         ["SKU003现在有多少库存？", "它按最近销量还能卖多久？"])
        self.assertIn("SKU003库存为50件。", [message.content for message in second_turn_messages
                                            if isinstance(message, AIMessage)])
        current_tool_messages = [message for message in model.inputs[3]
                                 if isinstance(message, ToolMessage)]
        self.assertEqual([message.tool_call_id for message in current_tool_messages],
                         ["inventory-2"])
        self.assertEqual(result.status, "completed")
        history = memory.to_messages()
        self.assertTrue(all(isinstance(message, (HumanMessage, AIMessage))
                            for message in history))
        self.assertFalse(any(isinstance(message, ToolMessage) for message in history))
        self.assertEqual(len(memory.turns), 2)

    def test_separate_memory_instances_isolate_sessions(self) -> None:
        first_model = ScriptedModel(AIMessage(content="第一会话回答"))
        second_model = ScriptedModel(AIMessage(content="第二会话回答"),
                                     AIMessage(content="第二会话追问回答"))
        first_memory, second_memory = ConversationMemory(), ConversationMemory()
        self.agent(first_model, first_memory).run("第一会话问题")
        second_agent = self.agent(second_model, second_memory)
        second_agent.run("第二会话问题")
        second_agent.run("第二会话追问")
        second_history = second_model.inputs[1]
        self.assertIn("第二会话问题", [message.content for message in second_history
                                      if isinstance(message, HumanMessage)])
        self.assertNotIn("第一会话问题", [message.content for message in second_history
                                      if isinstance(message, HumanMessage)])
        self.assertEqual(len(first_memory.turns), 1)
        self.assertEqual(len(second_memory.turns), 2)

    def test_only_latest_four_complete_turns_are_retained(self) -> None:
        model = ScriptedModel(*(AIMessage(content=f"回答{index}")
                                for index in range(1, 6)))
        memory = ConversationMemory()
        agent = self.agent(model, memory)
        for index in range(1, 6):
            agent.run(f"问题{index}")
        self.assertEqual([turn.question for turn in memory.turns],
                         ["问题2", "问题3", "问题4", "问题5"])
        self.assertEqual(len(memory.to_messages()), 8)
        with self.assertRaisesRegex(ValueError, "最多保留4轮"):
            ConversationMemory(max_turns=5)

    def test_model_exception_and_incomplete_tool_round_do_not_pollute_memory(self) -> None:
        memory = ConversationMemory()
        failing = self.agent(ScriptedModel(RuntimeError("private stack details")), memory)
        with self.assertRaisesRegex(ModelRequestError, "模型请求失败"):
            failing.run("失败问题")
        self.assertEqual(memory.turns, ())

        limited = self.agent(ScriptedModel(AIMessage(content="", tool_calls=[call(
            "get_inventory_data", {"sku": "SKU003"}, "limit-1")])),
                           memory, max_model_calls=1)
        result = limited.run("尚未完成的问题")
        self.assertEqual(result.status, "limit_reached")
        self.assertEqual(memory.turns, ())

    def test_analysis_history_preserves_structured_output_validation(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("上轮问题", "上轮上下文")
        report = {
            "sku": "SKU001", "summary": "库存查询已完成。",
            "findings": ["已调用商品查询工具。"], "risk_level": "unknown",
            "recommendations": ["继续按实际问题查询。"],
            "evidence_limits": ["本例未提供其他业务证据。"],
        }
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[call(
                "get_product_info", {"sku": "SKU001"}, "analysis-product")]),
            AIMessage(content=json.dumps(report, ensure_ascii=False)),
        )
        result = self.agent(model, memory).run_analysis("继续分析这个商品")
        self.assertEqual(result.structured_output["sku"], "SKU001")
        initial_messages = model.inputs[0]
        self.assertIsInstance(initial_messages[0], SystemMessage)
        self.assertEqual([message.content for message in initial_messages
                          if isinstance(message, HumanMessage)],
                         ["上轮问题", "继续分析这个商品"])
        self.assertEqual([turn.question for turn in memory.turns],
                         ["上轮问题", "继续分析这个商品"])
        self.assertFalse(any(isinstance(message, ToolMessage)
                             for message in memory.to_messages()))

    def test_invalid_structured_output_does_not_add_failed_turn(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("保留问题", "保留回答")
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[call(
                "get_product_info", {"sku": "SKU001"}, "analysis-product")]),
            AIMessage(content="不是JSON"),
            AIMessage(content="仍然不是JSON"),
        )
        with self.assertRaisesRegex(AgentExecutionError, "AnalysisReport"):
            self.agent(model, memory).run_analysis("失败的结构化分析")
        self.assertEqual([turn.question for turn in memory.turns], ["保留问题"])

    def test_interactive_entrypoint_reuses_one_memory_and_agent(self) -> None:
        model = ScriptedModel(AIMessage(content="第一轮回答"),
                              AIMessage(content="第二轮回答"))
        store = CsvDataStore()
        answers = iter(("第一个问题", "这个问题的追问", "/quit"))
        output = StringIO()
        with patch.object(sys, "argv", ["run_agent", "--interactive"]), \
                patch("scripts.run_agent.load_settings",
                      return_value=Settings("fixture-chat-key", "https://example.invalid/v1",
                                            "fixture-model")), \
                patch("scripts.run_agent.CsvDataStore", return_value=store), \
                patch("scripts.run_agent.create_model", return_value=model), \
                patch("scripts.run_agent.build_knowledge_base"), \
                patch("scripts.run_agent.build_tools", return_value=self.tools), \
                patch("builtins.input", side_effect=lambda _prompt: next(answers)), \
                redirect_stdout(output):
            run_agent_cli.main()
        second_input = model.inputs[1]
        self.assertEqual([message.content for message in second_input
                          if isinstance(message, HumanMessage)],
                         ["第一个问题", "这个问题的追问"])
        self.assertIn("第一轮回答", [message.content for message in second_input
                                     if isinstance(message, AIMessage)])
        self.assertIn("连续对话已开始", output.getvalue())

    def test_interactive_analysis_entrypoint_reuses_structured_history(self) -> None:
        report = {
            "sku": "SKU001", "summary": "商品查询完成。",
            "findings": ["已查询商品信息。"], "risk_level": "unknown",
            "recommendations": ["按后续问题继续查询。"],
            "evidence_limits": ["当前仅有商品信息。"],
        }
        model = ScriptedModel(
            AIMessage(content="", tool_calls=[call(
                "get_product_info", {"sku": "SKU001"}, "analysis-1")]),
            AIMessage(content=json.dumps(report, ensure_ascii=False)),
            AIMessage(content="", tool_calls=[call(
                "get_product_info", {"sku": "SKU001"}, "analysis-2")]),
            AIMessage(content=json.dumps(report, ensure_ascii=False)),
        )
        store = CsvDataStore()
        answers = iter(("分析SKU001商品", "补充说明它是什么商品", "/quit"))
        with patch.object(sys, "argv", ["run_analysis", "--interactive"]), \
                patch("scripts.run_analysis.load_settings",
                      return_value=Settings("fixture-chat-key", "https://example.invalid/v1",
                                            "fixture-model")), \
                patch("scripts.run_analysis.CsvDataStore", return_value=store), \
                patch("scripts.run_analysis.create_model", return_value=model), \
                patch("scripts.run_analysis.build_knowledge_base"), \
                patch("scripts.run_analysis.build_tools", return_value=self.tools), \
                patch("builtins.input", side_effect=lambda _prompt: next(answers)), \
                redirect_stdout(StringIO()):
            run_analysis_cli.main()
        second_turn = model.inputs[2]
        self.assertEqual([message.content for message in second_turn
                          if isinstance(message, HumanMessage)],
                         ["分析SKU001商品", "补充说明它是什么商品"])
        previous_assistant = [message.content for message in second_turn
                              if isinstance(message, AIMessage)]
        self.assertEqual(len(previous_assistant), 1)
        self.assertEqual(json.loads(previous_assistant[0]), report)


if __name__ == "__main__":
    unittest.main()
