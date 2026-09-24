"""Offline scripted-model protocol tests. These are not real LLM validation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.model import ModelRequestError, create_model, redact
from src.agent.runner import AgentExecutionError, ProductAgent
from src.config import Settings, load_settings
from src.services import CsvDataStore
from src.tools import build_tools


class ScriptedModel:
    """Test-only responses, with every input snapshot recorded for assertions."""

    def __init__(self, *responses: object) -> None:
        self.responses = iter(responses)
        self.inputs = []
        self.definitions = None

    def bind_tools(self, definitions: list[dict]) -> "ScriptedModel":
        self.definitions = definitions
        return self

    def invoke(self, messages: list) -> AIMessage:
        self.inputs.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def call(name: str = "get_inventory_data", args: dict | None = None,
         call_id: str = "call-1") -> dict:
    return {"name": name, "args": {"sku": "SKU003"} if args is None else args,
            "id": call_id, "type": "tool_call"}


class LoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = CsvDataStore()

    def agent(self, model: ScriptedModel, **kwargs: object) -> ProductAgent:
        return ProductAgent(model, build_tools(self.store), self.store.as_of_date, **kwargs)

    def test_two_rounds_execute_real_tool_and_return_message_to_model(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call()]),
                              AIMessage(content="库存50件。"))
        result = self.agent(model).run("查询SKU003库存")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_calls, 2)
        self.assertEqual(result.tool_calls[0]["result"]["data"]["current_inventory"], 50)
        message = model.inputs[1][-1]
        self.assertIsInstance(message, ToolMessage)
        self.assertEqual(message.tool_call_id, "call-1")
        self.assertEqual(len(model.definitions), 5)
        for definition in model.definitions:
            self.assertFalse(definition["function"]["parameters"]["additionalProperties"])

    def test_multiple_requested_tools_each_receive_matching_message(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[
            call(), call("get_product_info", {"sku": "SKU003"}, "call-2")]),
            AIMessage(content="完成查询"))
        result = self.agent(model).run("查询商品与库存")
        self.assertEqual(len(result.tool_calls), 2)
        replies = [item for item in model.inputs[1] if isinstance(item, ToolMessage)]
        self.assertEqual([item.tool_call_id for item in replies], ["call-1", "call-2"])

    def test_unknown_tool_can_be_corrected_by_model(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call("not_registered")]),
                              AIMessage(content="", tool_calls=[call(call_id="call-2")]),
                              AIMessage(content="库存50件"))
        result = self.agent(model).run("查询库存")
        self.assertEqual(result.tool_calls[0]["result"]["error"]["code"], "unknown_tool")
        self.assertEqual(model.inputs[1][-1].status, "error")
        self.assertEqual(result.tool_calls[1]["result"]["status"], "ok")

    def test_invalid_arguments_return_error_and_allow_correction(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call(args={})]),
                              AIMessage(content="", tool_calls=[call(call_id="call-2")]),
                              AIMessage(content="库存50件"))
        result = self.agent(model).run("查询库存")
        self.assertEqual(result.tool_calls[0]["execution_status"], "error")
        self.assertEqual(result.tool_calls[0]["result"]["error"]["code"], "invalid_arguments")
        self.assertEqual(result.model_calls, 3)

    def test_invalid_json_tool_call_stops(self) -> None:
        response = AIMessage(content="", invalid_tool_calls=[
            {"name": "get_product_info", "args": "{", "id": "bad", "error": "invalid json"}
        ])
        with self.assertRaisesRegex(AgentExecutionError, "无法解析"):
            self.agent(ScriptedModel(response)).run("查询商品")

    def test_duplicate_batch_ids_rejected_before_execution(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call(), call()]))
        with self.assertRaisesRegex(AgentExecutionError, "同一批"):
            self.agent(model).run("查询库存")

    def test_reused_id_in_next_round_rejected(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call()]),
                              AIMessage(content="", tool_calls=[call()]))
        with self.assertRaisesRegex(AgentExecutionError, "ID缺失或重复"):
            self.agent(model).run("查询库存")

    def test_missing_id_rejected(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call(call_id="")]))
        with self.assertRaisesRegex(AgentExecutionError, "ID缺失"):
            self.agent(model).run("查询库存")

    def test_model_round_limit_is_not_reported_as_completion(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call()]))
        result = self.agent(model, max_model_calls=1).run("查询库存")
        self.assertEqual(result.status, "limit_reached")
        self.assertEqual(result.model_calls, 1)
        self.assertEqual(len(result.tool_calls), 1)

    def test_tool_limit_rejects_batch_before_execution(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[
            call(), call(call_id="call-2")]))
        result = self.agent(model, max_tool_calls=1).run("查询库存")
        self.assertEqual(result.status, "limit_reached")
        self.assertEqual(result.tool_calls, [])

    def test_runs_do_not_share_conversation_history(self) -> None:
        model = ScriptedModel(AIMessage(content="请提供商品编号。"),
                              AIMessage(content="仍需商品编号。"))
        agent = self.agent(model)
        agent.run("第一个独立问题")
        result = agent.run("第二个独立问题")
        self.assertEqual(len(model.inputs[1]), 2)
        self.assertIsInstance(model.inputs[1][1], HumanMessage)
        self.assertEqual(model.inputs[1][1].content, "第二个独立问题")
        self.assertEqual(result.tool_calls, [])

    def test_empty_response_rejected(self) -> None:
        with self.assertRaisesRegex(AgentExecutionError, "可见答案"):
            self.agent(ScriptedModel(AIMessage(content=""))).run("测试")

    def test_truncated_response_rejected(self) -> None:
        response = AIMessage(content="未完", response_metadata={"finish_reason": "length"})
        with self.assertRaisesRegex(AgentExecutionError, "长度限制"):
            self.agent(ScriptedModel(response)).run("测试")

    def test_api_error_exposes_status_but_never_secret_or_headers(self) -> None:
        secret = "fixture-secret-not-a-real-credential"

        class ProviderFailure(Exception):
            status_code = 401
            body = {"error": {"code": "invalid_api_key", "message": f"invalid {secret}"}}

        model = ScriptedModel(ProviderFailure("raw headers should not be printed"))
        with self.assertRaises(ModelRequestError) as caught:
            self.agent(model, api_key=secret).run("测试")
        self.assertIn("401", str(caught.exception))
        self.assertIn("invalid_api_key", str(caught.exception))
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("raw headers", str(caught.exception))
        self.assertEqual(len(model.inputs), 1)

    def test_timeout_is_not_automatically_retried(self) -> None:
        model = ScriptedModel(TimeoutError("sensitive internal details"))
        with self.assertRaises(ModelRequestError) as caught:
            self.agent(model).run("测试")
        self.assertNotIn("sensitive", str(caught.exception))
        self.assertEqual(len(model.inputs), 1)

    def test_answer_redaction_and_reasoning_exclusion(self) -> None:
        secret = "fixture-secret-not-a-real-credential"
        response = AIMessage(content=f"reply {secret}",
                             additional_kwargs={"reasoning_content": "not for output"})
        result = self.agent(ScriptedModel(response), api_key=secret).run("测试")
        self.assertNotIn(secret, result.answer)
        self.assertNotIn("not for output", result.answer)
        self.assertIn("[REDACTED]", result.answer)

    def test_unexpected_tool_failure_stops_without_raw_exception(self) -> None:
        model = ScriptedModel(AIMessage(content="", tool_calls=[call()]))
        agent = self.agent(model)
        with patch.object(type(agent._tools["get_inventory_data"]), "invoke",
                          side_effect=RuntimeError("private details")):
            with self.assertRaisesRegex(AgentExecutionError, "RuntimeError") as caught:
                agent.run("查询库存")
        self.assertNotIn("private details", str(caught.exception))

    def test_empty_question_and_invalid_limits(self) -> None:
        with self.assertRaises(ValueError):
            self.agent(ScriptedModel()).run(" ")
        with self.assertRaises(ValueError):
            self.agent(ScriptedModel(), max_model_calls=0)

    def test_duplicate_tool_names_rejected(self) -> None:
        tools = build_tools(self.store)
        with self.assertRaisesRegex(ValueError, "不能重复"):
            ProductAgent(ScriptedModel(), [tools[0], tools[0]], self.store.as_of_date)


class ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".env"
        self.path.write_text("LLM_API_KEY=local-fixture-secret\n"
                             "LLM_BASE_URL=https://example.invalid/v1\nLLM_MODEL=test-model\n")

    def test_local_config_secret_not_in_repr(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = load_settings(self.path)
        self.assertEqual(settings.api_key, "local-fixture-secret")
        self.assertNotIn("local-fixture-secret", repr(settings))
        self.assertEqual(settings.model, "test-model")

    def test_environment_takes_precedence(self) -> None:
        with patch.dict("os.environ", {"LLM_MODEL": "environment-model"}, clear=True):
            settings = load_settings(self.path)
        self.assertEqual(settings.model, "environment-model")

    def test_missing_required_configuration(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "LLM_API_KEY"):
                load_settings(self.path.parent / "missing.env")

    def test_insecure_or_credential_url_rejected(self) -> None:
        for url in ("http://example.invalid/v1", "https://user:secret@example.invalid/v1"):
            with patch.dict("os.environ", {"LLM_BASE_URL": url}, clear=True):
                with self.assertRaisesRegex(ValueError, "HTTPS地址") as caught:
                    load_settings(self.path)
            self.assertNotIn(url, str(caught.exception))

    def test_model_factory_uses_only_given_config_no_retries(self) -> None:
        settings = Settings("fixture-secret", "https://example.invalid/v1", "test-model")
        with patch("src.agent.model.ChatOpenAI") as constructor:
            create_model(settings)
        params = constructor.call_args.kwargs
        self.assertEqual(params["model"], "test-model")
        self.assertEqual(params["base_url"], settings.base_url)
        self.assertEqual(params["max_retries"], 0)
        self.assertFalse(params["use_responses_api"])

    def test_redaction_replaces_exact_secret_and_bearer(self) -> None:
        value = redact("secretvalue Authorization: Bearer other-value", "secretvalue")
        self.assertNotIn("secretvalue", value)
        self.assertNotIn("other-value", value)


if __name__ == "__main__":
    unittest.main()
