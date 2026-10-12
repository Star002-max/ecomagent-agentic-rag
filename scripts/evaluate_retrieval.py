"""Compare fixed Phase 7 RAG cases across local and cloud embeddings."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from src.agent.model import redact
from src.config import EmbeddingSettings, PROJECT_ROOT, load_embedding_settings
from src.rag import build_knowledge_base


CASES_PATH = PROJECT_ROOT / "evals" / "phase7_cases.json"
CASE_IDS = ("C07", "C08", "C09")


def load_rag_cases(path: Path = CASES_PATH) -> list[dict]:
    """Reuse the stable Phase 7 queries and expected source annotations."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in payload["cases"]}
    cases = [by_id[case_id] for case_id in CASE_IDS]
    if any("rag_query" not in case or not case.get("expected_rag_sources")
           for case in cases):
        raise ValueError("Phase 7 C07-C09必须包含固定RAG query和预期来源。")
    return cases


def evaluate_provider(knowledge_base, provider: str, dimensions: int,
                      cases: list[dict] | None = None, *,
                      stop_on_error: bool = False,
                      error_secret: str = "") -> dict:
    """Evaluate fixed retrievals; semantic sufficiency remains a human judgment."""
    selected_cases = cases or load_rag_cases()
    results = []
    for case in selected_cases:
        expected = set(case["expected_rag_sources"])
        try:
            matches = knowledge_base.search(case["rag_query"], k=3)["matches"][:3]
            ranked = [{"rank": rank, **match,
                       "is_expected_source": match["source"] in expected}
                      for rank, match in enumerate(matches, start=1)]
            relevant_ranks = [item["rank"] for item in ranked
                              if item["is_expected_source"]]
            recall = len({item["source"] for item in ranked} & expected) / len(expected)
            reciprocal_rank = 1 / min(relevant_ranks) if relevant_ranks else 0.0
            result = {
                "case_id": case["id"], "query": case["rag_query"], "top_k": 3,
                "expected_sources": sorted(expected), "results": ranked,
                "recall_at_3": recall, "mrr": reciprocal_rank,
                "status": "completed",
            }
        except Exception as exc:
            result = {
                "case_id": case["id"], "query": case["rag_query"], "top_k": 3,
                "expected_sources": sorted(expected), "results": [],
                "recall_at_3": None, "mrr": None,
                "status": "error", "error_type": type(exc).__name__,
            }
            if stop_on_error:
                result["error"] = redact(str(exc), error_secret)[:800]
        if case["id"] == "C08":
            result["evidence_sufficiency"] = {
                "status": "pending_manual_review",
                "check": ("命中库存管理来源不等于证据充分；检查返回片段是否明确支持"
                          "针对‘只能卖几天’的具体优先处理措施。"),
            }
        results.append(result)
        if stop_on_error and result["status"] == "error":
            break

    successful = [item for item in results if item["status"] == "completed"]
    return {
        "provider": provider,
        "model": "LocalHashEmbeddings" if provider == "local_hash" else "text-embedding-v4",
        "dimensions": dimensions,
        "case_count": len(results),
        "completed_case_count": len(successful),
        "stopped_on_error": any(item["status"] == "error" for item in results),
        "mean_recall_at_3": mean(item["recall_at_3"] for item in successful)
        if successful else None,
        "mean_mrr": mean(item["mrr"] for item in successful) if successful else None,
        "cases": results,
    }


def run_evaluation(providers: list[str]) -> dict:
    """Build each selected provider once. Selecting aliyun can incur API usage."""
    if not providers or any(provider not in {"local_hash", "aliyun"}
                            for provider in providers):
        raise ValueError("provider必须是local_hash或aliyun。")
    if len(set(providers)) != len(providers):
        raise ValueError("provider不能重复。")

    reports = []
    for provider in providers:
        settings = (EmbeddingSettings(provider="local_hash") if provider == "local_hash"
                    else None)
        try:
            if provider == "aliyun":
                settings = load_embedding_settings()
                if settings.provider != "aliyun":
                    raise ValueError(
                        "运行云端评估前必须显式设置EMBEDDING_PROVIDER=aliyun。")
            knowledge_base = build_knowledge_base(settings=settings)
        except Exception as exc:
            if provider != "aliyun":
                raise
            secret = settings.api_key if settings else ""
            reports.append({
                "provider": provider, "model": "text-embedding-v4",
                "dimensions": 1024, "case_count": len(CASE_IDS),
                "completed_case_count": 0, "stopped_on_error": True,
                "status": "error", "error_type": type(exc).__name__,
                "error": redact(str(exc), secret)[:800], "cases": [],
            })
            break
        dimensions = 384 if provider == "local_hash" else settings.dimensions
        result = evaluate_provider(
            knowledge_base, provider, dimensions,
            stop_on_error=(provider == "aliyun"),
            error_secret=settings.api_key if provider == "aliyun" else "",
        )
        reports.append(result)
        if result["stopped_on_error"]:
            break

    report = {
        "schema_version": "1.0",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "evals/phase7_cases.json",
        "case_ids": list(CASE_IDS),
        "providers": reports,
        "stopped_on_error": any(item.get("stopped_on_error") for item in reports),
        "interpretation_limit": (
            "固定3个query仅用于本项目回归对照；来源命中不代表回答正确。"
            "C08证据充分性须单独人工复核。"
        ),
    }
    by_provider = {item["provider"]: item for item in reports}
    if "local_hash" in by_provider and "aliyun" in by_provider:
        local, aliyun = by_provider["local_hash"], by_provider["aliyun"]
        report["metric_deltas_aliyun_minus_local_hash"] = {
            metric: (aliyun.get(metric) - local.get(metric)
                     if aliyun.get(metric) is not None and local.get(metric) is not None
                     else None)
            for metric in ("mean_recall_at_3", "mean_mrr")
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", action="append", choices=sorted({"local_hash", "aliyun"}),
                        help="可重复指定；仅默认运行LocalHash。aliyun会产生真实API请求。")
    parser.add_argument("--output", type=Path,
                        help="可选JSON输出路径；省略时只打印到stdout。")
    args = parser.parse_args()
    report = run_evaluation(args.provider or ["local_hash"])
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
