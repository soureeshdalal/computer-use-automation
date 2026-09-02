"""Validate submission readiness."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "REPORT.md"
CAPABILITY = ROOT / "capabilities" / "lookup_member_balance.json"
SUBMISSION = ROOT / "evidence" / "submission"

REQUIRED_HEADINGS = [
    "# 1. Architecture",
    "# 2. Artifact schema",
    "# 3. Determinism & error handling",
    "# 4. Heterogeneity & multi-tenant",
    "# 5. Escalation & handoff",
    "# 6. Safety",
    "# 7. Cuts",
]


def main() -> int:
    errors: list[str] = []
    if not CAPABILITY.exists():
        errors.append("Missing capabilities/lookup_member_balance.json")
    if not REPORT.exists():
        errors.append("Missing REPORT.md")
    else:
        text = REPORT.read_text(encoding="utf-8")
        for heading in REQUIRED_HEADINGS:
            if heading not in text:
                errors.append(f"REPORT.md missing heading: {heading}")

    for folder in [
        "01-discovery",
        "02-replay-success",
        "03-business-outcome",
        "04-human-handoff",
    ]:
        if not (SUBMISSION / folder).exists():
            errors.append(f"Missing evidence/submission/{folder}")

    secret_patterns = [
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
    ]
    for path in ROOT.rglob("*"):
        if path.is_dir() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path.name.startswith("test_") or "/tests/" in str(path):
            continue
        if path.suffix not in {".py", ".md", ".json", ".jsonl", ".env.example"}:
            continue
        if path.name == ".env":
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in secret_patterns:
            if pattern.search(content):
                errors.append(f"Possible secret in {path}")

    if (ROOT / ".env").exists() and "OPENAI_API_KEY=" in (ROOT / ".env").read_text():
        pass  # local only

    result = subprocess.run(["pytest", "-q"], cwd=ROOT, check=False)
    if result.returncode != 0:
        errors.append("pytest failed")

    if errors:
        print("Preflight failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
