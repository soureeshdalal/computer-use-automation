"""Structured run logging and evidence capture."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from computer_use.safety.policy import redact_mapping, redact_text


class RunLogger:
    def __init__(self, base_dir: str | Path, run_kind: str) -> None:
        self.run_id = f"{run_kind}-{uuid.uuid4().hex[:10]}"
        self.run_dir = Path(base_dir) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self._llm_calls = 0

    @property
    def llm_calls(self) -> int:
        return self._llm_calls

    def increment_llm_calls(self) -> None:
        self._llm_calls += 1

    def log(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event_type,
            "payload": redact_mapping(payload),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def write_summary(self, summary: dict[str, Any]) -> Path:
        path = self.run_dir / "summary.json"
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return path

    def screenshot_path(self, name: str) -> Path:
        return self.run_dir / f"{name}.png"

    def trace_path(self) -> Path:
        return self.run_dir / "trace.zip"


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_mapping(record) if isinstance(record, dict) else record
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe) + "\n")


def redact_for_persist(value: str) -> str:
    return redact_text(value)
