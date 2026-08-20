import json

from tools.export_configuration_change_characterization import build_report, collect_rows


def test_characterization_omits_sensitive_and_absolute_coordinate_fields(tmp_path):
    event = {
        "schema_name": "labcraft.configuration_event",
        "event_type": "change",
        "workflow": "named_location_modify",
        "machine_id": "SECRET-MACHINE",
        "actor": {"operator": "SECRET OPERATOR"},
        "reason": "SECRET REASON",
        "changes": [{
            "guard_assessment": {
                "target_class": "camera",
                "hardware_profile": "current",
                "changes": [{
                    "target_key": "camera",
                    "before": {"X": 1, "Y": 2, "Z": 3},
                    "proposed": {"X": 4, "Y": 5, "Z": 6},
                    "absolute_delta": {"X": 3, "Y": 3, "Z": 3},
                }],
            }
        }],
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")

    rows = collect_rows([path], "rc2-lab")
    report = build_report(rows, "rc2-lab")
    serialized = json.dumps(report)

    assert len(rows) == 3
    assert set(rows[0]) == {
        "cohort_label", "hardware_profile", "target_class", "target_category",
        "axis", "absolute_delta_steps", "workflow", "later_verified_or_restored",
    }
    assert "SECRET" not in serialized
    assert '"before"' not in serialized
    assert report["notice"].startswith("Descriptive evidence only")
