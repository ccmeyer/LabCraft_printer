from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from QualificationReports import QualificationReportError, load_report, parse_report_timestamp


@dataclass(frozen=True)
class QualificationTimingEstimate:
    test_id: int
    typical_seconds: float
    sample_count: int
    min_seconds: float
    max_seconds: float
    source: str


class QualificationTimingModel:
    def __init__(
        self,
        by_manifest_test: dict[tuple[str, int], QualificationTimingEstimate] | None = None,
        by_test: dict[int, QualificationTimingEstimate] | None = None,
    ):
        self.by_manifest_test = by_manifest_test or {}
        self.by_test = by_test or {}

    def estimate_for(self, manifest_id: str, test_id: int) -> QualificationTimingEstimate | None:
        key = (str(manifest_id or ""), int(test_id))
        return self.by_manifest_test.get(key) or self.by_test.get(int(test_id))


def build_timing_model(report_root: str | Path) -> QualificationTimingModel:
    root = Path(report_root)
    if not root.exists():
        return QualificationTimingModel()

    manifest_samples: dict[tuple[str, int], list[float]] = {}
    test_samples: dict[int, list[float]] = {}
    for report_path in root.rglob("report.json"):
        try:
            report = load_report(report_path)
        except QualificationReportError:
            continue
        for manifest_id, test_id, duration_s in _durations_from_report(report):
            manifest_samples.setdefault((manifest_id, test_id), []).append(duration_s)
            test_samples.setdefault(test_id, []).append(duration_s)

    return QualificationTimingModel(
        by_manifest_test={
            key: _estimate(test_id=key[1], samples=samples, source="manifest")
            for key, samples in manifest_samples.items()
            if samples
        },
        by_test={
            test_id: _estimate(test_id=test_id, samples=samples, source="test")
            for test_id, samples in test_samples.items()
            if samples
        },
    )


def _durations_from_report(report: dict[str, Any]) -> list[tuple[str, int, float]]:
    if bool(report.get("aborted")):
        return []

    manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    manifest_id = str(manifest.get("manifest_id") or "")
    previous = parse_report_timestamp(report.get("started_at"))
    if previous is None:
        return []

    durations: list[tuple[str, int, float]] = []
    results = report.get("results") if isinstance(report.get("results"), list) else []
    for result in results:
        if not isinstance(result, dict):
            continue
        try:
            test_id = int(result.get("test_id"))
        except (TypeError, ValueError):
            continue
        if test_id <= 0:
            continue

        timestamp = parse_report_timestamp(result.get("timestamp"))
        if timestamp is None:
            return []
        duration_s = (timestamp - previous).total_seconds()
        previous = timestamp
        if duration_s < 0:
            return []
        durations.append((manifest_id, test_id, duration_s))
    return durations


def _estimate(*, test_id: int, samples: list[float], source: str) -> QualificationTimingEstimate:
    return QualificationTimingEstimate(
        test_id=int(test_id),
        typical_seconds=float(statistics.median(samples)),
        sample_count=len(samples),
        min_seconds=float(min(samples)),
        max_seconds=float(max(samples)),
        source=source,
    )
