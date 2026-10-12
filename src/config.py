"""Read local secrets without logging or changing process environment."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str
    model: str


@dataclass(frozen=True)
class EmbeddingSettings:
    """Independent configuration for selecting RAG embeddings."""

    provider: str = "local_hash"
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = "text-embedding-v4"
    dimensions: int = 1024


def load_embedding_settings(env_path: Path = PROJECT_ROOT / ".env") -> EmbeddingSettings:
    """Load embedding settings without requiring cloud credentials offline."""
    local = dotenv_values(env_path) if env_path.exists() else {}

    def value(name: str, default: str = "") -> str:
        raw = os.environ[name] if name in os.environ else local.get(name, default)
        return raw.strip() if isinstance(raw, str) else default

    provider = value("EMBEDDING_PROVIDER", "local_hash").lower()
    if provider == "local_hash":
        return EmbeddingSettings(provider="local_hash")
    if provider != "aliyun":
        raise ValueError("EMBEDDING_PROVIDER仅支持local_hash或aliyun。")

    api_key = value("EMBEDDING_API_KEY")
    base_url = value("EMBEDDING_BASE_URL")
    model = value("EMBEDDING_MODEL", "text-embedding-v4")
    dimensions_text = value("EMBEDDING_DIMENSIONS", "1024")
    if not api_key:
        raise ValueError("使用aliyun Embedding时必须配置EMBEDDING_API_KEY。")
    if not base_url:
        raise ValueError("使用aliyun Embedding时必须配置EMBEDDING_BASE_URL。")
    url = urlsplit(base_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or (
        url.query or url.fragment
    ):
        raise ValueError("EMBEDDING_BASE_URL必须是HTTPS地址，且不包含凭据、查询参数或片段。")
    if (not url.hostname.endswith(".cn-beijing.maas.aliyuncs.com")
            or url.path.rstrip("/") != "/compatible-mode/v1"):
        raise ValueError("EMBEDDING_BASE_URL必须使用北京地域OpenAI兼容接口Base URL。")
    try:
        dimensions = int(dimensions_text)
    except ValueError:
        raise ValueError("EMBEDDING_DIMENSIONS必须是整数。") from None
    if dimensions != 1024:
        raise ValueError("当前text-embedding-v4配置固定使用1024维。")
    if model != "text-embedding-v4":
        raise ValueError("当前aliyun Embedding仅支持text-embedding-v4。")
    return EmbeddingSettings(provider=provider, api_key=api_key,
                             base_url=base_url.rstrip("/"), model=model,
                             dimensions=dimensions)


def load_settings(env_path: Path = PROJECT_ROOT / ".env") -> Settings:
    """Prefer environment variables; never include config values in errors."""
    local = dotenv_values(env_path) if env_path.exists() else {}
    values = {}
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        value = os.environ[name] if name in os.environ else local.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"缺少配置：{name}，请在本地.env或环境变量设置。")
        values[name] = value.strip()
    url = urlsplit(values["LLM_BASE_URL"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or (
        url.query or url.fragment
    ):
        raise ValueError("LLM_BASE_URL必须是HTTPS地址，且不包含凭据、查询参数或片段。")
    return Settings(api_key=values["LLM_API_KEY"],
                    base_url=values["LLM_BASE_URL"].rstrip("/"), model=values["LLM_MODEL"])
