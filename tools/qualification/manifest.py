from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    """Raised when a qualification manifest is missing required fields."""


@dataclass(frozen=True)
class QualificationManifest:
    schema_version: str
    manifest_id: str
    name: str
    profile: str
    expected_test_ids: tuple[int, ...]
    fixtures: tuple[dict[str, Any], ...]
    enforce_expected_test_ids: bool
    analysis_rules: dict[str, Any]
    raw: dict[str, Any]

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "name": self.name,
            "profile": self.profile,
            "expected_test_ids": list(self.expected_test_ids),
            "fixtures": [dict(item) for item in self.fixtures],
            "enforce_expected_test_ids": bool(self.enforce_expected_test_ids),
            "analysis_rules": dict(self.analysis_rules),
        }


def _manifest_dir() -> Path:
    return Path(__file__).resolve().parent / "manifests"


def _resolve_manifest_path(ref: str | Path) -> Path:
    ref_path = Path(ref)
    if ref_path.exists() or ref_path.suffix.lower() == ".json" or len(ref_path.parts) > 1:
        return ref_path
    return _manifest_dir() / f"{ref_path.name}.json"


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"Manifest is missing required string field '{key}'.")
    return value.strip()


def _parse_expected_test_ids(payload: dict[str, Any]) -> tuple[int, ...]:
    values = payload.get("expected_test_ids")
    if not isinstance(values, list) or not values:
        raise ManifestError("Manifest must include a non-empty 'expected_test_ids' list.")
    parsed: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise ManifestError("Manifest test IDs must be integers.")
        try:
            test_id = int(value)
        except Exception as exc:
            raise ManifestError("Manifest test IDs must be integers.") from exc
        if test_id <= 0:
            raise ManifestError("Manifest test IDs must be positive integers.")
        parsed.append(test_id)
    return tuple(parsed)


def _parse_analysis_rules(payload: dict[str, Any]) -> dict[str, Any]:
    rules = payload.get("analysis_rules", {})
    if not isinstance(rules, dict):
        raise ManifestError("Manifest 'analysis_rules' must be an object when present.")

    parsed: dict[str, Any] = {}
    for key, value in rules.items():
        try:
            test_id = int(key)
        except Exception as exc:
            raise ManifestError("Manifest analysis rule keys must be test IDs.") from exc
        if test_id <= 0:
            raise ManifestError("Manifest analysis rule keys must be positive test IDs.")
        if not isinstance(value, dict):
            raise ManifestError("Manifest analysis rule entries must be objects.")
        metrics = value.get("metrics", {})
        if metrics is not None and not isinstance(metrics, dict):
            raise ManifestError("Manifest analysis rule 'metrics' must be an object when present.")
        if isinstance(metrics, dict):
            for metric_name, metric_rule in metrics.items():
                if not isinstance(metric_name, str) or not metric_name:
                    raise ManifestError("Manifest metric rule names must be non-empty strings.")
                if not isinstance(metric_rule, dict):
                    raise ManifestError("Manifest metric rule entries must be objects.")
                maturity = str(metric_rule.get("maturity", "informational")).lower()
                if maturity not in {"informational", "candidate", "acceptance"}:
                    raise ManifestError("Manifest metric rule maturity must be informational, candidate, or acceptance.")
        parsed[str(test_id)] = dict(value)
    return parsed


def parse_manifest(payload: dict[str, Any]) -> QualificationManifest:
    if not isinstance(payload, dict):
        raise ManifestError("Manifest JSON must be an object.")

    schema_version = _require_string(payload, "schema_version")
    manifest_id = _require_string(payload, "manifest_id")
    name = _require_string(payload, "name")
    profile = _require_string(payload, "profile").upper()
    if profile not in {"SAFE", "FULL"}:
        raise ManifestError("Manifest profile must be SAFE or FULL.")

    fixtures = payload.get("fixtures", [])
    if not isinstance(fixtures, list):
        raise ManifestError("Manifest 'fixtures' must be a list when present.")
    for item in fixtures:
        if not isinstance(item, dict):
            raise ManifestError("Manifest fixture entries must be objects.")

    enforce_expected = payload.get("enforce_expected_test_ids", False)
    if not isinstance(enforce_expected, bool):
        raise ManifestError("Manifest 'enforce_expected_test_ids' must be a boolean when present.")

    return QualificationManifest(
        schema_version=schema_version,
        manifest_id=manifest_id,
        name=name,
        profile=profile,
        expected_test_ids=_parse_expected_test_ids(payload),
        fixtures=tuple(dict(item) for item in fixtures),
        enforce_expected_test_ids=enforce_expected,
        analysis_rules=_parse_analysis_rules(payload),
        raw=dict(payload),
    )


def load_manifest(ref: str | Path) -> QualificationManifest:
    path = _resolve_manifest_path(ref)
    if not path.exists():
        raise ManifestError(f"Qualification manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid manifest JSON: {path}") from exc
    return parse_manifest(payload)
