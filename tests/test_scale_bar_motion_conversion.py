from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

from tools.scale_bar_motion_conversion import (
    analyze_scale_bar_center_image,
    analyze_scale_bar_motion_directory,
    main,
)


def _write_motion_scale(
    path: Path,
    *,
    center=(260, 360),
    spacing_px=30,
    tick_count=17,
    rotation_deg=0.0,
    noise=False,
    asymmetric_long_ticks=False,
):
    cx, cy = center
    image = np.full((760, 520), 245, dtype=np.uint8)
    first_y = int(round(cy - spacing_px * (tick_count - 1) / 2.0))
    last_y = int(round(cy + spacing_px * (tick_count - 1) / 2.0))
    cv2.rectangle(image, (int(cx - 28), first_y - 20), (int(cx + 28), last_y + 20), 45, -1)
    for idx, y in enumerate(range(first_y, last_y + 1, spacing_px)):
        left = 22 if asymmetric_long_ticks and idx % 5 == 0 else 75
        right = 190 if asymmetric_long_ticks and idx % 5 == 0 else 75
        cv2.line(image, (int(cx - left), y), (int(cx + right), y), 0, 5)
    if noise:
        rng = np.random.default_rng(987)
        noisy = image.astype(np.int16) + rng.normal(0, 3, image.shape).astype(np.int16)
        image = np.clip(noisy, 0, 255).astype(np.uint8)
    if rotation_deg:
        h, w = image.shape[:2]
        matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), float(rotation_deg), 1.0)
        image = cv2.warpAffine(
            image,
            matrix,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=245,
        )
    cv2.imwrite(str(path), image)


def _motion_options(**overrides):
    options = {
        "min_main_peaks": 10,
        "min_spine_long": 400,
        "min_y_profile_height_px": 200,
        "max_spacing_cv_pct": 20.0,
    }
    options.update(overrides)
    return options


def _full_contour_rect_center(path: Path):
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _threshold, mask = cv2.threshold(blurred, 150, 255, cv2.THRESH_BINARY_INV)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(contour)
    return rect[0]


def _write_metadata(path: Path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_analyze_scale_bar_center_image_finds_synthetic_center_with_noise_and_rotation(tmp_path):
    image_path = tmp_path / "scale_bar_000001.png"
    _write_motion_scale(image_path, center=(260, 360), rotation_deg=0.6, noise=True)

    result = analyze_scale_bar_center_image(image_path, options=_motion_options())

    assert result["status"] == "ok"
    assert result["main_peak_count"] >= 15
    assert math.isclose(result["center_x"], 260, abs_tol=5)
    assert math.isclose(result["center_y"], 360, abs_tol=8)
    assert abs(result["spine_angle_from_vertical_deg"]) < 2.0


def test_asymmetric_long_ticks_do_not_pull_hybrid_x_center_like_full_contour(tmp_path):
    image_path = tmp_path / "scale_bar_000001.png"
    _write_motion_scale(image_path, center=(260, 360), asymmetric_long_ticks=True)

    full_cx, _full_cy = _full_contour_rect_center(image_path)
    result = analyze_scale_bar_center_image(image_path, options=_motion_options())

    assert result["status"] == "ok"
    assert abs(result["center_x"] - 260) < 8
    assert abs(full_cx - 260) > 25


def test_truncated_tick_sequence_is_rejected(tmp_path):
    image_path = tmp_path / "scale_bar_000001.png"
    _write_motion_scale(image_path, center=(260, 360), tick_count=5)

    result = analyze_scale_bar_center_image(image_path, options=_motion_options(min_main_peaks=10, min_spine_long=100))

    assert result["status"] == "rejected"
    assert "y_profile_too_short" in result["quality_flags"]


def test_directory_mode_joins_metadata_excludes_non_idle_and_reports_repeat_scatter(tmp_path):
    metadata_rows = []
    for index, (filename, x_pos, z_pos, center, idle) in enumerate(
            [
                ("scale_bar_000001.png", 1000, 5000, (260, 340), True),
                ("scale_bar_000002.png", 1000, 5000, (262, 342), True),
                ("scale_bar_000003.png", 1040, 5000, (360, 342), True),
                ("scale_bar_000004.png", 1000, 5060, (262, 520), True),
                ("scale_bar_000005.png", 1100, 5120, (360, 520), False),
        ],
        start=1,
    ):
        _write_motion_scale(tmp_path / filename, center=center)
        metadata_rows.append(
            {
                "index": index,
                "filename": filename,
                "X_position": x_pos,
                "Y_position": 0,
                "Z_position": z_pos,
                "commands_idle_at_frame": idle,
                "capture_context": "optics_scale_bar",
                "machine_position": {"X": x_pos, "Y": 0, "Z": z_pos},
                "controller_expected_position": {"X": x_pos, "Y": 0, "Z": z_pos},
            }
        )
    _write_metadata(tmp_path / "metadata.jsonl", metadata_rows)

    payload = analyze_scale_bar_motion_directory(tmp_path, options=_motion_options())

    assert payload["status"] == "ok"
    assert payload["summary"]["accepted_count"] == 5
    assert payload["motion_fit"]["fit_count"] == 4
    non_idle = next(row for row in payload["results"] if row["filename"] == "scale_bar_000005.png")
    assert non_idle["used_for_motion_fit"] is False
    assert payload["repeat_position_groups"]
    assert payload["repeat_position_groups"][0]["n"] == 2


def test_cli_writes_json_csv_and_debug_index(tmp_path):
    for index, (filename, x_pos, z_pos, center) in enumerate(
        [
            ("scale_bar_000001.png", 1000, 5000, (260, 340)),
            ("scale_bar_000002.png", 1040, 5000, (360, 342)),
            ("scale_bar_000003.png", 1000, 5060, (262, 520)),
        ],
        start=1,
    ):
        _write_motion_scale(tmp_path / filename, center=center)
    _write_metadata(
        tmp_path / "metadata.jsonl",
        [
            {
                "index": 1,
                "filename": "scale_bar_000001.png",
                "X_position": 1000,
                "Y_position": 0,
                "Z_position": 5000,
                "commands_idle_at_frame": True,
            },
            {
                "index": 2,
                "filename": "scale_bar_000002.png",
                "X_position": 1040,
                "Y_position": 0,
                "Z_position": 5000,
                "commands_idle_at_frame": True,
            },
            {
                "index": 3,
                "filename": "scale_bar_000003.png",
                "X_position": 1000,
                "Y_position": 0,
                "Z_position": 5060,
                "commands_idle_at_frame": True,
            },
        ],
    )
    output = tmp_path / "analysis.json"
    csv_path = tmp_path / "centers.csv"
    debug_dir = tmp_path / "debug"

    exit_code = main(
        [
            str(tmp_path),
            "--output",
            str(output),
            "--csv",
            str(csv_path),
            "--debug",
            "--debug-dir",
            str(debug_dir),
            "--min-main-peaks",
            "10",
            "--min-spine-long",
            "400",
            "--min-y-profile-height",
            "200",
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert csv_path.exists()
    assert (debug_dir / "index.html").exists()
    assert any(path.name.startswith("debug_") and path.suffix == ".png" for path in debug_dir.iterdir())
    assert (debug_dir / "summary_fit_observed_predicted_residuals.png").exists()
    assert (debug_dir / "summary_fit_residual_vectors.png").exists()


def test_directory_mode_can_limit_images_for_quick_debug_runs(tmp_path):
    metadata_rows = []
    for index in range(1, 7):
        filename = f"scale_bar_{index:06d}.png"
        _write_motion_scale(tmp_path / filename, center=(220 + index * 20, 340 + index * 10))
        metadata_rows.append(
            {
                "index": index,
                "filename": filename,
                "X_position": 1000 + index,
                "Y_position": 0,
                "Z_position": 5000 + index,
                "commands_idle_at_frame": True,
            }
        )
    _write_metadata(tmp_path / "metadata.jsonl", metadata_rows)

    payload = analyze_scale_bar_motion_directory(tmp_path, options=_motion_options(), image_limit=3)

    assert payload["summary"]["available_image_count"] == 6
    assert payload["summary"]["image_count"] == 3
    assert len(payload["results"]) == 3
