import copy
import json
from pathlib import Path

from PySide6.QtWidgets import QLabel

from ConfigurationSafetyPolicy import ConfigurationChangeGuard, load_configuration_change_policy, parse_safety_bounds
from View import ConfigurationChangePreviewDialog


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


def test_preview_requires_exact_phrase_and_returns_proposal_bound_confirmation(qapp, monkeypatch):
    assessment = _assessment()
    dialog = ConfigurationChangePreviewDialog(assessment)
    warnings = []
    monkeypatch.setattr("View.QMessageBox.warning", lambda *args: warnings.append(args))
    dialog.operator_edit.setText("Alice")
    dialog.reason_edit.setText("Camera recalibration")
    dialog.acknowledge.setChecked(True)
    dialog.phrase_edit.setText("wrong")

    dialog._finish()
    assert dialog.outcome == "cancelled"
    assert warnings

    dialog.phrase_edit.setText(assessment["required_confirmation_phrase"])
    dialog._finish()
    assert dialog.outcome == "accepted"


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
