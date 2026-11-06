"""Validated, portable choices for offline plate-reader analysis."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import pandas as pd


SCHEMA_VERSION = "plate_reader_analysis_settings_v1"
SETTINGS_FILENAME = "plate_reader_analysis_settings.json"
WELL_RE = re.compile(r"^([A-P])([1-9]|1[0-9]|2[0-4])$")


def normalize_settings(settings: dict | None = None) -> dict:
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("Analysis settings must be a JSON object.")
    raw = {} if settings is None else dict(settings)
    allowed = {"schema_version", "nominal_targets", "target_tolerance_percent", "excluded_wells", "target_source"}
    if set(raw) - allowed:
        raise ValueError("Unknown analysis settings: " + ", ".join(sorted(set(raw) - allowed)))
    if raw.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError("Unsupported plate-reader analysis settings schema.")
    if isinstance(raw.get("target_tolerance_percent"), bool):
        raise ValueError("Target tolerance must be numeric, not a boolean.")
    try:
        tolerance = float(raw.get("target_tolerance_percent", 2.0))
    except (TypeError, ValueError):
        raise ValueError("Target tolerance must be numeric.") from None
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 100:
        raise ValueError("Target tolerance must be between 0 and 100 percent.")
    targets = {}
    target_values = raw.get("nominal_targets", {})
    excluded_values = raw.get("excluded_wells", {})
    if not isinstance(target_values, dict) or not isinstance(excluded_values, dict):
        raise ValueError("Intended targets and excluded wells must be JSON objects.")
    for column, values in target_values.items():
        if not isinstance(column, str) or not column.strip() or not isinstance(values, list) or not values:
            raise ValueError("Each reagent must have a name and a nonempty list of intended concentrations.")
        if any(isinstance(value, bool) for value in values):
            raise ValueError("Intended concentrations must be numeric.")
        try:
            levels = [float(value) for value in values]
        except (TypeError, ValueError):
            raise ValueError(f"Intended concentrations for {column} must be numeric.") from None
        if any(not math.isfinite(value) or value < 0 for value in levels) or len(set(levels)) != len(levels):
            raise ValueError(f"Intended concentrations for {column} must be finite, nonnegative, and unique.")
        targets[column] = sorted(levels)
    exclusions = {}
    for well, reason in excluded_values.items():
        normalized = str(well).strip().upper()
        if not WELL_RE.fullmatch(normalized):
            raise ValueError(f"Invalid excluded well: {well!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"An exclusion reason is required for {normalized}.")
        if normalized in exclusions:
            raise ValueError(f"Duplicate excluded well: {normalized}")
        exclusions[normalized] = reason.strip()
    source = raw.get("target_source", {})
    if not isinstance(source, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in source.items()):
        raise ValueError("Target source must contain text provenance fields.")
    return {
        "schema_version": SCHEMA_VERSION,
        "nominal_targets": dict(sorted(targets.items())),
        "target_tolerance_percent": tolerance,
        "excluded_wells": dict(sorted(exclusions.items())),
        "target_source": dict(source),
    }


def load_settings(path: str | Path) -> dict:
    return _settings_document(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def _settings_document(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Saved analysis settings must be a JSON object.")
    return normalize_settings(value)


def save_settings(path: str | Path, settings: dict) -> None:
    """Replace only a valid analysis-settings document, with a concurrent-write check."""
    destination = Path(path)
    normalized = normalize_settings(settings)
    previous = destination.read_bytes() if destination.exists() else None
    if previous is not None:
        _settings_document(json.loads(previous.decode("utf-8-sig")))
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".analysis-settings-", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(normalized, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        current = destination.read_bytes() if destination.exists() else None
        if current != previous:
            raise ValueError("Analysis settings changed while saving; reload them before retrying.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def settings_from_design(path: str | Path) -> dict:
    source = Path(path)
    raw = source.read_bytes()
    design = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(design, dict) or not isinstance(design.get("factors"), list):
        raise ValueError("Experiment design must contain a factors list.")
    targets = {}
    for factor in design["factors"]:
        options = factor["options"]
        for option in options:
            units = str(option.get("units", ""))
            if units == "--":
                continue
            column = f"{option['name']}_{units}".strip("_")
            levels = list(option["targets"])
            if factor.get("kind") == "choice" and len(options) > 1 and 0 not in levels:
                levels.append(0)
            if column in targets and targets[column] != levels:
                raise ValueError(f"Conflicting intended levels for {column} in experiment design.")
            targets[column] = levels
    if not targets:
        raise ValueError("Experiment design contains no reagent concentration targets.")
    return normalize_settings({"nominal_targets": targets, "target_source": {
        "file": str(source.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
    }})


def expand_well_ranges(text: str) -> list[str]:
    wells = set()
    for item in re.split(r"[,;\s]+", text.strip()):
        if not item:
            continue
        ends = re.split(r"[:-]", item.upper())
        if len(ends) not in (1, 2) or any(not WELL_RE.fullmatch(end) for end in ends):
            raise ValueError(f"Invalid well or range: {item!r}. Use A1 or N1:P4.")
        first, last = ends[0], ends[-1]
        row_start, row_end = ord(first[0]), ord(last[0])
        col_start, col_end = int(first[1:]), int(last[1:])
        if row_start > row_end or col_start > col_end:
            raise ValueError(f"Reversed well range: {item!r}")
        wells.update(f"{chr(row)}{col}" for row in range(row_start, row_end + 1) for col in range(col_start, col_end + 1))
    return sorted(wells)


def apply_nominal_targets(dataframe: pd.DataFrame, condition_columns: list[str], settings: dict) -> tuple[pd.DataFrame, list[dict]]:
    result = dataframe.copy()
    targets = settings["nominal_targets"]
    unknown = set(targets) - set(condition_columns)
    if unknown:
        raise ValueError("Intended targets do not match concentration-key columns: " + ", ".join(sorted(unknown)))
    keyed = result["is_keyed"].astype(bool)
    summaries = []
    for column, levels in targets.items():
        mapping = {}
        for raw in result.loc[keyed, column].unique():
            try:
                value = float(raw)
            except (ValueError, TypeError):
                raise ValueError(f"Missing or nonnumeric calculated concentration for {column}: {raw!r}") from None
            if not math.isfinite(value):
                raise ValueError(f"Missing or non-finite calculated concentration for {column}.")
            matches = [target for target in levels if abs(value - target) <= max(abs(target) * settings["target_tolerance_percent"] / 100, 1e-9)]
            if len(matches) != 1:
                kind = "No intended level within tolerance" if not matches else "Ambiguous intended levels within tolerance"
                raise ValueError(f"{kind} for {column}={value:g}. Review the levels or tolerance.")
            mapping[raw] = matches[0]
        mapped = result.loc[keyed, column].map(mapping)
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(float)
        result.loc[keyed, column] = mapped.to_numpy(dtype=float)
        summaries.append({"reagent": column, "calculated_levels": sorted(float(v) for v in mapping),
                          "analysis_levels": sorted(set(mapping.values())),
                          "mapping": [{"calculated": float(v), "intended": t} for v, t in sorted(mapping.items())]})
    return result, summaries
