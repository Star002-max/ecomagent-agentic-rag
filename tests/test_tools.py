"""Offline tests of real StructuredTools; no model, keys or Agent required."""

import json
import unittest
from unittest.mock import patch

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool

from src import services
from src.services import CsvDataStore, DataValidationError
from src.tools import build_tools, describe_tools


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = CsvDataStore()

    def setUp(self) -> None:
        self.tools = {tool.name: tool for tool in build_tools(self.store)}

    def invoke(self, name: str, arguments: dict) -> dict:
        result = self.tools[name].invoke(arguments)
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertEqual(set(parsed), {"schema_version", "tool", "status", "data", "error"})
        self.assertEqual(parsed["tool"], name)
        self.assertEqual(parsed["schema_version"], "1.0")
        json.dumps(parsed, allow_nan=False)
        return parsed

    def test_five_real_tools_and_unique_names(self) -> None:
        expected = {"get_product_info", "get_sales_data", "compare_sales_periods",
                    "get_inventory_data", "get_review_data"}
        self.assertEqual(set(self.tools), expected)
        for tool in self.tools.values():
            self.assertIsInstance(tool, StructuredTool)
            self.assertIn("2026-09-22", tool.description)
            self.assertFalse(tool.return_direct)

    def test_definitions_expose_schema_but_not_store_or_paths(self) -> None:
        definitions = describe_tools(list(self.tools.values()))
        self.assertEqual(len(definitions), 5)
        for item in definitions:
            self.assertEqual(item["type"], "function")
            function = item["function"]
            properties = function["parameters"]["properties"]
            self.assertIn("sku", properties)
            self.assertNotIn("store", properties)
            self.assertNotIn("data_dir", properties)
            self.assertNotIn("/Users/", json.dumps(item))
            self.assertFalse(function["parameters"]["additionalProperties"])
            for field in properties.values():
                self.assertTrue(field["description"])
        sales = self.tools["get_sales_data"].args_schema.model_json_schema()
        self.assertEqual(set(sales["required"]), {"sku", "start_date", "end_date"})

    def test_each_tool_calls_its_service_once_and_preserves_payload(self) -> None:
        examples = {
            "get_product_info": {"sku": "SKU001"},
            "get_sales_data": {"sku": "SKU001", "start_date": "2026-08-24",
                               "end_date": "2026-09-22"},
            "compare_sales_periods": {
                "sku": "SKU002", "current_start": "2026-08-24",
                "current_end": "2026-09-22", "previous_start": "2026-07-25",
                "previous_end": "2026-08-23",
            },
            "get_inventory_data": {"sku": "SKU003"},
            "get_review_data": {"sku": "SKU005", "low_rating_limit": 2},
        }
        for name, arguments in examples.items():
            service = getattr(services, name)
            expected = service(self.store, **arguments)
            with self.subTest(name=name), patch.object(services, name, wraps=service) as spy:
                tool = {item.name: item for item in build_tools(self.store)}[name]
                result = json.loads(tool.invoke(arguments))
                self.assertEqual(spy.call_count, 1)
                self.assertIs(spy.call_args.args[0], self.store)
                self.assertEqual(result["data"], expected)
                self.assertIsNone(result["error"])

    def test_optional_omitted_and_null_dates_match_service(self) -> None:
        for name in ("get_inventory_data", "get_review_data"):
            omitted = self.invoke(name, {"sku": "SKU003"})
            explicit = self.invoke(name, {"sku": "SKU003", "start_date": None,
                                          "end_date": None})
            self.assertEqual(omitted, explicit)
        review = self.invoke("get_review_data", {"sku": "SKU005"})["data"]
        self.assertEqual(len(review["low_rating_reviews"]), 5)

    def test_unknown_sku_is_business_result_not_execution_error(self) -> None:
        result = self.invoke("get_product_info", {"sku": "SKU999"})
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["error"])
        self.assertIsNone(result["data"]["product"])

    def test_no_data_and_null_values_preserved(self) -> None:
        result = self.invoke("get_sales_data", {
            "sku": "SKU001", "start_date": "2020-01-01", "end_date": "2020-01-02",
        })
        self.assertEqual(result["status"], "no_data")
        self.assertTrue(all(value is None for value in result["data"]["metrics"].values()))

    def test_partial_and_insufficient_comparison_preserved(self) -> None:
        result = self.invoke("get_sales_data", {
            "sku": "SKU001", "start_date": "2026-09-22", "end_date": "2026-09-23",
        })
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["data"]["coverage"]["missing_dates"], ["2026-09-23"])
        comparison = self.invoke("compare_sales_periods", {
            "sku": "SKU001", "current_start": "2026-09-22", "current_end": "2026-09-23",
            "previous_start": "2026-09-20", "previous_end": "2026-09-21",
        })
        self.assertEqual(comparison["status"], "insufficient_data")
        self.assertIsNone(comparison["data"]["changes"])

    def test_missing_arguments_rejected_before_service(self) -> None:
        with patch.object(services, "get_sales_data") as spy:
            tool = {t.name: t for t in build_tools(self.store)}["get_sales_data"]
            result = json.loads(tool.invoke({"sku": "SKU001"}))
            spy.assert_not_called()
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertEqual({item["field"] for item in result["error"]["details"]},
                         {"start_date", "end_date"})

    def test_extra_fields_are_rejected_not_silently_ignored(self) -> None:
        result = self.invoke("get_product_info", {"sku": "SKU001", "data_dir": "/tmp"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["details"][0]["field"], "data_dir")

    def test_strict_types_and_limit_bounds(self) -> None:
        for value in (True, "5", 1.5, 0, 101):
            with self.subTest(value=value):
                result = self.invoke("get_review_data", {"sku": "SKU005",
                                                          "low_rating_limit": value})
                self.assertEqual(result["status"], "error")
        self.assertEqual(self.invoke("get_product_info", {"sku": 1})["status"], "error")

    def test_date_shape_schema_error_and_calendar_service_error(self) -> None:
        for value in ("2026-9-1", "2026-02-30"):
            result = self.invoke("get_sales_data", {
                "sku": "SKU001", "start_date": value, "end_date": "2026-09-22",
            })
            self.assertEqual(result["error"]["code"], "invalid_arguments")
            self.assertIsNone(result["data"])

    def test_service_range_errors_are_actionable(self) -> None:
        result = self.invoke("get_sales_data", {
            "sku": "SKU001", "start_date": "2026-09-22", "end_date": "2026-08-24",
        })
        self.assertIn("不能晚于", result["error"]["message"])

    def test_service_sku_normalization_is_reused(self) -> None:
        result = self.invoke("get_product_info", {"sku": " sku001 "})
        self.assertEqual(result["data"]["sku"], "SKU001")

    def test_tool_call_returns_correlated_success_message(self) -> None:
        result = self.tools["get_inventory_data"].invoke({
            "name": "get_inventory_data", "args": {"sku": "SKU003"},
            "id": "manual-test-001", "type": "tool_call",
        })
        self.assertIsInstance(result, ToolMessage)
        self.assertEqual(result.tool_call_id, "manual-test-001")
        self.assertEqual(result.name, "get_inventory_data")
        self.assertEqual(result.status, "success")
        self.assertEqual(json.loads(result.content)["data"]["current_inventory"], 50)

    def test_tool_call_schema_error_returns_error_message(self) -> None:
        result = self.tools["get_sales_data"].invoke({
            "name": "get_sales_data", "args": {"sku": "SKU001"},
            "id": "manual-error-001", "type": "tool_call",
        })
        self.assertEqual(result.status, "error")
        self.assertEqual(result.tool_call_id, "manual-error-001")
        self.assertEqual(json.loads(result.content)["error"]["code"], "invalid_arguments")

    def test_tool_call_service_error_returns_error_message(self) -> None:
        result = self.tools["get_sales_data"].invoke({
            "name": "get_sales_data", "type": "tool_call", "id": "manual-error-002",
            "args": {"sku": "SKU001", "start_date": "2026-09-22", "end_date": "2026-09-01"},
        })
        self.assertEqual(result.status, "error")
        self.assertIn("不能晚于", json.loads(result.content)["error"]["message"])

    def test_data_error_keeps_its_category(self) -> None:
        with patch.object(services, "get_product_info", side_effect=DataValidationError("测试数据错误")):
            tool = {t.name: t for t in build_tools(self.store)}["get_product_info"]
            result = json.loads(tool.invoke({"sku": "SKU001"}))
        self.assertEqual(result["error"]["code"], "data_error")

    def test_unexpected_errors_are_not_disguised_as_success(self) -> None:
        with patch.object(services, "get_product_info", side_effect=RuntimeError("test failure")):
            tool = {t.name: t for t in build_tools(self.store)}["get_product_info"]
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                tool.invoke({"sku": "SKU001"})

    def test_broken_output_not_mislabeled_as_bad_input(self) -> None:
        with patch.object(services, "get_product_info",
                          return_value={"status": "ok", "price": float("nan")}):
            tool = {t.name: t for t in build_tools(self.store)}["get_product_info"]
            with self.assertRaises(ValueError):
                tool.invoke({"sku": "SKU001"})


if __name__ == "__main__":
    unittest.main()
