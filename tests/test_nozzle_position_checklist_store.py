import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzlePositionChecklistStore


def _manifest_path():
    return (
        Path(__file__).resolve().parents[1]
        / "FreeRTOS-interface"
        / "CalibrationClasses"
        / "test_images"
        / "NozzlePositionCalibrationProcess"
        / "checklist_manifest.v1.json"
    )


def _dummy_model_with_unknown_reagent():
    return SimpleNamespace(
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
    )


def test_store_writes_capture_records_with_selected_label_and_unknown_reagent(tmp_path):
    store = NozzlePositionChecklistStore(
        _dummy_model_with_unknown_reagent(),
        base_dir=str(tmp_path / "NozzlePositionCalibrationProcess"),
        manifest_path=str(_manifest_path()),
    )
    store.begin_session(session_id="session_test")

    row_key = "NP_OK_CENTERED:default"
    frame = np.zeros((32, 40, 3), dtype=np.uint8)
    rec = store.capture_for_row(
        row_key,
        "background",
        frame,
        selected_label="Centered nozzle / Centered detection",
        machine_state={"X": 1, "Y": 2, "Z": 3},
        camera_settings={"flash_delay_us": 5000},
        reagent_name=store.resolve_reagent_name(),
    )

    assert rec["selected_label"] == "Centered nozzle / Centered detection"
    assert rec["reagent_name"] == "unknown"
    img_path = Path(store.session_dir) / Path(rec["image_relpath"])
    assert img_path.exists()

    lines = Path(store.records_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["record_id"] == rec["record_id"]
    assert payload["capture_role"] == "background"


def test_store_completion_counts_respect_reject_last(tmp_path):
    store = NozzlePositionChecklistStore(
        _dummy_model_with_unknown_reagent(),
        base_dir=str(tmp_path / "NozzlePositionCalibrationProcess"),
        manifest_path=str(_manifest_path()),
    )
    store.begin_session(session_id="session_counts")

    row_key = "NP_OK_CENTERED:default"
    frame = np.zeros((24, 24, 3), dtype=np.uint8)

    store.capture_for_row(row_key, "background", frame, selected_label="sel")
    for _ in range(3):
        store.capture_for_row(row_key, "droplet", frame, selected_label="sel")

    st = store.get_row_status(row_key)
    assert st["accepted_background"] == 1
    assert st["accepted_droplet"] == 3
    assert st["complete"] is True

    evt = store.reject_last_capture(reason="wrong label")
    assert evt is not None
    st2 = store.get_row_status(row_key)
    assert st2["accepted_droplet"] == 2
    assert st2["complete"] is False


def test_store_pair_metadata_links_droplet_to_background(tmp_path):
    store = NozzlePositionChecklistStore(
        _dummy_model_with_unknown_reagent(),
        base_dir=str(tmp_path / "NozzlePositionCalibrationProcess"),
        manifest_path=str(_manifest_path()),
    )
    store.begin_session(session_id="session_pairing")

    row_key = "NP_OK_CENTERED:default"
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    pair_id = "pair-test-001"

    bg = store.capture_for_row(
        row_key,
        "background",
        frame,
        selected_label="sel",
        pair_id=pair_id,
        pair_role="background",
        pair_order=1,
        pair_capture_mode="background_then_droplet",
    )
    dr = store.capture_for_row(
        row_key,
        "droplet",
        frame,
        selected_label="sel",
        pair_id=pair_id,
        pair_role="droplet",
        pair_order=2,
        pair_capture_mode="background_then_droplet",
        subtract_background_record_id=bg["record_id"],
        subtract_background_image_relpath=bg["image_relpath"],
    )

    lines = Path(store.records_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payload_bg = json.loads(lines[0])
    payload_dr = json.loads(lines[1])

    assert payload_bg["pair_id"] == pair_id
    assert payload_bg["pair_role"] == "background"
    assert payload_bg["pair_order"] == 1

    assert payload_dr["pair_id"] == pair_id
    assert payload_dr["pair_role"] == "droplet"
    assert payload_dr["pair_order"] == 2
    assert payload_dr["subtract_background_record_id"] == bg["record_id"]
    assert payload_dr["subtract_background_image_relpath"] == bg["image_relpath"]
    assert dr["subtract_background_record_id"] == bg["record_id"]
