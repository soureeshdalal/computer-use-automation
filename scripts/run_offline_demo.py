"""Offline demo using mock planner (not submission evidence)."""

from __future__ import annotations

import subprocess
import sys
import time


def main() -> int:
    server = subprocess.Popen(
        [sys.executable, "-m", "demo_app.app"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    try:
        commands = [
            [
                sys.executable,
                "-m",
                "computer_use",
                "discover",
                "--planner",
                "mock",
                "--goal",
                "Look up member {{member_id}} and read their savings balance",
                "--param",
                "member_id=12345",
                "--name",
                "lookup_member_balance",
                "--output",
                "capabilities/lookup_member_balance.json",
                "--headless",
            ],
            [
                sys.executable,
                "-m",
                "computer_use",
                "replay",
                "capabilities/lookup_member_balance.json",
                "--input",
                "member_id=54321",
                "--input",
                "operator_password=demo",
                "--headless",
            ],
        ]
        for command in commands:
            result = subprocess.run(command, check=False)
            if result.returncode != 0:
                return result.returncode
        return 0
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
