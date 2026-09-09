from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY = re.compile(r"(password|secret|token|api[_-]?key|ssn|social|credential)", re.I)


def redact(value: Any, key: str | None = None) -> Any:
    if key and SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
