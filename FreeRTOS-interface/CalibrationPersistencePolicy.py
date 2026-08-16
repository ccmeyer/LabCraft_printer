"""Calibration legacy-writer policy for the canonical storage cutover.

This module is deliberately Qt-free.  Experiment designs persist only the
declared policy; process-local environment overrides are evaluated by the
calibration manager at application start.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


SCHEMA_NAME = "labcraft.calibration_storage.policy"
SCHEMA_VERSION = 1


class LegacyWriterMode(str, Enum):
    CANONICAL_ONLY = "canonical_only"
    LEGACY_COMPATIBLE = "legacy_compatible"


@dataclass(frozen=True)
class CalibrationStoragePolicy:
    legacy_writer_mode: LegacyWriterMode
    source: str = "persisted"
    warning: str = ""

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "legacy_writer_mode": self.legacy_writer_mode.value,
        }


def new_experiment_policy() -> CalibrationStoragePolicy:
    return CalibrationStoragePolicy(
        LegacyWriterMode.CANONICAL_ONLY,
        source="new_experiment_default",
    )


def legacy_compatible_policy(
    *, source: str = "historical_default", warning: str = ""
) -> CalibrationStoragePolicy:
    return CalibrationStoragePolicy(
        LegacyWriterMode.LEGACY_COMPATIBLE,
        source=source,
        warning=warning,
    )


def load_calibration_storage_policy(value: Any) -> CalibrationStoragePolicy:
    """Load a persisted policy, conservatively retaining legacy writes.

    Missing policy is the expected shape for historical experiments.  Invalid
    or future policy documents also retain the compatibility writer and expose
    a warning to diagnostics instead of risking loss of the legacy copy.
    """

    if value is None:
        return legacy_compatible_policy()
    if not isinstance(value, Mapping):
        return legacy_compatible_policy(
            source="invalid_fallback",
            warning="calibration_storage must be a JSON object",
        )
    if str(value.get("schema_name") or "") != SCHEMA_NAME:
        return legacy_compatible_policy(
            source="invalid_fallback",
            warning="calibration_storage schema_name is unsupported",
        )
    try:
        version = int(value.get("schema_version"))
    except (TypeError, ValueError):
        version = -1
    if version != SCHEMA_VERSION:
        return legacy_compatible_policy(
            source="invalid_fallback",
            warning="calibration_storage schema_version is unsupported",
        )
    try:
        mode = LegacyWriterMode(str(value.get("legacy_writer_mode") or ""))
    except ValueError:
        return legacy_compatible_policy(
            source="invalid_fallback",
            warning="calibration_storage legacy_writer_mode is unsupported",
        )
    return CalibrationStoragePolicy(mode, source="persisted")


def normalize_calibration_storage_policy(value: Any) -> CalibrationStoragePolicy:
    if isinstance(value, CalibrationStoragePolicy):
        return value
    if isinstance(value, LegacyWriterMode):
        return CalibrationStoragePolicy(value, source="runtime")
    if isinstance(value, str):
        try:
            return CalibrationStoragePolicy(LegacyWriterMode(value), source="runtime")
        except ValueError:
            return legacy_compatible_policy(
                source="invalid_fallback",
                warning="runtime legacy writer mode is unsupported",
            )
    return load_calibration_storage_policy(value)


__all__ = [
    "CalibrationStoragePolicy",
    "LegacyWriterMode",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "legacy_compatible_policy",
    "load_calibration_storage_policy",
    "new_experiment_policy",
    "normalize_calibration_storage_policy",
]
