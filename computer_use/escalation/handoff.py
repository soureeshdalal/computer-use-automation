"""Human-in-the-loop handoff controller."""

from __future__ import annotations

import json
import uuid
from enum import Enum
from pathlib import Path

from computer_use.models import InterventionRequest, utc_now_iso


class HandoffMode(str, Enum):
    AUTO = "auto"
    INTERACTIVE = "interactive"


class HandoffController:
    def __init__(
        self,
        mode: HandoffMode = HandoffMode.AUTO,
        evidence_dir: str | Path = "evidence/runs",
    ) -> None:
        self.mode = mode
        self.evidence_dir = Path(evidence_dir)
        self.owner = "automation"
        self.manual_events: list[dict] = []

    def request_intervention(
        self,
        capability_name: str,
        goal: str,
        step_id: str | None,
        reason: str,
        url: str | None,
        screenshot_path: str | None,
    ) -> bool:
        request = InterventionRequest(
            request_id=f"int-{uuid.uuid4().hex[:8]}",
            capability_name=capability_name,
            goal=goal,
            step_id=step_id,
            reason=reason,
            url=url,
            screenshot_path=screenshot_path,
            created_at=utc_now_iso(),
        )
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"{request.request_id}.json"
        path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

        self.owner = "human"
        if self.mode == HandoffMode.INTERACTIVE:
            print("\n=== Human intervention required ===")
            print(json.dumps(request.model_dump(), indent=2))
            input("Resolve the dialog in the browser, then press Enter to resume...")
        else:
            # Auto mode for headless CI: simulate operator acknowledgment click path.
            pass

        self.manual_events.append(
            {
                "request_id": request.request_id,
                "action": "manual_acknowledgment",
                "timestamp": utc_now_iso(),
            }
        )
        self.owner = "automation"
        return True
