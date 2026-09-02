"""Copy strongest runs into evidence/submission for reviewers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evidence" / "runs"
SUBMISSION = ROOT / "evidence" / "submission"
CAPABILITY = ROOT / "capabilities" / "lookup_member_balance.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def newest_run(prefix: str) -> Path | None:
    matches = sorted(RUNS.glob(f"{prefix}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def copy_run(source: Path, target_name: str) -> None:
    target = SUBMISSION / target_name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def newest_runs(prefix: str, count: int = 1) -> list[Path]:
    matches = sorted(RUNS.glob(f"{prefix}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[:count]


def main() -> int:
    SUBMISSION.mkdir(parents=True, exist_ok=True)
    if CAPABILITY.exists():
        shutil.copy2(CAPABILITY, SUBMISSION / "capability.lookup_member_balance.json")

    run_map = {
        "01-discovery": newest_runs("discovery", 1),
        "02-replay-success": newest_runs("replay", 3),
        "03-business-outcome": newest_runs("replay", 3),
        "04-human-handoff": newest_runs("replay", 1),
    }
    copied: dict[str, str] = {}
    used: set[str] = set()

    success_run = None
    business_run = None
    handoff_run = None
    for run in sorted(RUNS.glob("replay-*"), key=lambda p: p.stat().st_mtime, reverse=True):
        summary_path = run / "summary.json"
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("status") == "success" and success_run is None:
            success_run = run
        if summary.get("status") == "business_outcome" and business_run is None:
            business_run = run
        if summary.get("recovered_conditions") and handoff_run is None:
            handoff_run = run

    folder_sources = {
        "01-discovery": run_map["01-discovery"][0] if run_map["01-discovery"] else None,
        "02-replay-success": success_run,
        "03-business-outcome": business_run,
        "04-human-handoff": handoff_run,
    }

    for folder, source in folder_sources.items():
        if source is None:
            continue
        copy_run(source, folder)
        copied[folder] = source.name
        used.add(source.name)

    manifest = [
        "# Submission Evidence",
        "",
        "Selected runs copied from local evidence/runs.",
        "",
        "| Folder | Source run |",
        "| --- | --- |",
    ]
    for folder, run_name in copied.items():
        manifest.append(f"| {folder} | `{run_name}` |")

    manifest.append("")
    manifest.append("## File digests")
    manifest.append("")
    for path in sorted(SUBMISSION.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.md":
            manifest.append(f"- `{path.relative_to(SUBMISSION)}`: `{digest(path)}`")

    (SUBMISSION / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(json.dumps({"submission_dir": str(SUBMISSION), "copied": copied}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
