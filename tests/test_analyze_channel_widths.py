from __future__ import annotations

import cv2
import numpy as np

from tools import analyze_channel_widths as mod


def _curved_channel_image(
    *, width_px: float = 100.0, roughness_px: float = 0.0
) -> np.ndarray:
    height, width = 480, 640
    x = np.linspace(50.0, 590.0, 700)
    phase = (x - 50.0) / 540.0 * np.pi
    center_y = 235.0 + (55.0 * np.sin(phase - (np.pi / 2.0)))
    slope = (55.0 * np.pi / 540.0) * np.cos(phase - (np.pi / 2.0))
    normal_x = -slope / np.sqrt(1.0 + (slope * slope))
    normal_y = 1.0 / np.sqrt(1.0 + (slope * slope))
    half = width_px / 2.0
    first_distance = half + roughness_px * np.sin((2.0 * np.pi * x) / 31.0)
    second_distance = half + roughness_px * np.cos((2.0 * np.pi * x) / 37.0)
    first = np.column_stack(
        (x - (first_distance * normal_x), center_y - (first_distance * normal_y))
    )
    second = np.column_stack(
        (x + (second_distance * normal_x), center_y + (second_distance * normal_y))
    )
    polygon = np.vstack((first, second[::-1]))

    green = np.full((height, width), 18, dtype=np.uint8)
    cv2.fillPoly(green, [np.rint(polygon).astype(np.int32)], 220)
    green = cv2.GaussianBlur(green, (0, 0), 1.3)
    image = cv2.cvtColor(green, cv2.COLOR_GRAY2BGR)
    image[:, :, 2] = np.clip(image[:, :, 2].astype(np.int16) + 5, 0, 255).astype(np.uint8)
    return image


def test_curved_channel_uses_local_perpendicular_widths():
    expected_width = 100.0
    analysis = mod.analyze_image(
        _curved_channel_image(width_px=expected_width),
        micrometers_per_pixel=1.0,
        end_trim_fraction=0.20,
        sample_spacing_px=8.0,
    )

    assert len(analysis.samples) >= 35
    assert abs(analysis.median_width_px - expected_width) < 2.0
    assert analysis.width_iqr_px < 2.0
    for sample in analysis.samples:
        assert abs(float(np.dot(sample.tangent_xy, sample.normal_xy))) < 1e-6
        for wall in (sample.first_wall_xy, sample.second_wall_xy):
            assert 2.0 <= wall[0] <= 637.0
            assert 2.0 <= wall[1] <= 477.0


def test_rendered_stages_show_four_full_panels():
    analysis = mod.analyze_image(
        _curved_channel_image(),
        micrometers_per_pixel=0.771,
    )

    rendered = mod.render_stages(analysis, image_name="synthetic.png")

    assert rendered.shape == (900, 1600, 3)
    assert rendered.dtype == np.uint8
    assert int(rendered.max()) > 0


def test_aperture_clipping_is_excluded_from_wall_models():
    image = _curved_channel_image(width_px=100.0)
    center_x, center_y, aperture_radius = 320.0, 240.0, 255.0
    yy, xx = np.indices(image.shape[:2])
    image[np.hypot(xx - center_x, yy - center_y) > aperture_radius] = 2

    analysis = mod.analyze_image(
        image,
        micrometers_per_pixel=1.0,
        aperture_circle=(center_x, center_y, aperture_radius),
        aperture_margin_px=35.0,
        end_trim_fraction=0.10,
        sample_spacing_px=8.0,
    )

    assert len(analysis.samples) >= 25
    assert abs(analysis.median_width_px - 100.0) < 3.0
    for sample in analysis.samples:
        for wall in (sample.first_wall_xy, sample.second_wall_xy):
            assert np.hypot(wall[0] - center_x, wall[1] - center_y) <= 220.5


def test_wall_residual_metric_increases_for_rough_walls():
    smooth = mod.analyze_image(
        _curved_channel_image(roughness_px=0.0), micrometers_per_pixel=1.0
    )
    rough = mod.analyze_image(
        _curved_channel_image(roughness_px=7.0), micrometers_per_pixel=1.0
    )

    assert smooth.wall_p95_um < 3.0
    assert rough.wall_p95_um > smooth.wall_p95_um + 5.0
    assert rough.wall_p95_um > 6.5
    assert rough.normal_angle_bend_p95_deg < 0.10


def test_repeated_inner_cutoff_sets_vignette_margin(tmp_path):
    size = 640
    center = (320, 320)
    outer_radius = 300.0
    inner_cutoff = 240.0
    yy, xx = np.indices((size, size))
    paths = []
    for index, angle in enumerate((0.0, 25.0, 55.0, 90.0)):
        image = np.full((size, size, 3), 12, dtype=np.uint8)
        rectangle = ((320.0, 320.0), (580.0, 110.0), angle)
        box = np.rint(cv2.boxPoints(rectangle)).astype(np.int32)
        cv2.fillPoly(image, [box], (220, 220, 220))
        image[np.hypot(xx - center[0], yy - center[1]) > inner_cutoff] = 0
        path = tmp_path / f"cutoff_{index}.png"
        cv2.imwrite(str(path), image)
        paths.append(path)

    margin = mod.estimate_aperture_margin(
        paths, (float(center[0]), float(center[1]), outer_radius)
    )

    assert abs(margin - (outer_radius - inner_cutoff + 5.0)) <= 5.0
