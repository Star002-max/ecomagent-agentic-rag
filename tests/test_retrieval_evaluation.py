"""Offline tests for the fixed Phase 7 retrieval comparison evaluator."""

import unittest
from unittest.mock import patch

from scripts.evaluate_retrieval import (evaluate_provider, load_rag_cases,
                                        run_evaluation)
from src.config import EmbeddingSettings


class ScriptedKnowledgeBase:
    def __init__(self, results: dict[str, list[dict]]) -> None:
        self.results = results
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, *, k: int = 3) -> dict:
        self.queries.append((query, k))
        return {"matches": self.results[query][:k]}


def match(source: str, section: str, chunk_id: int) -> dict:
    return {"source": source, "section": section, "title": "rule",
            "chunk_id": chunk_id, "content": f"evidence {section}"}


class RetrievalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_rag_cases()

    def test_fixed_phase7_queries_and_expected_cases_are_reused(self) -> None:
        self.assertEqual([case["id"] for case in self.cases], ["C07", "C08", "C09"])
        self.assertEqual(self.cases[1]["rag_query"],
                         "余量按最近销售速度只能卖几天应该优先处理什么")

    def test_top3_recall_and_mrr_are_calculated_and_c08_review_is_separate(self) -> None:
        queries = {case["id"]: case["rag_query"] for case in self.cases}
        kb = ScriptedKnowledgeBase({
            queries["C07"]: [match("sales_analysis_rules.md", "metrics", 1),
                             match("inventory_management.md", "risk", 2)],
            queries["C08"]: [match("product_analysis_sop.md", "analysis", 3),
                             match("inventory_management.md", "risk", 4)],
            queries["C09"]: [match("inventory_management.md", "advice", 5)],
        })
        report = evaluate_provider(kb, "local_hash", 384, self.cases)
        by_id = {item["case_id"]: item for item in report["cases"]}
        self.assertEqual(by_id["C07"]["recall_at_3"], 1.0)
        self.assertEqual(by_id["C07"]["mrr"], 0.5)
        self.assertEqual(by_id["C08"]["recall_at_3"], 1.0)
        self.assertEqual(by_id["C08"]["mrr"], 0.5)
        self.assertEqual(by_id["C08"]["evidence_sufficiency"]["status"],
                         "pending_manual_review")
        self.assertIn("不等于证据充分",
                      by_id["C08"]["evidence_sufficiency"]["check"])
        self.assertEqual(report["mean_recall_at_3"], 1.0)
        self.assertEqual(report["mean_mrr"], (0.5 + 0.5 + 1.0) / 3)
        self.assertTrue(all(k == 3 for _, k in kb.queries))

    def test_expected_source_missing_has_zero_recall_and_mrr(self) -> None:
        kb = ScriptedKnowledgeBase({case["rag_query"]: [
            match("product_analysis_sop.md", "analysis", 1)
        ] for case in self.cases})
        report = evaluate_provider(kb, "aliyun", 1024, self.cases)
        self.assertTrue(all(item["recall_at_3"] == 0.0 for item in report["cases"]))
        self.assertTrue(all(item["mrr"] == 0.0 for item in report["cases"]))
        self.assertEqual(report["model"], "text-embedding-v4")
        self.assertEqual(report["dimensions"], 1024)

    def test_retrieval_error_is_recorded_without_exception_text(self) -> None:
        class BrokenKnowledgeBase:
            def search(self, query: str, *, k: int = 3) -> dict:
                raise RuntimeError("embedding-secret")

        report = evaluate_provider(BrokenKnowledgeBase(), "aliyun", 1024,
                                   self.cases[:1])
        result = report["cases"][0]
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["recall_at_3"])
        self.assertNotIn("embedding-secret", str(report))

    def test_live_evaluation_stops_after_first_error_and_redacts_key(self) -> None:
        class BrokenKnowledgeBase:
            def __init__(self) -> None:
                self.queries = []

            def search(self, query: str, *, k: int = 3) -> dict:
                self.queries.append(query)
                raise RuntimeError("request failed with embedding-secret")

        kb = BrokenKnowledgeBase()
        report = evaluate_provider(kb, "aliyun", 1024, self.cases,
                                   stop_on_error=True,
                                   error_secret="embedding-secret")
        self.assertEqual(len(kb.queries), 1)
        self.assertTrue(report["stopped_on_error"])
        self.assertEqual(report["cases"][0]["status"], "error")
        self.assertNotIn("embedding-secret", str(report))
        self.assertIn("[REDACTED]", report["cases"][0]["error"])

    def test_comparison_reports_cloud_minus_local_deltas_without_api(self) -> None:
        queries = {case["id"]: case["rag_query"] for case in self.cases}
        local = ScriptedKnowledgeBase({query: [
            match("inventory_management.md", "risk", index)
        ] for index, query in enumerate(queries.values())})
        cloud = ScriptedKnowledgeBase({query: [
            match("product_analysis_sop.md", "other", index)
        ] for index, query in enumerate(queries.values())})
        with patch("scripts.evaluate_retrieval.load_embedding_settings",
                   return_value=EmbeddingSettings(
                       provider="aliyun", api_key="fake",
                       base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")), \
                patch("scripts.evaluate_retrieval.build_knowledge_base",
                      side_effect=[local, cloud]) as builder:
            report = run_evaluation(["local_hash", "aliyun"])
        self.assertEqual(builder.call_count, 2)
        self.assertEqual(report["metric_deltas_aliyun_minus_local_hash"], {
            "mean_recall_at_3": -1.0, "mean_mrr": -1.0,
        })


if __name__ == "__main__":
    unittest.main()
