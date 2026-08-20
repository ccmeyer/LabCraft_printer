"""Export sanitized coordinate-delta characterization from explicit histories.

The tool is read-only with respect to every input. It omits coordinates,
machine/operator identifiers, reasons, source paths, and experiment content.
It does not select or modify safety thresholds.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def _event_paths(path: Path):
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.json"))


def collect_rows(paths, cohort_label):
    rows = []
    for supplied in paths:
        for path in _event_paths(Path(supplied).expanduser().resolve(strict=True)):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or event.get("schema_name") != "labcraft.configuration_event":
                continue
            workflow = str(event.get("workflow", "unknown"))
            verified_or_restored = event.get("event_type") in {"verification", "restore"}
            for entry in event.get("changes", []):
                guard = entry.get("guard_assessment") if isinstance(entry, dict) else None
                if not isinstance(guard, dict):
                    continue
                target_class = str(guard.get("target_class", "unknown"))
                hardware_profile = str(guard.get("hardware_profile", "unknown"))
                for change in guard.get("changes", []):
                    absolute = change.get("absolute_delta", {}) if isinstance(change, dict) else {}
                    target_key = str(change.get("target_key", "")) if isinstance(change, dict) else ""
                    category = target_class
                    if target_class == "camera" or target_key.casefold() == "camera":
                        category = "camera"
                    elif target_class == "rack" or target_key.casefold().startswith("rack_position_"):
                        category = "rack_anchor"
                    elif target_class == "plate":
                        category = "plate_corner"
                    elif target_class in {"reserved_location", "new_target"}:
                        category = target_class
                    else:
                        category = "generic_location"
                    for axis in ("X", "Y", "Z"):
                        delta = absolute.get(axis)
                        if type(delta) is not int:
                            continue
                        rows.append(
                            {
                                "cohort_label": cohort_label,
                                "hardware_profile": hardware_profile,
                                "target_class": target_class,
                                "target_category": category,
                                "axis": axis,
                                "absolute_delta_steps": delta,
                                "workflow": workflow,
                                "later_verified_or_restored": bool(verified_or_restored),
                            }
                        )
    return rows


def build_report(rows, cohort_label):
    groups = Counter(
        (row["hardware_profile"], row["target_category"], row["axis"])
        for row in rows
    )
    return {
        "schema_name": "labcraft.configuration_change_characterization",
        "schema_version": 1,
        "cohort_label": cohort_label,
        "notice": "Descriptive evidence only; this report does not select safety thresholds.",
        "sample_count": len(rows),
        "groups": [
            {
                "hardware_profile": key[0],
                "target_category": key[1],
                "axis": key[2],
                "sample_count": count,
                "minimum_steps": min(
                    row["absolute_delta_steps"] for row in rows
                    if (row["hardware_profile"], row["target_category"], row["axis"]) == key
                ),
                "maximum_steps": max(
                    row["absolute_delta_steps"] for row in rows
                    if (row["hardware_profile"], row["target_category"], row["axis"]) == key
                ),
            }
            for key, count in sorted(groups.items())
        ],
        "samples": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="append", required=True, help="Explicit event file or history directory; repeatable")
    parser.add_argument("--cohort-label", required=True, help="Caller-supplied non-identifying cohort label")
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args(argv)
    rows = collect_rows(args.history, args.cohort_label)
    report = build_report(rows, args.cohort_label)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_csv is not None:
        fields = list(rows[0]) if rows else [
            "cohort_label", "hardware_profile", "target_class", "target_category",
            "axis", "absolute_delta_steps", "workflow", "later_verified_or_restored",
        ]
        with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote {len(rows)} sanitized axis samples to {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
