"""Business outcome detection patterns."""

from __future__ import annotations

import re

from computer_use.models import BusinessOutcome


PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"no record found", re.I),
        "MEMBER_NOT_FOUND",
        "No member record exists for the supplied identifier.",
    ),
    (
        re.compile(r"permission denied|access restricted", re.I),
        "PERMISSION_DENIED",
        "Operator profile lacks permission for this account.",
    ),
]


def detect_business_outcome(page_text: str) -> BusinessOutcome | None:
    for pattern, code, message in PATTERNS:
        if pattern.search(page_text):
            return BusinessOutcome(code=code, message=message)
    return None
