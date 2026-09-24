"""Simple structured output for Phase 5 comprehensive product analysis."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class StructuredOutputError(ValueError):
    """The model's final text is not a valid analysis report."""


class AnalysisReport(BaseModel):
    """Presentation contract only; it does not calculate any business metric."""

    model_config = ConfigDict(extra="forbid", strict=True)

    sku: str = Field(pattern=r"^SKU\d{3}$", description="被分析的商品编号。")
    summary: str = Field(min_length=1, max_length=500, description="基于工具证据的简短结论。")
    findings: list[str] = Field(
        min_length=1, max_length=8,
        description="已确认的数据事实或明确标注的同期变化。",
    )
    risk_level: Literal["low", "medium", "high", "unknown"] = Field(
        description="仅基于当前证据的简单风险等级；证据不足时使用unknown。"
    )
    recommendations: list[str] = Field(
        min_length=1, max_length=5,
        description="与发现直接对应、且不超出现有证据的下一步建议。",
    )
    evidence_limits: list[str] = Field(
        min_length=1, max_length=5,
        description="数据不能证明的因果关系、缺失数据或方法限制。",
    )

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("summary不能为空。")
        return cleaned

    @field_validator("findings", "recommendations", "evidence_limits")
    @classmethod
    def strip_list_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("列表项不能为空。")
        return cleaned


def _json_text(text: str) -> str:
    """Accept plain JSON or one complete fenced JSON block, nothing else."""
    cleaned = text.strip()
    if cleaned.startswith("```json") and cleaned.endswith("```"):
        return cleaned[7:-3].strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        return cleaned[3:-3].strip()
    return cleaned


def parse_analysis_report(text: str) -> AnalysisReport:
    """Validate model text without repairing, filling, or changing its claims."""
    try:
        return AnalysisReport.model_validate_json(_json_text(text))
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            fields = sorted({".".join(str(part) for part in item["loc"])
                             for item in exc.errors(include_input=False, include_url=False)})
            detail = "、".join(fields) if fields else "JSON"
        else:
            detail = "JSON"
        raise StructuredOutputError(
            f"模型最终输出不符合AnalysisReport结构（问题字段：{detail}），任务未完成。"
        ) from None
