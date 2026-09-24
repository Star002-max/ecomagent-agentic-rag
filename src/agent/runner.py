"""A bounded LangChain model → tools → model loop for one user question."""

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langsmith import tracing_context

from src.models import AnalysisReport, StructuredOutputError, parse_analysis_report
from src.prompts.analysis import analysis_structure_repair_prompt, analysis_system_prompt
from src.prompts.basic import system_prompt
from src.tools import describe_tools
from src.tools.results import result_json

from .model import redact, safe_request_error


class AgentExecutionError(RuntimeError):
    """Invalid model protocol or an unexpected tool failure."""


@dataclass
class AgentResult:
    status: str
    answer: str
    model_calls: int
    tool_calls: list[dict]
    structured_output: dict | None = None


def final_text(message: AIMessage) -> str:
    """Read answer text only; never dump response metadata or reasoning fields."""
    if isinstance(message.content, str):
        return message.content.strip()
    return "\n".join(block.get("text", "") for block in message.content
                     if isinstance(block, dict) and block.get("type") == "text").strip()


class ProductAgent:
    """Keep messages only inside run(). Shared services are not chat memory.

    The model is dependency-injected, so offline tests can supply a clearly
    labeled scripted model. Production always uses the configured ChatOpenAI.
    """

    def __init__(self, model: Any, tools: list[StructuredTool], as_of_date: str,
                 *, api_key: str = "", max_model_calls: int = 6,
                 max_tool_calls: int = 8) -> None:
        if max_model_calls < 1 or max_tool_calls < 1:
            raise ValueError("循环和工具调用上限必须大于0。")
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("工具名称不能重复。")
        self._model = model.bind_tools(describe_tools(tools))
        self._tools = {tool.name: tool for tool in tools}
        self._as_of_date = as_of_date
        self._secret = api_key
        self._max_model_calls = max_model_calls
        self._max_tool_calls = max_tool_calls

    def run(self, question: str) -> AgentResult:
        """Execute model-selected calls, returning facts and compact audit data."""
        return self._run(question, system_prompt(self._as_of_date))

    def run_analysis(self, question: str) -> AgentResult:
        """Run the same loop and validate the final answer as AnalysisReport."""
        return self._run(question, analysis_system_prompt(self._as_of_date),
                         output_model=AnalysisReport, require_tool=True)

    def _run(self, question: str, prompt: str, *,
             output_model: type[AnalysisReport] | None = None,
             require_tool: bool = False) -> AgentResult:
        """Shared bounded loop; output validation never performs calculations."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("问题不能为空。")
        messages = [SystemMessage(content=prompt),
                    HumanMessage(content=question.strip())]
        trace: list[dict] = []
        seen_ids: set[str] = set()
        structure_repairs = 0
        awaiting_structure_repair = False
        # Explicitly disable external tracing even if the shell enabled it.
        with tracing_context(enabled=False):
            for number in range(1, self._max_model_calls + 1):
                try:
                    response = self._model.invoke(messages)
                except Exception as exc:
                    raise safe_request_error(exc, self._secret) from None
                if not isinstance(response, AIMessage):
                    raise AgentExecutionError("模型未返回AIMessage，停止执行。")
                if response.invalid_tool_calls:
                    raise AgentExecutionError("模型返回了无法解析的工具参数，停止执行。")
                if response.response_metadata.get("finish_reason") == "length":
                    raise AgentExecutionError("模型输出达到长度限制，未将截断内容当作完整答案。")
                messages.append(response)
                if not response.tool_calls:
                    answer = final_text(response)
                    if not answer:
                        raise AgentExecutionError("模型未返回工具调用或可见答案。")
                    if require_tool and not any(
                        item["execution_status"] == "success" for item in trace
                    ):
                        raise AgentExecutionError("综合分析未成功执行任何业务工具，任务未完成。")
                    safe_answer = redact(answer, self._secret)
                    structured = None
                    if output_model is not None:
                        try:
                            report = parse_analysis_report(safe_answer)
                        except StructuredOutputError as exc:
                            if structure_repairs >= 1:
                                raise AgentExecutionError(str(exc)) from None
                            structure_repairs += 1
                            awaiting_structure_repair = True
                            messages.append(HumanMessage(
                                content=analysis_structure_repair_prompt(str(exc))
                            ))
                            continue
                        structured = report.model_dump(mode="json")
                        safe_answer = report.model_dump_json()
                    return AgentResult("completed", safe_answer, number, trace, structured)
                if len(trace) + len(response.tool_calls) > self._max_tool_calls:
                    return AgentResult("limit_reached", "达到工具调用上限，任务未完成。", number, trace)
                if awaiting_structure_repair:
                    raise AgentExecutionError("结构修正阶段不应再次调用工具，任务已停止。")
                # Validate the batch before executing any of it.
                batch_ids = []
                for call in response.tool_calls:
                    call_id = call.get("id")
                    if not isinstance(call_id, str) or not call_id or call_id in seen_ids:
                        raise AgentExecutionError("工具调用ID缺失或重复，停止执行。")
                    if not isinstance(call.get("args"), dict):
                        raise AgentExecutionError("工具参数必须是对象。")
                    batch_ids.append(call_id)
                if len(set(batch_ids)) != len(batch_ids):
                    raise AgentExecutionError("同一批工具调用ID重复。")
                seen_ids.update(batch_ids)
                for call in response.tool_calls:
                    name = call["name"]
                    tool = self._tools.get(name)
                    if tool is None:
                        content = result_json(name, "error", error={
                            "code": "unknown_tool", "message": "工具不存在，请使用已提供的工具。",
                            "details": [],
                        })
                        message = ToolMessage(content=content, name=name,
                                              tool_call_id=call["id"], status="error")
                    else:
                        try:
                            message = tool.invoke({**call, "type": "tool_call"})
                        except Exception as exc:
                            # Tool-boundary errors are handled by Phase 3. An
                            # unexpected programming error must stop this run.
                            raise AgentExecutionError(
                                f"工具执行异常（{type(exc).__name__}），任务停止，请检查代码。"
                            ) from None
                    if not isinstance(message, ToolMessage):
                        raise AgentExecutionError("工具未返回ToolMessage。")
                    messages.append(message)
                    payload = json.loads(message.content)
                    trace.append(json.loads(redact(json.dumps({
                        "id": call["id"], "name": name, "arguments": call["args"],
                        "execution_status": message.status, "result": payload,
                    }, ensure_ascii=False, allow_nan=False), self._secret)))
            return AgentResult("limit_reached", "达到模型调用轮数上限，任务未完成。",
                               self._max_model_calls, trace)
