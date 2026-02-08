from __future__ import annotations

import json
from typing import Any


def dumps(msg: dict[str, Any]) -> str:
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False)


def status(phase: str, detail: str = "") -> dict[str, Any]:
    return {"type": "status", "phase": phase, "detail": detail}


def error(message: str, detail: str = "") -> dict[str, Any]:
    return {"type": "error", "message": message, "detail": detail}

