"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policy.json"
CAPABILITIES_DIR = ROOT / "capabilities"
EVIDENCE_DIR = ROOT / "evidence" / "runs"
SUBMISSION_EVIDENCE_DIR = ROOT / "evidence" / "submission"

DEMO_APP_HOST = os.getenv("DEMO_APP_HOST", "127.0.0.1")
DEMO_APP_PORT = int(os.getenv("DEMO_APP_PORT", "8765"))
DEMO_APP_URL = f"http://{DEMO_APP_HOST}:{DEMO_APP_PORT}"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8766"))
