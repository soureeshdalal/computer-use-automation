"""End-to-end submission flow with live OpenAI discovery when configured."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(command))
    return subprocess.run(command, check=False, text=True, capture_output=True)


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY must be set for the genuine discovery run.", file=sys.stderr)
        return 1

    server = subprocess.Popen(
        [sys.executable, "-m", "demo_app.app"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    artifact = ROOT / "capabilities" / "lookup_member_balance.json"
    try:
        steps = [
            [
                sys.executable,
                "-m",
                "computer_use",
                "discover",
                "--planner",
                "openai",
                "--goal",
                "Sign in, look up member {{member_id}}, and read the savings balance",
                "--param",
                "member_id=12345",
                "--name",
                "lookup_member_balance",
                "--output",
                str(artifact),
                "--headless",
            ],
            [
                sys.executable,
                "-m",
                "computer_use",
                "replay",
                str(artifact),
                "--input",
                "member_id=54321",
                "--input",
                "operator_password=demo",
                "--headless",
            ],
            [
                sys.executable,
                "-m",
                "computer_use",
                "replay",
                str(artifact),
                "--input",
                "member_id=99999",
                "--input",
                "operator_password=demo",
                "--headless",
            ],
            [
                sys.executable,
                "-m",
                "computer_use",
                "replay",
                str(artifact),
                "--input",
                "member_id=42424",
                "--input",
                "operator_password=demo",
                "--human-mode",
                "interactive",
            ],
        ]
        for command in steps[:-1]:
            result = run(command)
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            if result.returncode != 0:
                return result.returncode

        print("Handoff demo requires a headed browser. Running with auto ack in headless.")
        handoff_cmd = steps[-1][:-2] + ["--headless"]
        result = run(handoff_cmd)
        print(result.stdout)
        if result.returncode != 0:
            return result.returncode

        collect = run([sys.executable, str(ROOT / "scripts" / "collect_submission_evidence.py")])
        print(collect.stdout)
        return collect.returncode
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
