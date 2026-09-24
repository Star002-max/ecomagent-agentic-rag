"""Serialize a stable tool envelope and handle expected boundary failures."""

import json
from typing import Callable

from langchain_core.tools import ToolException
from pydantic import ValidationError

from src.services import CsvDataStore, DataValidationError


def result_json(tool_name: str, status: str, data: dict | None = None,
                error: dict | None = None) -> str:
    """Keep the service payload intact, including warnings, nulls and coverage."""
    return json.dumps({"schema_version": "1.0", "tool": tool_name,
                       "status": status, "data": data, "error": error},
                      ensure_ascii=False, allow_nan=False)


def validation_error_json(tool_name: str, error: ValidationError) -> str:
    """Return useful field errors without dumping input values or internals."""
    details = [{"field": ".".join(str(part) for part in item["loc"]),
                "type": item["type"], "message": item["msg"]}
               for item in error.errors(include_input=False, include_url=False)]
    return result_json(tool_name, "error", error={
        "code": "invalid_arguments", "message": "参数不符合工具schema，请按字段说明修正。",
        "details": details,
    })


def call_service(tool_name: str, service: Callable[..., dict],
                 store: CsvDataStore, **kwargs: object) -> str:
    """Delegate exactly once. Unexpected programming errors remain visible."""
    try:
        data = service(store, **kwargs)
    except DataValidationError as exc:
        raise ToolException(result_json(tool_name, "error", error={
            "code": "data_error", "message": str(exc), "details": [],
        })) from exc
    except ValueError as exc:
        raise ToolException(result_json(tool_name, "error", error={
            "code": "invalid_arguments", "message": str(exc), "details": [],
        })) from exc
    # Serialize outside the try: a broken service output is not an input error.
    return result_json(tool_name, data["status"], data=data)
