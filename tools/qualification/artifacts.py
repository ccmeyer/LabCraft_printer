from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_OUTPUT_ROOT = Path("hil_reports") / "qualification"


@dataclass(frozen=True)
class RunArtifacts:
    run_dir: Path
    raw_selftest_path: Path
    report_path: Path
    summary_csv_path: Path
    traces_dir: Path
    plots_dir: Path


def now_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_machine_id(machine_id: str) -> str:
    text = str(machine_id or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return text or "LC-UNASSIGNED"


def create_run_artifacts(
    machine_id: str,
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    timestamp: str | None = None,
) -> RunArtifacts:
    safe_machine_id = sanitize_machine_id(machine_id)
    stamp = str(timestamp or now_timestamp())
    base_dir = Path(output_root) / safe_machine_id
    run_dir = base_dir / stamp
    if run_dir.exists():
        for idx in range(1, 1000):
            candidate = base_dir / f"{stamp}_{idx:03d}"
            if not candidate.exists():
                run_dir = candidate
                break
    run_dir.mkdir(parents=True, exist_ok=False)
    return RunArtifacts(
        run_dir=run_dir,
        raw_selftest_path=run_dir / "raw_selftest.json",
        report_path=run_dir / "report.json",
        summary_csv_path=run_dir / "summary.csv",
        traces_dir=run_dir / "traces",
        plots_dir=run_dir / "plots",
    )
