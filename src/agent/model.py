"""Use the configured OpenAI-compatible endpoint through LangChain."""

import re

from langchain_openai import ChatOpenAI

from src.config import Settings


class ModelRequestError(RuntimeError):
    """A sanitized provider failure; callers must not retry another model."""


def redact(text: str, secret: str) -> str:
    """Remove the exact configured secret and common key/bearer representations."""
    cleaned = text.replace(secret, "[REDACTED]") if secret else text
    cleaned = re.sub(r"sk-[A-Za-z0-9_.-]+", "[REDACTED]", cleaned)
    return re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", cleaned)


def safe_request_error(error: Exception, secret: str) -> ModelRequestError:
    """Expose HTTP status and provider error message, not requests or headers."""
    status = getattr(error, "status_code", None)
    body = getattr(error, "body", None)
    details = body.get("error", body) if isinstance(body, dict) else {}
    message = details.get("message", "") if isinstance(details, dict) else ""
    code = details.get("code", "") if isinstance(details, dict) else ""
    summary = f"模型请求失败：{type(error).__name__}"
    if status is not None:
        summary += f"，HTTP {status}"
    if code:
        summary += f"，code={code}"
    if message:
        summary += f"，{message}"
    else:
        summary += "。请检查网络、超时或模型接口；未自动重试或切换服务。"
    return ModelRequestError(redact(summary, secret)[:1200])


def create_model(settings: Settings) -> ChatOpenAI:
    """No fallback, no automatic retries and no Responses API conversion."""
    return ChatOpenAI(
        api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=0, timeout=60, max_retries=0, max_tokens=2048,
        use_responses_api=False,
    )
