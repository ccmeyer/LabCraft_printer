import copy
import json
from pathlib import Path

from PySide6.QtWidgets import QLabel

from ConfigurationSafetyPolicy import ConfigurationChangeGuard, load_configuration_change_policy, parse_safety_bounds
from View import ConfigurationChangePreviewDialog, ControlledCalibrationPromotionDialog


def _assessment():
    preset = Path(__file__).resolve().parents[1] / "FreeRTOS-interface" / "Presets"
    docs = {
        name: json.loads((preset / name).read_text(encoding="utf-8"))
        for name in ("Locations.json", "Plates.json", "Settings.json", "Obstacles.json")
    }
    proposed = copy.deepcopy(docs["Locations.json"])
    proposed["camera"]["Y"] += 9000
    guard = ConfigurationChangeGuard(load_configuration_change_policy(), parse_safety_bounds(docs["Obstacles.json"]))
    return guard.assess(
        before_documents=docs,
        proposed_documents={"Locations.json": proposed},
        workflow="named_location_modify",
        target_keys=("camera",),
        hardware_profile="current",
    )


def test_preview_requires_checkbox_and_returns_proposal_bound_confirmation(qapp, monkeypatch):
    assessment = _assessment()
    dialog = ConfigurationChangePreviewDialog(assessment)
    warnings = []
    monkeypatch.setattr("View.QMessageBox.warning", lambda *args: warnings.append(args))
    dialog.operator_edit.setText("Alice")
    dialog.reason_edit.setText("Camera recalibration")
    dialog._finish()
    assert dialog.outcome == "cancelled"
    assert warnings

    dialog.acknowledge.setChecked(True)
    dialog._finish()
    assert dialog.outcome == "accepted"
    result = dialog.result_payload()
    assert result["confirmation"] == {
        "proposal_sha256": assessment["proposal_sha256"],
        "acknowledged": True,
        "acknowledgement_version": assessment["confirmation_version"],
    }


def test_restore_preview_identifies_verified_backup_and_removed_target(qapp):
    assessment = _assessment()
    assessment["workflow"] = "configuration_restore"
    assessment["changes"] = [
        {
            "target_key": "qualification-unverified",
            "before": {"X": 1, "Y": 2, "Z": 3},
            "proposed": None,
            "signed_delta": {"X": None, "Y": None, "Z": None},
            "absolute_delta": {"X": None, "Y": None, "Z": None},
        }
    ]
    assessment["preconditions"] = {
        "captures": [],
        "restore": {
            "transaction_id": "00000000-0000-0000-0000-000000000123",
            "backup_manifest": {"raw_sha256": "a" * 64},
        },
    }

    dialog = ConfigurationChangePreviewDialog(assessment)

    assert dialog.table.item(0, 2).text() == "removed by exact backup"
    assert dialog.table.item(0, 6).text() == "removed"
    assert dialog.action_button.text() == "Restore Exact Backup and Revoke Changed Targets"
    labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Verified backup transaction 00000000-0000-0000-0000-000000000123" in labels


def test_controlled_calibration_promotion_uses_review_checkbox_without_json(qapp, monkeypatch):
    candidate = {
        "target_key": "plate:plate-a",
        "workflow": "plate_calibration",
        "source_event_path": "history/configuration_events/0001-source.json",
        "source_created_at_utc": "2026-08-23T00:00:00Z",
        "integrity": "verified",
        "proposal_sha256": "a" * 64,
        "captures": [
            {
                "target_key": "top_left",
                "captured_position": {"X": 1, "Y": 2, "Z": 3},
                "expected_position": {"X": 1, "Y": 2, "Z": 3},
                "ready": True,
                "reason_codes": [],
            }
        ],
        "deltas": [],
    }
    dialog = ControlledCalibrationPromotionDialog(candidate)
    warnings = []
    monkeypatch.setattr("View.QMessageBox.warning", lambda *args: warnings.append(args))
    dialog.operator_edit.setText("Alice")
    dialog.reason_edit.setText("Review existing plate calibration")

    dialog._accept_if_complete()
    assert warnings
    assert dialog.result() == 0

    dialog.acknowledge.setChecked(True)
    dialog._accept_if_complete()
    assert dialog.result() == 1
    assert dialog.review_result() == {
        "operator": "Alice",
        "reason": "Review existing plate calibration",
    }
