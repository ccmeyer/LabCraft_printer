from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

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


def _assert_integer_move(actual, expected):
    assert actual == expected
    assert all(type(value) is int for value in actual)


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


def test_explicit_optics_path_overrides_checkout_local_class_default(
    tmp_path, monkeypatch
):
    checkout_local = tmp_path / "checkout" / "local" / "optics.json"
    canonical = tmp_path / "external" / "machine" / "calibration" / "optics.json"
    monkeypatch.setattr(DropletCameraModel, "OPTICS_CONFIG_PATH", checkout_local)
    cam = DropletCameraModel(
        str(_step_calibration_path(tmp_path)),
        optics_config_path=canonical,
    )

    cam.set_um_per_pixel(2.75, source="canonical_test")

    assert cam.optics_config_path() == canonical
    assert json.loads(canonical.read_text(encoding="utf-8"))["um_per_pixel"] == 2.75
    assert not checkout_local.exists()


def test_droplet_camera_motion_conversion_falls_back_to_preset_when_missing_or_invalid(tmp_path, monkeypatch):
    config_path = tmp_path / "optics.json"
    config_path.write_text(
        json.dumps(
            {
                "um_per_pixel": 2.0,
                "motion_conversion": {
                    "intercept_cx": 1.0,
                    "intercept_cy": 2.0,
                    "A": [[1.0, 0.0], [0.0, 0.0]],
                },
            }
        ),
        encoding="utf-8",
    )

    cam = _make_camera(tmp_path, monkeypatch, config_path=config_path)

    assert cam.get_um_per_pixel() == 2.0
    assert cam.get_motion_conversion_config() == {}
    assert cam.get_step_conversion_source().startswith("preset:")
    _assert_integer_move(cam.compute_stage_move(5, 7), (5, 0, 7))


def test_droplet_camera_valid_local_motion_conversion_overrides_preset(tmp_path, monkeypatch):
    config_path = tmp_path / "optics.json"
    config_path.write_text(
        json.dumps(
            {
                "um_per_pixel": 2.0,
                "source": "unit_test",
                "motion_conversion": {
                    "intercept_cx": 10.0,
                    "intercept_cy": 20.0,
                    "A": [[2.0, 0.0], [0.0, 4.0]],
                    "source": "unit_motion",
                },
            }
        ),
        encoding="utf-8",
    )

    cam = _make_camera(tmp_path, monkeypatch, config_path=config_path)

    assert cam.get_step_conversion_source() == "unit_motion"
    assert cam.get_motion_conversion_config()["intercept_cx"] == 10.0
    _assert_integer_move(cam.compute_stage_move(8, 12), (4, 0, 3))


def test_droplet_camera_apply_combined_optics_payload_persists_motion_conversion(tmp_path, monkeypatch):
    config_path = tmp_path / "optics.json"
    cam = _make_camera(tmp_path, monkeypatch, config_path=config_path)
    payload = {
        "summary": {
            "status": "ok",
            "apply_ready": True,
            "motion_debug_index_path": str(tmp_path / "debug" / "index.html"),
        },
        "scale_bar_analysis": {
            "summary": {
                "status": "ok",
                "median_um_per_pixel": 2.5,
                "mean_um_per_pixel": 2.51,
                "std_um_per_pixel": 0.01,
                "cv_pct": 0.4,
                "division_um": 10.0,
                "accepted_count": 25,
                "run_directory": str(tmp_path / "run"),
            }
        },
        "motion_analysis": {
            "summary": {
                "status": "ok",
                "run_directory": str(tmp_path / "run"),
                "accepted_count": 25,
                "rejected_count": 1,
                "error_count": 0,
                "repeat_position_group_count": 4,
            },
            "motion_fit": {
                "status": "ok",
                "fit_count": 24,
                "intercept": [100.0, 200.0],
                "matrix": [[2.0, 0.0], [0.0, 4.0]],
                "inverse_matrix": [[0.5, 0.0], [0.0, 0.25]],
                "determinant": 8.0,
                "rmse_x_px": 3.0,
                "rmse_y_px": 2.0,
                "rmse_2d_px": 4.0,
                "median_2d_residual_px": 3.0,
                "p95_2d_residual_px": 8.0,
                "max_2d_residual_px": 9.0,
            },
        },
    }

    written = cam.apply_optics_calibration(payload)
    reloaded = _make_camera(tmp_path, monkeypatch, config_path=config_path)

    assert written["um_per_pixel"] == 2.5
    assert written["motion_conversion"]["A"] == [[2.0, 0.0], [0.0, 4.0]]
    assert reloaded.get_um_per_pixel() == 2.5
    assert reloaded.get_step_conversion_source() == "scale_bar_motion_calibration"
    _assert_integer_move(reloaded.compute_stage_move(8, 12), (4, 0, 3))


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


def test_droplet_camera_stop_saving_discards_pending_jobs_after_timeout(tmp_path, monkeypatch):
    cam = _make_camera(tmp_path, monkeypatch)
    cam._saving_enabled = True
    cam._save_dir = str(tmp_path / "captures")
    cam._save_queue.put_nowait(("frame-a.png", np.zeros((2, 2, 3), dtype=np.uint8), {}))
    cam._save_queue.put_nowait(("frame-b.png", np.zeros((2, 2, 3), dtype=np.uint8), {}))

    cam.stop_saving(drain_timeout_s=0.01)

    assert cam._saving_enabled is False
    assert cam._save_queue.empty()
    assert cam._save_queue_pending_count() == 0


@pytest.mark.parametrize(
    ('delta', 'expected'),
    [
        ((5, 7), (5, 0, 7)),
        ((-5, -7), (-5, 0, -7)),
        ((0, 0), (0, 0, 0)),
        ((2.5, 3.5), (2, 0, 4)),
        ((-2.5, -3.5), (-2, 0, -4)),
        ((2.49, -3.51), (2, 0, -4)),
    ],
)
def test_stage_move_returns_integers_and_preserves_rounding(tmp_path, monkeypatch, delta, expected):
    cam = _make_camera(tmp_path, monkeypatch)

    _assert_integer_move(cam.compute_stage_move(*delta), expected)


def test_stage_move_preserves_coupled_matrix_conversion(tmp_path, monkeypatch):
    cam = _make_camera(tmp_path, monkeypatch)
    cam.A_inv = np.array([[0.5, -0.125], [0.0, 0.25]])

    _assert_integer_move(cam.compute_stage_move(10, 12), (4, 0, 3))


@pytest.mark.parametrize(
    ('fractions', 'expected'),
    [
        ((0.1, 0.1), (10, 0, 8)),
        ((-0.1, -0.1), (-10, 0, -8)),
        ((0, 0), (0, 0, 0)),
    ],
)
def test_camera_position_helpers_preserve_integer_coordinates(
    tmp_path, monkeypatch, fractions, expected
):
    cam = _make_camera(tmp_path, monkeypatch)
    cam.image_width, cam.image_height = 100, 80
    dx, _, dz = expected

    _assert_integer_move(cam.compute_move_by_fraction(*fractions), expected)
    _assert_integer_move(cam.calculate_move_to_target((20, 30), (20 + dx, 30 + dz)), expected)
    _assert_integer_move(cam.calculate_move_to_top_center((50 - dx, 150 - dz)), expected)

    origin = {'X': 10000, 'Y': 10000, 'Z': 10000}
    center_x, center_y = cam.get_center_in_pixels()
    target = cam.convert_pixel_position_to_motor_steps((center_x + dx, center_y + dz), origin)

    assert target == {'X': 10000 + dx, 'Y': 10000, 'Z': 10000 + dz}
    assert all(type(value) is int for value in target.values())
    assert origin == {'X': 10000, 'Y': 10000, 'Z': 10000}
