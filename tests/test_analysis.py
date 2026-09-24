"""Phase 5 offline multi-tool and structured-output tests."""

import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.runner import AgentExecutionError, ProductAgent
from src.models import AnalysisReport, StructuredOutputError, parse_analysis_report
from src.services import CsvDataStore
from src.tools import build_tools


class ScriptedAnalysisModel:
    """Test-only model. It validates loop mechanics, not LLM reasoning quality."""

    def __init__(self, *responses: AIMessage) -> None:
        self.responses = iter(responses)
        self.inputs: list[list] = []

    def bind_tools(self, definitions: list[dict]) -> "ScriptedAnalysisModel":
        self.definitions = definitions
        return self

    def invoke(self, messages: list) -> AIMessage:
        self.inputs.append(list(messages))
        return next(self.responses)


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def report_json(sku: str = "SKU005", **overrides: object) -> str:
    payload = {
        "sku": sku,
        "summary": "销售与评分同期下降，需要关注，但现有数据不能证明因果。",
        "findings": ["最近30天销量下降40.09%。", "评价均分同期从4.68降至2.10。"],
        "risk_level": "high",
        "recommendations": ["检查低分评价涉及的商品体验问题。"],
        "evidence_limits": ["同期变化只表示相关性，不能证明评分下降导致销量下降。"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class StructuredOutputTests(unittest.TestCase):
    def test_valid_plain_and_fenced_json(self) -> None:
        plain = parse_analysis_report(report_json())
        fenced = parse_analysis_report(f"```json\n{report_json()}\n```")
        self.assertEqual(plain, fenced)
        self.assertIsInstance(plain, AnalysisReport)
        self.assertEqual(plain.risk_level, "high")

    def test_extra_field_wrong_risk_and_missing_field_rejected(self) -> None:
        for changes in ({"unexpected": True}, {"risk_level": "critical"},
                        {"findings": []}):
            with self.subTest(changes=changes), self.assertRaises(StructuredOutputError):
                parse_analysis_report(report_json(**changes))
        payload = json.loads(report_json())
        del payload["recommendations"]
        with self.assertRaisesRegex(StructuredOutputError, "recommendations"):
            parse_analysis_report(json.dumps(payload, ensure_ascii=False))

    def test_non_json_and_surrounding_prose_rejected(self) -> None:
        for text in ("不是JSON", f"分析如下：{report_json()}"):
            with self.assertRaises(StructuredOutputError):
                parse_analysis_report(text)

    def test_items_are_trimmed_but_not_rewritten(self) -> None:
        report = parse_analysis_report(report_json(
            findings=["  已确认事实  "], recommendations=["  建议  "],
            evidence_limits=["  限制  "], summary="  摘要  "))
        self.assertEqual(report.summary, "摘要")
        self.assertEqual(report.findings, ["已确认事实"])


class MultiToolAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = CsvDataStore()

    def agent(self, model: ScriptedAnalysisModel, **kwargs: object) -> ProductAgent:
        return ProductAgent(model, build_tools(self.store), self.store.as_of_date, **kwargs)

    def test_one_model_message_can_request_multiple_tools(self) -> None:
        first = AIMessage(content="", tool_calls=[
            tool_call("compare_sales_periods", {
                "sku": "SKU005", "current_start": "2026-08-24",
                "current_end": "2026-09-22", "previous_start": "2026-07-25",
                "previous_end": "2026-08-23",
            }, "compare-1"),
            tool_call("get_review_data", {
                "sku": "SKU005", "start_date": "2026-08-24",
                "end_date": "2026-09-22", "low_rating_limit": 3,
            }, "reviews-1"),
        ])
        model = ScriptedAnalysisModel(first, AIMessage(content=report_json()))
        result = self.agent(model).run_analysis("分析SKU005最近30天的销售和评论变化")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_calls, 2)
        self.assertEqual([item["name"] for item in result.tool_calls],
                         ["compare_sales_periods", "get_review_data"])
        self.assertEqual(result.structured_output["sku"], "SKU005")
        self.assertEqual(json.loads(result.answer), result.structured_output)
        replies = [message for message in model.inputs[1] if isinstance(message, ToolMessage)]
        self.assertEqual([message.tool_call_id for message in replies],
                         ["compare-1", "reviews-1"])
        comparison = json.loads(replies[0].content)["data"]
        reviews = json.loads(replies[1].content)["data"]
        self.assertLess(comparison["changes"]["units"]["relative_change"], -0.35)
        self.assertLess(reviews["rating_change"], -1.5)

    def test_tools_can_be_selected_across_multiple_model_rounds(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("compare_sales_periods", {
                "sku": "SKU005", "current_start": "2026-08-24",
                "current_end": "2026-09-22", "previous_start": "2026-07-25",
                "previous_end": "2026-08-23",
            }, "compare-1")]),
            AIMessage(content="", tool_calls=[tool_call("get_review_data", {
                "sku": "SKU005", "start_date": "2026-08-24", "end_date": "2026-09-22",
            }, "reviews-1")]),
            AIMessage(content=report_json()),
        )
        result = self.agent(model).run_analysis("分析SKU005销售和评论")
        self.assertEqual(result.model_calls, 3)
        self.assertEqual(len(result.tool_calls), 2)

    def test_sku002_evidence_is_stable_sessions_and_lower_conversion(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("compare_sales_periods", {
                "sku": "SKU002", "current_start": "2026-08-24",
                "current_end": "2026-09-22", "previous_start": "2026-07-25",
                "previous_end": "2026-08-23",
            }, "compare-2")]),
            AIMessage(content=report_json(
                sku="SKU002",
                summary="访问量同期基本稳定，转化率和销量下降。",
                findings=["访问量同期基本稳定。", "转化率和销量同期下降。"],
                recommendations=["继续调查转化率下降所需的补充数据。"],
                evidence_limits=["现有数据不能证明转化率下降的原因。"],
            )),
        )
        result = self.agent(model).run_analysis("SKU002最近表现变差了吗？")
        data = result.tool_calls[0]["result"]["data"]["changes"]
        self.assertLess(abs(data["sessions"]["relative_change"]), 0.02)
        self.assertLess(data["conversion_rate"]["relative_change"], -0.25)

    def test_no_data_can_produce_unknown_risk_report(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("get_product_info", {"sku": "SKU999"},
                                                         "product-1")]),
            AIMessage(content=report_json(
                sku="SKU999", summary="当前数据源没有该商品，无法完成分析。",
                findings=["当前数据源未找到SKU999。"], risk_level="unknown",
                recommendations=["核对SKU编号后重新分析。"],
                evidence_limits=["没有商品或业务数据，无法判断表现和风险。"])),
        )
        result = self.agent(model).run_analysis("分析SKU999最近表现")
        self.assertEqual(result.structured_output["risk_level"], "unknown")
        self.assertEqual(result.tool_calls[0]["result"]["status"], "not_found")

    def test_tool_argument_failure_can_be_corrected_before_report(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("compare_sales_periods", {
                "sku": "SKU001"
            }, "bad-1")]),
            AIMessage(content="", tool_calls=[tool_call("compare_sales_periods", {
                "sku": "SKU001", "current_start": "2026-08-24",
                "current_end": "2026-09-22", "previous_start": "2026-07-25",
                "previous_end": "2026-08-23",
            }, "fixed-1")]),
            AIMessage(content=report_json(
                sku="SKU001", summary="访问和销量同期下降，转化率相对稳定。",
                findings=["最近30天访问和销量均下降。"], risk_level="medium",
                recommendations=["继续核查访问量下降的渠道来源。"],
                evidence_limits=["现有数据不能证明访问量下降的外部原因。"])),
        )
        result = self.agent(model).run_analysis("分析SKU001")
        self.assertEqual(result.tool_calls[0]["execution_status"], "error")
        self.assertEqual(result.tool_calls[1]["result"]["status"], "ok")
        self.assertEqual(result.status, "completed")

    def test_only_failed_tool_does_not_count_as_grounded_analysis(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("compare_sales_periods", {
                "sku": "SKU001"
            }, "bad-1")]), AIMessage(content=report_json(sku="SKU001")))
        with self.assertRaisesRegex(AgentExecutionError, "未成功执行"):
            self.agent(model).run_analysis("分析SKU001")

    def test_invalid_structure_gets_one_format_only_retry(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("get_product_info", {"sku": "SKU001"},
                                                         "product-1")]),
            AIMessage(content='{"sku":"SKU001","summary":"缺少其他字段"}'),
            AIMessage(content=report_json(sku="SKU001")),
        )
        result = self.agent(model).run_analysis("分析SKU001")
        self.assertEqual(result.model_calls, 3)
        repair = model.inputs[2][-1]
        self.assertIsInstance(repair, HumanMessage)
        self.assertIn("仅修正JSON格式", repair.content)

    def test_second_invalid_structure_is_rejected(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("get_product_info", {"sku": "SKU001"},
                                                         "product-1")]),
            AIMessage(content='{"sku":"SKU001","summary":"缺少其他字段"}'),
            AIMessage(content="仍然不是JSON"),
        )
        with self.assertRaisesRegex(AgentExecutionError, "AnalysisReport"):
            self.agent(model).run_analysis("分析SKU001")

    def test_structure_retry_cannot_call_more_tools(self) -> None:
        model = ScriptedAnalysisModel(
            AIMessage(content="", tool_calls=[tool_call("get_product_info", {"sku": "SKU001"},
                                                         "product-1")]),
            AIMessage(content="不是JSON"),
            AIMessage(content="", tool_calls=[tool_call(
                "get_product_info", {"sku": "SKU001"}, "product-2")]),
        )
        with self.assertRaisesRegex(AgentExecutionError, "结构修正阶段"):
            self.agent(model).run_analysis("分析SKU001")

    def test_model_cannot_skip_tools_and_submit_structured_report(self) -> None:
        model = ScriptedAnalysisModel(AIMessage(content=report_json(sku="SKU001")))
        with self.assertRaisesRegex(AgentExecutionError, "未成功执行"):
            self.agent(model).run_analysis("分析SKU001")

    def test_analysis_preserves_existing_loop_limits(self) -> None:
        model = ScriptedAnalysisModel(AIMessage(content="", tool_calls=[
            tool_call("get_product_info", {"sku": "SKU001"}, "one"),
            tool_call("get_sales_data", {"sku": "SKU001", "start_date": "2026-08-24",
                                          "end_date": "2026-09-22"}, "two"),
        ]))
        result = self.agent(model, max_tool_calls=1).run_analysis("分析SKU001")
        self.assertEqual(result.status, "limit_reached")
        self.assertEqual(result.tool_calls, [])


if __name__ == "__main__":
    unittest.main()
