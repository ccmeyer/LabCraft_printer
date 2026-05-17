from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from QualificationReports import subsystem_for
from tools.qualification.manifest import ManifestError, QualificationManifest, load_manifest
from tools.qualification.test_catalog import test_catalog_entry


@dataclass(frozen=True)
class QualificationSuiteEntry:
    manifest_path: Path
    manifest: QualificationManifest

    @property
    def manifest_id(self) -> str:
        return self.manifest.manifest_id

    @property
    def display_name(self) -> str:
        suffix = "operator-gated" if self.manifest.requires_operator_prompts else self.manifest.profile
        return f"{self.manifest.name}  |  {suffix}  |  {len(self.manifest.expected_test_ids)} tests"

    @property
    def fixture_ids(self) -> tuple[str, ...]:
        return required_fixture_ids(self.manifest)


@dataclass(frozen=True)
class QualificationTestPlanRow:
    test_id: int
    status: str
    subsystem: str
    name: str
    evaluates: str
    metrics: str
    fixture_summary: str
    category: str


def default_manifest_root(repo_root: str | Path) -> Path:
    return Path(repo_root) / "tools" / "qualification" / "manifests"


def discover_suite_entries(root: str | Path) -> list[QualificationSuiteEntry]:
    manifest_root = Path(root)
    if not manifest_root.exists():
        return []

    entries: list[QualificationSuiteEntry] = []
    for manifest_path in manifest_root.glob("*.json"):
        try:
            entries.append(QualificationSuiteEntry(manifest_path=manifest_path, manifest=load_manifest(manifest_path)))
        except ManifestError:
            continue
    entries.sort(key=lambda item: _suite_sort_key(item.manifest.manifest_id))
    return entries


def _suite_sort_key(manifest_id: str) -> tuple[int, str]:
    preferred = {
        "factory_acceptance_v3": 0,
        "gripper_seal_v1": 1,
        "gripper_seal_stress_v1": 2,
        "xy_motion_v1": 3,
        "motion_envelope_v1": 4,
        "pressure_regulator_v1": 5,
        "valve_characterization_v1": 6,
        "valve_gap_sweep_v1": 7,
        "factory_acceptance_v2": 8,
        "factory_acceptance_v1": 9,
        "factory_acceptance_v0": 10,
    }
    return (preferred.get(manifest_id, 100), manifest_id)


def required_fixture_ids(manifest: QualificationManifest) -> tuple[str, ...]:
    ids = {
        str(item.get("fixture_id") or "").strip()
        for item in manifest.fixtures
        if str(item.get("fixture_id") or "").strip()
    }
    return tuple(sorted(ids))


def fixture_notes(manifest: QualificationManifest) -> list[str]:
    notes: list[str] = []
    for item in manifest.fixtures:
        fixture_id = str(item.get("fixture_id") or "").strip()
        operator_note = str(item.get("operator_note") or "").strip()
        if fixture_id and operator_note:
            notes.append(f"{fixture_id}: {operator_note}")
        elif fixture_id:
            notes.append(fixture_id)
    return notes


def _fixture_ids_by_test(manifest: QualificationManifest) -> dict[int, list[str]]:
    mapping: dict[int, list[str]] = {}
    for item in manifest.fixtures:
        fixture_id = str(item.get("fixture_id") or "").strip()
        if not fixture_id:
            continue
        for raw_test_id in item.get("required_for") or []:
            try:
                test_id = int(raw_test_id)
            except (TypeError, ValueError):
                continue
            mapping.setdefault(test_id, []).append(fixture_id)
    return mapping


def _metric_summary(rule: dict[str, Any]) -> str:
    metrics = rule.get("metrics") if isinstance(rule.get("metrics"), dict) else {}
    if not metrics:
        return ""
    return ", ".join(str(name) for name in metrics.keys())


def build_test_plan_rows(manifest: QualificationManifest) -> list[QualificationTestPlanRow]:
    fixture_by_test = _fixture_ids_by_test(manifest)
    rows: list[QualificationTestPlanRow] = []
    for test_id in manifest.expected_test_ids:
        rule = manifest.analysis_rules.get(str(test_id), {})
        category = str(rule.get("category") or "")
        fixture_summary = ", ".join(fixture_by_test.get(int(test_id), []))
        catalog = test_catalog_entry(int(test_id))
        rows.append(
            QualificationTestPlanRow(
                test_id=int(test_id),
                status="Not run",
                subsystem=subsystem_for(category),
                name=catalog.display_name,
                evaluates=catalog.evaluates,
                metrics=_metric_summary(rule),
                fixture_summary=fixture_summary,
                category=category,
            )
        )
    return rows
