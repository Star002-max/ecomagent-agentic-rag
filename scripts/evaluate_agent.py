"""Run the fixed Phase 7 evaluation set offline or against two live Qwen cases."""

import argparse
import json
import resource
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage

from src.agent.model import ModelRequestError, create_model, redact
from src.agent.runner import ProductAgent
from src.config import EmbeddingSettings, PROJECT_ROOT, load_settings
from src.models import AnalysisReport
from src.rag import build_knowledge_base
from src.services import CsvDataStore
from src.tools import build_tools


DATASET_PATH = PROJECT_ROOT / "evals" / "phase7_cases.json"
LIVE_CASES = {"C06", "C09"}
METRICS = {
    "required_tool_recall", "tool_selection_precision", "rag_source_hit_rate",
    "structured_output_validity", "tool_evidence_check", "answer_fact_review",
    "evidence_limit_compliance", "failure_handling",
}
MAX_TOOL_EVIDENCE_CHARS = 5000


class SharedResourceInitializationError(RuntimeError):
    """A common CSV/RAG dependency failed before individual cases could start."""


class ScriptedFakeModel:
    """Independent scripted responses for exercising the Agent, not LLM quality."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = iter(responses)
        self.invocations = 0

    def bind_tools(self, definitions: list[dict]) -> "ScriptedFakeModel":
        self.tool_definitions = definitions
        return self

    def invoke(self, messages: list) -> AIMessage:
        self.invocations += 1
        return next(self._responses)


class BrokenRetriever:
    """Fault injection used only by C13; the other RAG cases use real Chroma."""

    def search(self, query: str, *, k: int = 3) -> dict:
        raise RuntimeError("injected retrieval failure")


def _call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _analysis_json(sku: str, summary: str, findings: list[str],
                   recommendation: str, limit: str, risk: str) -> str:
    return json.dumps({
        "sku": sku,
        "summary": summary,
        "findings": findings,
        "risk_level": risk,
        "recommendations": [recommendation],
        "evidence_limits": [limit],
    }, ensure_ascii=False)


def _fake_responses(case_id: str) -> list[AIMessage]:
    """Keep the scripted model plan separate from dataset expectations."""
    compare_001 = {
        "sku": "SKU001", "current_start": "2026-08-24", "current_end": "2026-09-22",
        "previous_start": "2026-07-25", "previous_end": "2026-08-23",
    }
    compare_002 = {**compare_001, "sku": "SKU002"}
    compare_005 = {**compare_001, "sku": "SKU005"}
    responses: dict[str, list[AIMessage]] = {
        "C01": [
            AIMessage(content="", tool_calls=[_call("get_product_info", {"sku": "SKU001"}, "c01-product")]),
            AIMessage(content="SKU001是桌面收纳盒，当前价格39.9元、评分4.5833。"),
        ],
        "C02": [
            AIMessage(content="", tool_calls=[_call("get_inventory_data", {"sku": "SKU003"}, "c02-inventory")]),
            AIMessage(content=("SKU003当前库存50件，可售约0.65天。该天数按近30天历史日均销量静态估算，"
                               "假设未来销量相同；不考虑在途补货或需求变化，因此不是需求预测。")),
        ],
        "C03": [
            AIMessage(content="", tool_calls=[_call("compare_sales_periods", compare_001, "c03-compare")]),
            AIMessage(content=_analysis_json("SKU001", "销量与Sessions同期下降，转化率基本稳定。",
                ["销量从1833降至1205件。", "Sessions从28021降至18226。", "转化率基本稳定。"],
                "继续监控流量和销售数据。", "同期变化不能证明外部原因。", "unknown")),
        ],
        "C04": [
            AIMessage(content="", tool_calls=[_call("compare_sales_periods", compare_002, "c04-compare")]),
            AIMessage(content=_analysis_json("SKU002", "访问量稳定而转化率下降。",
                ["Sessions从29038变为29018。", "Conversion Rate从6.50%降至3.91%。"],
                "补充页面和价格变化数据后继续分析。", "现有数据无法证明转化下降原因。", "unknown")),
        ],
        "C05": [
            AIMessage(content="", tool_calls=[_call("get_review_data", {"sku": "SKU005"}, "c05-review")]),
            AIMessage(content="SKU005最近30天均分2.1，低分评价47条，较前期下降约2.58分。"),
        ],
        "C06": [
            AIMessage(content="", tool_calls=[
                _call("compare_sales_periods", compare_005, "c06-compare"),
                _call("get_review_data", {"sku": "SKU005"}, "c06-review"),
            ]),
            AIMessage(content=_analysis_json("SKU005", "销量与评价同期恶化，Sessions基本持平。",
                ["销量从2130降至1276件。", "Sessions变化约0.06%。", "均分为2.1，低分评价47条。"],
                "核对低分评价并补充调查数据。", "同期变化不能证明销量下降由评价造成。", "unknown")),
        ],
        "C07": [
            AIMessage(content="", tool_calls=[_call("search_operation_knowledge", {
                "query": "可售天数库存风险分级", "k": 3}, "c07-rag")]),
            AIMessage(content="检索到的规则是：可售天数小于7天为高风险，7至14天为中风险，大于14天为低风险；库存为0时为缺货高风险。"),
        ],
        "C08": [
            AIMessage(content="", tool_calls=[_call("search_operation_knowledge", {
                "query": "余量按最近销售速度只能卖几天应该优先处理什么", "k": 3}, "c08-rag")]),
            AIMessage(content="本次检索返回的片段没有提供针对该情形的具体处理建议；仅凭当前证据，无法判断应该优先采取哪项措施。"),
        ],
        "C09": [
            AIMessage(content="", tool_calls=[
                _call("get_inventory_data", {"sku": "SKU003"}, "c09-inventory"),
                _call("search_operation_knowledge", {
                    "query": "库存风险分级和补货建议", "k": 3}, "c09-rag"),
            ]),
            AIMessage(content=("SKU003当前库存50件，可售约0.65天；按检索规则，小于7天属高风险。"
                               "规则建议立即核对在途补货和预计到货时间，并结合近期销量安排补货。"
                               "可售天数是按近30天历史日均销量作出的静态估算，假设未来销量相同，"
                               "不考虑在途补货或需求变化。")),
        ],
        "C10": [
            AIMessage(content="", tool_calls=[_call("get_product_info", {"sku": "SKU999"}, "c10-product")]),
            AIMessage(content=_analysis_json("SKU999", "当前数据源未找到SKU999，无法分析表现。",
                ["商品查询返回not_found。"], "核对SKU编号后重试。", "没有商品数据，无法评估风险。", "unknown")),
        ],
        "C11": [
            AIMessage(content="", tool_calls=[_call("get_sales_data", {
                "sku": "SKU001", "start_date": "2026-09-22", "end_date": "2026-09-23",
            }, "c11-sales")]),
            AIMessage(content="该区间只覆盖1天，第二天没有记录，不能视为完整两天数据。"),
        ],
        "C12": [
            AIMessage(content="", tool_calls=[_call("get_inventory_data", {}, "c12-invalid")]),
            AIMessage(content="库存查询参数不完整，未取得SKU库存数据。"),
        ],
        "C13": [
            AIMessage(content="", tool_calls=[_call("search_operation_knowledge", {
                "query": "库存风险和补货", "k": 3}, "c13-rag")]),
            AIMessage(content="本次知识检索失败，无法引用内部库存规则。"),
        ],
    }
    return responses[case_id]


def load_cases(path: Path = DATASET_PATH) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 10 <= len(cases) <= 15:
        raise ValueError("评估集必须包含10至15个案例。")
    seen: set[str] = set()
    required_fields = {"id", "entrypoint", "question", "required_tools",
                       "allowed_tools", "applicable_metrics", "answer_fact_checks",
                       "evidence_limit_checks"}
    for case in cases:
        if not required_fields.issubset(case):
            raise ValueError("评估案例缺少必需字段。")
        if case["id"] in seen:
            raise ValueError(f"评估案例ID重复：{case['id']}")
        seen.add(case["id"])
        if case["entrypoint"] not in {"run", "run_analysis"}:
            raise ValueError(f"{case['id']}的Agent入口无效。")
        if not set(case["required_tools"]).issubset(case["allowed_tools"]):
            raise ValueError(f"{case['id']}的required_tools必须属于allowed_tools。")
        if not set(case["applicable_metrics"]).issubset(METRICS):
            raise ValueError(f"{case['id']}包含未注册指标。")
        if not isinstance(case["answer_fact_checks"], list) or not isinstance(
                case["evidence_limit_checks"], list):
            raise ValueError(f"{case['id']}的人工复核检查必须使用数组。")
    return cases


def _dig(value: dict, dotted_path: str):
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _metric(status: str, passed: int = 0, applicable: int = 0,
            details: list[str] | None = None, **extra: object) -> dict:
    return {"status": status, "passed": passed, "applicable": applicable,
            "details": details or [], **extra}


def evaluate_case(case: dict, result: dict | None, *, error: str | None = None,
                  model_calls_attempted: int | None = None) -> dict:
    calls = result.get("tool_calls", []) if result else []
    actual_names = {call.get("name") for call in calls}
    metrics: dict[str, dict] = {}

    # A provider connection failure prevented the Agent from producing a
    # result; this is an unavailable evaluation, not a tool-selection failure.
    if error and result is None:
        metrics = {name: _metric("N/A", details=[error])
                   for name in case["applicable_metrics"]}

    if not (error and result is None) and "required_tool_recall" in case["applicable_metrics"]:
        required = set(case["required_tools"])
        found = required & actual_names
        denominator = len(required)
        status = "passed" if denominator and len(found) == denominator else "failed"
        metrics["required_tool_recall"] = _metric(
            status, len(found), denominator,
            [f"未调用必需工具：{name}" for name in sorted(required - found)],
            expected=sorted(required), actual=sorted(actual_names),
        )

    if not (error and result is None) and "tool_selection_precision" in case["applicable_metrics"]:
        allowed = set(case["allowed_tools"])
        correct = actual_names & allowed
        denominator = len(actual_names)
        status = "N/A" if denominator == 0 else (
            "passed" if len(correct) == denominator else "failed")
        unexpected = sorted(actual_names - allowed)
        metrics["tool_selection_precision"] = _metric(
            status, len(correct), denominator,
            [f"调用了不允许的工具：{name}" for name in unexpected],
            expected=sorted(allowed), actual=sorted(actual_names),
            actual_call_count=len(calls), redundant_call_count=len(calls) - denominator,
        )

    if not (error and result is None) and "rag_source_hit_rate" in case["applicable_metrics"]:
        expected_sources = set(case.get("expected_rag_sources", []))
        retrieved = set()
        for call in calls:
            if call.get("name") == "search_operation_knowledge":
                for match in call.get("result", {}).get("data", {}).get("matches", []):
                    retrieved.add(match.get("source"))
        hits = expected_sources & retrieved
        denominator = len(expected_sources)
        status = "passed" if denominator and len(hits) == denominator else "failed"
        metrics["rag_source_hit_rate"] = _metric(
            status, len(hits), denominator,
            [f"未检索到预期来源：{source}" for source in sorted(expected_sources - hits)],
            expected=sorted(expected_sources), actual=sorted(retrieved), top_k=3,
        )

    if not (error and result is None) and "structured_output_validity" in case["applicable_metrics"]:
        try:
            output = result.get("structured_output") if result else None
            AnalysisReport.model_validate(output)
            schema_status, details = "passed", []
        except Exception as exc:
            schema_status, details = "failed", [f"结构化输出无效：{type(exc).__name__}"]
        metrics["structured_output_validity"] = _metric(
            schema_status, int(schema_status == "passed"), 1, details)

    if not (error and result is None) and "tool_evidence_check" in case["applicable_metrics"]:
        facts = case.get("expected_tool_facts", [])
        passed_facts, details, evidence = 0, [], []
        for fact in facts:
            matching = [call for call in calls if call.get("name") == fact["tool"]]
            observed, found = (None, False)
            for call in matching:
                observed, found = _dig(call.get("result", {}), fact["path"])
                if found:
                    break
            expected = fact["equals"]
            tolerance = fact.get("tolerance", 0)
            equal = found and (
                abs(observed - expected) <= tolerance
                if isinstance(expected, (int, float)) and not isinstance(expected, bool)
                and isinstance(observed, (int, float)) and not isinstance(observed, bool)
                else observed == expected
            )
            passed_facts += int(equal)
            evidence.append({"tool": fact["tool"], "path": fact["path"],
                             "expected": expected,
                             "observed": observed if found else None,
                             "status": "passed" if equal else "failed"})
            if not equal:
                details.append(f"{fact['tool']}.{fact['path']}预期{expected}，实际{observed if found else 'missing'}")
        denominator = len(facts)
        status = "passed" if denominator and passed_facts == denominator else "failed"
        metrics["tool_evidence_check"] = _metric(
            status, passed_facts, denominator, details, evidence=evidence)

    if not (error and result is None) and "answer_fact_review" in case["applicable_metrics"]:
        checks = case["answer_fact_checks"]
        metrics["answer_fact_review"] = _metric(
            "pending_manual_review" if checks else "N/A", 0, len(checks),
            checks, review_required=bool(checks),
        )

    if not (error and result is None) and "evidence_limit_compliance" in case["applicable_metrics"]:
        checks = case["evidence_limit_checks"]
        metrics["evidence_limit_compliance"] = _metric(
            "pending_manual_review" if checks else "N/A", 0, len(checks),
            checks, review_required=bool(checks),
        )

    if not (error and result is None) and "failure_handling" in case["applicable_metrics"]:
        expected = case.get("expected_failure", {})
        matched = [call for call in calls if call.get("name") == expected.get("tool")]
        observed = matched[-1].get("result", {}) if matched else {}
        status_match = observed.get("status") == expected.get("result_status")
        error_match = ("error_code" not in expected or
                       (observed.get("error") or {}).get("code") == expected["error_code"])
        auto_ok = bool(expected) and status_match and error_match
        checks = case["answer_fact_checks"] + case["evidence_limit_checks"]
        metric_status = ("failed" if not auto_ok else
                         "pending_manual_review" if checks else "passed")
        metrics["failure_handling"] = _metric(
            metric_status, int(auto_ok), 1,
            [] if auto_ok else ["实际状态或错误码与预期不符"],
            automated_status="passed" if auto_ok else "failed",
            manual_checks=checks,
        )

    compact_calls = []
    for call in calls:
        envelope = call.get("result", {})
        raw_data = envelope.get("data")
        serialized_data = json.dumps(raw_data, ensure_ascii=False, allow_nan=False)
        if len(serialized_data) <= MAX_TOOL_EVIDENCE_CHARS:
            evidence = {"data": raw_data, "truncated": False}
        else:
            evidence = {
                "data": None, "truncated": True,
                "serialized_chars": len(serialized_data),
                "preview": serialized_data[:800],
                "preview_note": "完整Tool数据超过单次记录上限，preview仅供定位，不是完整证据。",
            }
        compact = {
            "name": call.get("name"), "arguments": call.get("arguments"),
            "execution_status": call.get("execution_status"),
            "result_status": envelope.get("status"),
            "error_code": (envelope.get("error") or {}).get("code"),
            "error": envelope.get("error"),
            "evidence": evidence,
        }
        compact_calls.append(compact)

    return {
        "id": case["id"], "title": case["title"], "status": "error" if error else (
            result.get("status", "error") if result else "error"),
        "error": error,
        "model_calls": result.get("model_calls") if result else model_calls_attempted,
        "model_call_count_kind": "completed_agent_calls" if result else (
            "attempts_before_error" if model_calls_attempted is not None else None),
        "answer": result.get("answer") if result else None,
        "structured_output": result.get("structured_output") if result else None,
        "tool_calls": compact_calls,
        "metrics": metrics,
    }


def aggregate_metrics(case_results: list[dict]) -> dict:
    aggregates = {name: {"passing_cases": 0, "failing_cases": 0,
                         "pending_manual_review_cases": 0,
                         "pending_review_items": 0,
                         "numerator": 0, "denominator": 0} for name in METRICS}
    for case in case_results:
        for name, metric in case["metrics"].items():
            if metric["status"] == "N/A":
                continue
            aggregate = aggregates[name]
            status = metric.get("automated_status", metric["status"])
            if status in {"passed", "failed"}:
                aggregate["denominator"] += metric["applicable"]
                aggregate["numerator"] += metric["passed"]
            if metric["status"] == "passed":
                aggregate["passing_cases"] += 1
            elif metric["status"] == "failed":
                aggregate["failing_cases"] += 1
            elif metric["status"] == "pending_manual_review":
                aggregate["pending_manual_review_cases"] += 1
                aggregate["pending_review_items"] += len(
                    metric.get("manual_checks", metric.get("details", [])))
    for aggregate in aggregates.values():
        aggregate["rate"] = (aggregate["numerator"] / aggregate["denominator"]
                             if aggregate["denominator"] else None)
    return aggregates


def _rag_baseline(cases: list[dict], knowledge_base) -> list[dict]:
    baseline = []
    for case in cases:
        if "rag_query" not in case:
            continue
        expected = set(case.get("expected_rag_sources", []))
        try:
            matches = knowledge_base.search(case["rag_query"], k=3)["matches"]
        except Exception as exc:
            baseline.append({
                "case_id": case["id"], "query": case["rag_query"], "top_k": 3,
                "expected_sources": sorted(expected), "source_hit": None,
                "status": "error", "error_type": type(exc).__name__,
                "error": "该问题的RAG基线检索失败；其他问题仍继续记录。",
                "results": [],
            })
            continue
        ranked = [{"rank": rank, **match,
                   "is_expected_source": match["source"] in expected}
                  for rank, match in enumerate(matches, start=1)]
        returned = {match["source"] for match in matches}
        baseline.append({
            "case_id": case["id"], "query": case["rag_query"], "top_k": 3,
            "expected_sources": sorted(expected),
            "source_hit": bool(expected) and expected.issubset(returned),
            "status": "completed", "results": ranked,
        })
    return baseline


def _get_fake_retriever(case_id: str, knowledge_base):
    return BrokenRetriever() if case_id == "C13" else knowledge_base


def run_offline(cases: list[dict]) -> dict:
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        store = CsvDataStore()
        knowledge_base = build_knowledge_base(
            settings=EmbeddingSettings(provider="local_hash"))
    except Exception as exc:
        raise SharedResourceInitializationError(
            f"共享CSV或RAG资源初始化失败（{type(exc).__name__}），尚未运行任何案例。"
        ) from None
    results = []
    for case in cases:
        model = None
        try:
            model = ScriptedFakeModel(_fake_responses(case["id"]))
            tools = build_tools(store, _get_fake_retriever(case["id"], knowledge_base))
            agent = ProductAgent(model, tools, store.as_of_date)
            method = getattr(agent, case["entrypoint"])
            result = asdict(method(case["question"]))
            results.append(evaluate_case(case, result))
        except Exception as exc:
            results.append(evaluate_case(
                case, None, error=f"{type(exc).__name__}: {exc}",
                model_calls_attempted=model.invocations if model else None))
    rag_baseline = _rag_baseline(cases, knowledge_base)
    return {
        "mode": "offline", "model_kind": "scripted_fake",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_as_of": store.as_of_date, "embedding": "LocalHashEmbeddings",
        "case_count": len(cases), "completed_case_count": sum(
            item["status"] == "completed" for item in results),
        "cases": results, "metrics": aggregate_metrics(results),
        "rag_top3_baseline": rag_baseline,
        "interpretation_limit": (
            "Scripted Fake Model案例验证Agent协议、评估器和本地组件；不代表真实Qwen的工具选择或回答准确率。"
        ),
        "resources": {
            "wall_seconds": round(time.perf_counter() - started, 4),
            "process_cpu_seconds": round(time.process_time() - cpu_started, 4),
            "process_peak_rss_bytes": _peak_rss_bytes(),
            "rss_scope": "当前Python进程生命周期峰值，包含解释器、依赖导入和本次评估，不是Phase 7增量内存。",
        },
    }


def run_live(cases: list[dict]) -> dict:
    if {case["id"] for case in cases} != LIVE_CASES:
        raise ValueError("Live Evaluation固定只允许C06与C09。")
    started = time.perf_counter()
    cpu_started = time.process_time()
    settings = load_settings()
    store = CsvDataStore()
    # This Live suite exercises Qwen behavior; its RAG baseline remains offline.
    knowledge_base = build_knowledge_base(
        settings=EmbeddingSettings(provider="local_hash"))
    agent = ProductAgent(create_model(settings), build_tools(store, knowledge_base),
                         store.as_of_date, api_key=settings.api_key)
    results, stopped_on_api_error = [], False
    for case in cases:
        try:
            result = asdict(getattr(agent, case["entrypoint"])(case["question"]))
            results.append(evaluate_case(case, result))
        except ModelRequestError as exc:
            results.append(evaluate_case(
                case, None, error=redact(str(exc), settings.api_key),
                model_calls_attempted=1))
            stopped_on_api_error = True
            break
        except Exception as exc:
            results.append(evaluate_case(case, None, error=redact(
                f"{type(exc).__name__}: {exc}", settings.api_key)))
    return {
        "mode": "live", "model_kind": settings.model,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_as_of": store.as_of_date, "embedding": "LocalHashEmbeddings",
        "planned_case_ids": sorted(LIVE_CASES), "cases": results,
        "metrics": aggregate_metrics(results),
        "stopped_on_api_error": stopped_on_api_error,
        "rag_top3_baseline": _rag_baseline(cases, knowledge_base),
        "interpretation_limit": "结果仅代表本次固定验收样本，不是Agent整体准确率。",
        "resources": {
            "wall_seconds": round(time.perf_counter() - started, 4),
            "process_cpu_seconds": round(time.process_time() - cpu_started, 4),
            "process_peak_rss_bytes": _peak_rss_bytes(),
            "rss_scope": "当前Python进程生命周期峰值，包含解释器、依赖导入和本次评估，不是Phase 7增量内存。",
        },
    }, settings.api_key


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _git_revision() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                              check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    args = parser.parse_args()
    cases = load_cases()
    shared_setup_failed = False
    if args.mode == "live":
        selected = [case for case in cases if case["id"] in LIVE_CASES]
        payload, secret = run_live(selected)
        destination = PROJECT_ROOT / "docs" / "phase7_live_results.json"
    else:
        try:
            payload = run_offline(cases)
        except SharedResourceInitializationError as exc:
            shared_setup_failed = True
            payload = {
                "mode": "offline", "status": "shared_resource_initialization_error",
                "error": str(exc), "case_count": len(cases),
                "completed_case_count": 0, "cases": [],
                "metrics": aggregate_metrics([]), "rag_top3_baseline": [],
                "interpretation_limit": "共享数据/RAG资源初始化未完成，因此未运行任何评估案例。",
            }
        secret = ""
        destination = PROJECT_ROOT / "docs" / "phase7_offline_results.json"
    payload["dataset_version"] = "1.0"
    payload["git_revision"] = _git_revision()
    payload["case_status_counts"] = {
        status: sum(item["status"] == status for item in payload["cases"])
        for status in ("completed", "error", "limit_reached")
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    safe = redact(encoded, secret)
    destination.write_text(safe, encoding="utf-8")
    payload_bytes = len(safe.encode("utf-8"))
    print(json.dumps({
        "mode": payload["mode"], "cases": payload["case_count"] if "case_count" in payload
        else len(payload["cases"]), "case_status_counts": payload["case_status_counts"],
        "result_file": str(destination.relative_to(PROJECT_ROOT)),
        "result_file_bytes": payload_bytes,
        "metrics": payload["metrics"], "resources": payload["resources"],
    }, ensure_ascii=False, indent=2))
    if shared_setup_failed:
        raise SystemExit(1)
    if payload.get("stopped_on_api_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
