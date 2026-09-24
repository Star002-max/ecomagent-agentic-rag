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
