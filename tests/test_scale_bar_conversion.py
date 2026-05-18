from __future__ import annotations

import math

import cv2
import numpy as np

from tools.scale_bar_conversion import analyze_scale_bar_directory, analyze_scale_bar_image


def _write_scale_image(path, *, spacing_px=50, rotation_deg=0.0, noise=False):
    image = np.full((220, 720), 245, dtype=np.uint8)
    for idx, x in enumerate(range(80, 631, spacing_px)):
        height = 150 if idx % 5 == 0 else 95
        y0 = 35
        y1 = min(image.shape[0] - 20, y0 + height)
        cv2.line(image, (x, y0), (x, y1), 0, 4)
    cv2.line(image, (80, 36), (630, 36), 0, 2)
    if noise:
        rng = np.random.default_rng(123)
        noisy = image.astype(np.int16) + rng.normal(0, 4, image.shape).astype(np.int16)
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


def test_analyze_scale_bar_image_handles_rotation_and_noise(tmp_path):
    path = tmp_path / "scale.png"
    _write_scale_image(path, spacing_px=50, rotation_deg=1.5, noise=True)

    result = analyze_scale_bar_image(path, division_um=10.0)

    assert result["status"] == "ok"
    assert result["spacing_count"] >= 5
    assert math.isclose(result["um_per_pixel"], 0.2, rel_tol=0.03)


def test_analyze_scale_bar_directory_skips_rejected_frames(tmp_path):
    good = tmp_path / "good.png"
    rejected = tmp_path / "reject.png"
    _write_scale_image(good, spacing_px=40)
    _write_scale_image(rejected, spacing_px=80)

    payload = analyze_scale_bar_directory(tmp_path, division_um=10.0, rejected_filenames={rejected.name})

    assert payload["status"] == "ok"
    summary = payload["summary"]
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 1
    assert math.isclose(summary["median_um_per_pixel"], 0.25, rel_tol=0.03)
