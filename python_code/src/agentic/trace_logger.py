"""
Agentic step 5 — per-resonator JSONL trace logging.

Every prompt, tool call, tool result, and token count is appended to
``{log_dir}/{run_id}/res_{index:02d}.jsonl`` so failed runs can be replayed
and audited. Logging never raises into the agent loop.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of SDK objects (pydantic blocks) to plain data."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _jsonable(dump())
        except Exception:
            pass
    return repr(value)


class TraceLogger:
    """Append-only JSONL writer for one resonator's agentic run."""

    def __init__(self, log_dir: Path, run_id: str, index: int) -> None:
        self.path = Path(log_dir) / run_id / f"res_{index:02d}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._t0 = time.monotonic()

    def log(self, event: str, **payload: Any) -> None:
        record = {
            "t_s": round(time.monotonic() - self._t0, 3),
            "event": event,
            **{k: _jsonable(v) for k, v in payload.items()},
        }
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # tracing must never kill the run
