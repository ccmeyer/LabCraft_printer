import copy
import json
from pathlib import Path

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
