"""Policy loading and enforcement."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from computer_use.models import ArtifactAction


class PolicyViolation(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PolicyEngine:
    def __init__(self, policy_path: str | Path) -> None:
        data = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        self.allowed_hosts: set[str] = set(data.get("allowed_hosts", []))
        self.allowed_actions: set[str] = set(data.get("allowed_actions", []))
        self.blocked_patterns = [
            re.compile(p, re.I) for p in data.get("blocked_control_patterns", [])
        ]
        self.risky_patterns = [
            re.compile(p, re.I) for p in data.get("risky_control_patterns", [])
        ]
        self.max_steps = int(data.get("max_steps", 40))
        self.step_timeout_ms = int(data.get("step_timeout_ms", 15000))
        self.max_retries = int(data.get("max_retries", 2))
        self.require_human_for_risky = bool(data.get("require_human_for_risky", True))

    def check_url(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        if host not in self.allowed_hosts:
            raise PolicyViolation(
                "URL_NOT_ALLOWED",
                f"Navigation to host '{host}' is not on the allowlist.",
            )

    def check_action(self, action: str) -> None:
        if action not in self.allowed_actions:
            raise PolicyViolation(
                "ACTION_NOT_ALLOWED",
                f"Action '{action}' is not permitted by policy.",
            )

    def classify_control(self, label: str) -> str:
        text = label.lower()
        for pattern in self.blocked_patterns:
            if pattern.search(text):
                return "blocked"
        for pattern in self.risky_patterns:
            if pattern.search(text):
                return "risky"
        return "safe"

    def is_risky_action(self, action: ArtifactAction, control_label: str) -> bool:
        if action in {ArtifactAction.NAVIGATE}:
            return False
        return self.classify_control(control_label) == "risky"


def redact_text(text: str) -> str:
    import re

    patterns = [
        (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_SECRET]"),
        (re.compile(r"\b\d{9,}\b"), "[REDACTED_ID]"),
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
    ]
    result = text
    for pattern, replacement in patterns:
        result = pattern.sub(replacement, result)
    return result


def redact_mapping(data: dict) -> dict:
    cleaned: dict = {}
    for key, value in data.items():
        if isinstance(value, str):
            if "password" in key.lower():
                cleaned[key] = "[REDACTED_SECRET]"
            else:
                cleaned[key] = redact_text(value)
        else:
            cleaned[key] = value
    return cleaned
