from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

from CalibrationClasses.Model import DropletCameraModel


def _step_calibration_path(tmp_path):
    path = tmp_path / "steps.json"
    path.write_text(
        json.dumps(
            {
                "intercept_cx": 0,
                "intercept_cy": 0,
                "A": [[1.0, 0.0], [0.0, 1.0]],
            }
        ),
        encoding="utf-8",
    )
    return path


def _make_camera(tmp_path, monkeypatch, config_path=None):
    if config_path is None:
        config_path = tmp_path / "droplet_imager_optics.json"
    monkeypatch.setattr(DropletCameraModel, "OPTICS_CONFIG_PATH", config_path)
    return DropletCameraModel(str(_step_calibration_path(tmp_path)))


def test_droplet_camera_optics_config_falls_back_and_persists(tmp_path, monkeypatch):
    config_path = tmp_path / "optics.json"
    cam = _make_camera(tmp_path, monkeypatch, config_path=config_path)

    assert math.isclose(cam.get_um_per_pixel(), DropletCameraModel.DEFAULT_UM_PER_PIXEL)
    assert cam.get_um_per_pixel_source() == "default"

    cam.set_um_per_pixel(
        2.345,
        source="unit_test",
        division_um=10.0,
        accepted_image_count=7,
        mean_um_per_pixel=2.346,
        median_um_per_pixel=2.345,
        std_um_per_pixel=0.01,
        cv_pct=0.4,
        run_directory=str(tmp_path / "run"),
    )

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["um_per_pixel"] == 2.345
    assert data["accepted_image_count"] == 7

    reloaded = _make_camera(tmp_path, monkeypatch, config_path=config_path)
    assert reloaded.get_um_per_pixel() == 2.345
    assert reloaded.get_um_per_pixel_source() == "unit_test"


def test_droplet_camera_ignores_invalid_optics_config(tmp_path, monkeypatch):
    config_path = tmp_path / "optics.json"
    config_path.write_text(json.dumps({"um_per_pixel": -1}), encoding="utf-8")

    cam = _make_camera(tmp_path, monkeypatch, config_path=config_path)

    assert math.isclose(cam.get_um_per_pixel(), DropletCameraModel.DEFAULT_UM_PER_PIXEL)
    assert cam.get_um_per_pixel_source() == "default"


def test_characterize_droplet_uses_configured_factor_unless_explicit(tmp_path, monkeypatch):
    cam = _make_camera(tmp_path, monkeypatch)
    cam.set_um_per_pixel(2.0, source="unit_test")
    background = np.full((180, 180, 3), 255, dtype=np.uint8)
    image = background.copy()
    cv2.ellipse(image, (90, 90), (24, 20), 0, 0, 360, (0, 0, 0), -1)

    result, _annotated, details = cam.characterize_droplet(image, background, return_details=True)
    explicit, _annotated2, explicit_details = cam.characterize_droplet(
        image,
        background,
        um_per_pixel=3.0,
        return_details=True,
    )

    assert result is not None
    assert details["status"] == "ok"
    assert details["um_per_pixel"] == 2.0
    assert result["um_per_pixel"] == 2.0
    assert explicit_details["um_per_pixel"] == 3.0
    assert explicit["um_per_pixel"] == 3.0
    assert explicit["volume"] > result["volume"]


def test_droplet_camera_update_image_writes_save_metadata(tmp_path, monkeypatch):
    cam = _make_camera(tmp_path, monkeypatch)
    run_dir = cam.start_saving(root_dir=str(tmp_path / "captures"), prefix="scale_bar", image_ext="png")
    frame = np.full((16, 20, 3), 128, dtype=np.uint8)

    cam.update_image(
        frame,
        capture_info={"cap_id": 42, "reason": "threshold"},
        save_metadata={
            "X_position": 111,
            "Y_position": 222,
            "Z_position": 333,
            "position_source": "controller_expected_position",
            "capture_context": "optics_scale_bar",
            "commands_idle_at_frame": True,
            "machine_position": {"X": 110, "Y": 220, "Z": 330},
            "controller_expected_position": {"X": 111, "Y": 222, "Z": 333},
            "capture_info": {"should": "not overwrite"},
            "index": 999,
        },
    )
    cam.stop_saving()

    metadata_path = Path(run_dir) / "metadata.jsonl"
    row = json.loads(metadata_path.read_text(encoding="utf-8").splitlines()[0])

    assert row["index"] == 1
    assert row["filename"] == "scale_bar_000001.png"
    assert row["capture_info"] == {"cap_id": 42, "reason": "threshold"}
    assert row["X_position"] == 111
    assert row["Y_position"] == 222
    assert row["Z_position"] == 333
    assert row["position_source"] == "controller_expected_position"
    assert row["capture_context"] == "optics_scale_bar"
    assert row["commands_idle_at_frame"] is True
    assert row["machine_position"] == {"X": 110, "Y": 220, "Z": 330}
    assert row["controller_expected_position"] == {"X": 111, "Y": 222, "Z": 333}
