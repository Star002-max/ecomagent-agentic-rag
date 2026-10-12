"""Phase 7 fixed evaluation dataset and evaluator tests."""

import unittest
from unittest.mock import patch

import scripts.evaluate_agent as evaluator
from scripts.evaluate_agent import (MAX_TOOL_EVIDENCE_CHARS,
                                    SharedResourceInitializationError,
                                    _rag_baseline, aggregate_metrics,
                                    evaluate_case, load_cases, run_live, run_offline)


class EvaluationDatasetTests(unittest.TestCase):
    def test_dataset_has_thirteen_unique_valid_cases(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 13)
        self.assertEqual({case["id"] for case in cases},
                         {f"C{number:02d}" for number in range(1, 14)})
        self.assertTrue(all(set(case["required_tools"]).issubset(case["allowed_tools"])
                            for case in cases))

    def test_live_mode_refuses_any_set_except_the_two_accepted_cases(self) -> None:
        with self.assertRaisesRegex(ValueError, "固定只允许C06与C09"):
            run_live([load_cases()[0]])


class EvaluationMetricTests(unittest.TestCase):
    def test_required_tool_recall_and_precision_use_names_not_duplicate_calls(self) -> None:
        case = {"id": "T", "title": "test", "required_tools": ["needed"],
                "allowed_tools": ["needed", "optional"],
                "applicable_metrics": ["required_tool_recall", "tool_selection_precision"]}
        result = {"status": "completed", "tool_calls": [
            {"name": "needed", "result": {}}, {"name": "needed", "result": {}},
            {"name": "optional", "result": {}}]}
        metrics = evaluate_case(case, result)["metrics"]
        self.assertEqual(metrics["required_tool_recall"]["status"], "passed")
        self.assertEqual(metrics["tool_selection_precision"]["status"], "passed")
        self.assertEqual(metrics["tool_selection_precision"]["actual_call_count"], 3)
        self.assertEqual(metrics["tool_selection_precision"]["redundant_call_count"], 1)

    def test_tool_evidence_checks_tool_payload_not_final_answer(self) -> None:
        case = {"id": "T", "title": "test", "required_tools": [], "allowed_tools": [],
                "applicable_metrics": ["tool_evidence_check"],
                "expected_tool_facts": [{"tool": "inventory", "path": "data.units",
                                         "equals": 50}]}
        result = {"answer": "库存50件", "tool_calls": [
            {"name": "inventory", "result": {"data": {"units": 42}}}]}
        metric = evaluate_case(case, result)["metrics"]["tool_evidence_check"]
        self.assertEqual(metric["status"], "failed")
        self.assertEqual(metric["evidence"][0]["observed"], 42)

    def test_invalid_structured_output_is_a_deterministic_failure(self) -> None:
        case = {"id": "T", "title": "test", "required_tools": [], "allowed_tools": [],
                "applicable_metrics": ["structured_output_validity"]}
        result = {"tool_calls": [], "structured_output": {"sku": "not-a-sku"}}
        metric = evaluate_case(case, result)["metrics"]["structured_output_validity"]
        self.assertEqual(metric["status"], "failed")

    def test_answer_and_evidence_review_are_independent_and_pending(self) -> None:
        case = {"id": "T", "title": "test", "required_tools": [], "allowed_tools": [],
                "applicable_metrics": ["answer_fact_review", "evidence_limit_compliance"],
                "answer_fact_checks": ["事实应与Tool一致"],
                "evidence_limit_checks": ["估算限制应披露"]}
        metrics = evaluate_case(case, {"tool_calls": []})["metrics"]
        self.assertEqual(metrics["answer_fact_review"]["status"], "pending_manual_review")
        self.assertEqual(metrics["answer_fact_review"]["details"], ["事实应与Tool一致"])
        self.assertEqual(metrics["evidence_limit_compliance"]["status"],
                         "pending_manual_review")
        self.assertEqual(metrics["evidence_limit_compliance"]["details"], ["估算限制应披露"])
        totals = aggregate_metrics([{"metrics": metrics}])
        self.assertEqual(totals["answer_fact_review"]["denominator"], 0)
        self.assertEqual(totals["evidence_limit_compliance"]["denominator"], 0)

    def test_empty_review_categories_are_explicitly_not_applicable(self) -> None:
        case = {"id": "T", "title": "test", "required_tools": [], "allowed_tools": [],
                "applicable_metrics": ["answer_fact_review", "evidence_limit_compliance"],
                "answer_fact_checks": [], "evidence_limit_checks": []}
        metrics = evaluate_case(case, {"tool_calls": []})["metrics"]
        self.assertEqual(metrics["answer_fact_review"]["status"], "N/A")
        self.assertEqual(metrics["evidence_limit_compliance"]["status"], "N/A")

    def test_saved_tool_evidence_preserves_actual_business_payload(self) -> None:
        payload = evaluator.run_offline(load_cases())
        result = {case["id"]: case for case in payload["cases"]}
        c01_call = result["C01"]["tool_calls"][0]
        self.assertEqual(c01_call["name"], "get_product_info")
        self.assertEqual(c01_call["arguments"], {"sku": "SKU001"})
        self.assertEqual(c01_call["result_status"], "ok")
        self.assertFalse(c01_call["evidence"]["truncated"])
        self.assertEqual(c01_call["evidence"]["data"]["product"]["rating"], 4.5833)
        c07_call = result["C07"]["tool_calls"][0]
        self.assertEqual(c07_call["evidence"]["data"]["matches"][0]["source"],
                         "inventory_management.md")
        self.assertIn("可售天数小于 7 天", c07_call["evidence"]["data"]["matches"][0]["content"])

    def test_tool_evidence_size_is_bounded_and_truncation_is_explicit(self) -> None:
        case = {"id": "T", "title": "test", "required_tools": [], "allowed_tools": [],
                "applicable_metrics": []}
        result = {"tool_calls": [{"name": "large", "arguments": {},
                                  "result": {"status": "ok", "data": {"text": "x" * 8000}}}]}
        call = evaluate_case(case, result)["tool_calls"][0]
        self.assertTrue(call["evidence"]["truncated"])
        self.assertGreater(call["evidence"]["serialized_chars"], MAX_TOOL_EVIDENCE_CHARS)
        self.assertIsNone(call["evidence"]["data"])


class OfflineEvaluationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()
        cls.result = run_offline(cls.cases)

    def test_every_case_runs_independently_and_failure_is_captured(self) -> None:
        self.assertEqual(len(self.result["cases"]), 13)
        by_id = {case["id"]: case for case in self.result["cases"]}
        self.assertTrue(all(case["status"] == "completed" for case in by_id.values()))
        c13 = by_id["C13"]
        self.assertEqual(c13["tool_calls"][0]["result_status"], "error")
        self.assertEqual(c13["tool_calls"][0]["error_code"], "retrieval_error")
        self.assertEqual(c13["metrics"]["failure_handling"]["automated_status"], "passed")

    def test_real_local_rag_returns_top_three_for_baseline_cases(self) -> None:
        baseline = {item["case_id"]: item for item in self.result["rag_top3_baseline"]}
        self.assertEqual(set(baseline), {"C07", "C08", "C09"})
        self.assertTrue(all(len(item["results"]) == 3 for item in baseline.values()))
        self.assertTrue(all(item["results"][0]["source"] for item in baseline.values()))

    def test_expected_tool_facts_are_recorded_with_observed_values(self) -> None:
        by_id = {case["id"]: case for case in self.result["cases"]}
        evidence = by_id["C02"]["metrics"]["tool_evidence_check"]["evidence"]
        self.assertEqual([item["observed"] for item in evidence], [50, 0.6487889273356402])

    def test_scripted_answers_follow_actual_evidence_and_state_limits(self) -> None:
        by_id = {case["id"]: case for case in self.result["cases"]}
        for case_id in ("C03", "C04", "C06"):
            self.assertEqual(by_id[case_id]["structured_output"]["risk_level"], "unknown")

        c02 = by_id["C02"]["answer"]
        self.assertIn("历史日均销量静态估算", c02)
        self.assertIn("不考虑在途补货", c02)
        self.assertIn("不是需求预测", c02)

        c07 = by_id["C07"]["answer"]
        self.assertIn("小于7天为高风险", c07)
        self.assertIn("7至14天为中风险", c07)
        self.assertIn("大于14天为低风险", c07)

        c08 = by_id["C08"]
        c08_answer = c08["answer"]
        c08_matches = c08["tool_calls"][0]["evidence"]["data"]["matches"]
        c08_evidence_text = " ".join(item["content"] for item in c08_matches)
        self.assertNotIn("核对在途补货", c08_evidence_text)
        self.assertNotIn("处理建议", c08_evidence_text)
        self.assertIn("没有提供", c08_answer)
        self.assertIn("无法判断", c08_answer)

        c09 = by_id["C09"]["answer"]
        for required_detail in ("50件", "0.65天", "小于7天属高风险", "核对在途补货",
                                "静态估算", "不考虑在途补货或需求变化"):
            self.assertIn(required_detail, c09)

    def test_case_setup_failure_is_recorded_and_later_case_still_runs(self) -> None:
        original = evaluator._fake_responses

        def fail_first_case(case_id: str):
            if case_id == "C01":
                raise RuntimeError("injected fake fixture failure")
            return original(case_id)

        with patch("scripts.evaluate_agent._fake_responses", side_effect=fail_first_case):
            payload = run_offline(self.cases)
        by_id = {case["id"]: case for case in payload["cases"]}
        self.assertEqual(by_id["C01"]["status"], "error")
        self.assertIn("injected fake fixture failure", by_id["C01"]["error"])
        self.assertEqual(by_id["C02"]["status"], "completed")
        self.assertEqual(len(by_id), 13)

    def test_shared_resource_initialization_failure_is_not_a_case_error(self) -> None:
        with patch("scripts.evaluate_agent.CsvDataStore", side_effect=RuntimeError("shared")):
            with self.assertRaises(SharedResourceInitializationError):
                run_offline(self.cases)

    def test_rag_baseline_failure_is_recorded_and_next_query_runs(self) -> None:
        class OneQueryFails:
            def search(self, query: str, *, k: int = 3) -> dict:
                if query == "可售天数库存风险分级":
                    raise RuntimeError("injected retrieval failure")
                return {"matches": [{"source": "inventory_management.md",
                                     "title": "库存管理规则", "section": "风险分级",
                                     "chunk_id": 0, "content": "可售天数规则"}]}

        cases = [case for case in self.cases if case["id"] in {"C07", "C08"}]
        baseline = _rag_baseline(cases, OneQueryFails())
        self.assertEqual([item["status"] for item in baseline], ["error", "completed"])
        self.assertIsNone(baseline[0]["source_hit"])
        self.assertTrue(baseline[1]["source_hit"])


if __name__ == "__main__":
    unittest.main()
