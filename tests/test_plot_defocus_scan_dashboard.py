from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import cv2
import pytest


TOOLS_DIRECTORY = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIRECTORY))
MODULE_PATH = TOOLS_DIRECTORY / "plot_defocus_scan_dashboard.py"
SPEC = importlib.util.spec_from_file_location("plot_defocus_scan_dashboard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


def _write_summary(path: Path) -> None:
    rows = []
    widths = {
        0: {1: [10.0, 12.0], 2: [20.0, 22.0]},
        2: {1: [30.0, 32.0], 2: [40.0, 42.0]},
        4: {1: [50.0, 52.0], 2: [60.0, 62.0]},
    }
    for defocus, channels in widths.items():
        for channel, image_widths in channels.items():
            for image_replicate, width in enumerate(image_widths, start=1):
                rows.append(
                    {
                        "group": f"{defocus}defocus",
                        "image": f"{defocus}mm_{channel}_{image_replicate}.png",
                        "median_width_um": width,
                        "width_iqr_um": 2.0,
                        "wall_rms_um": 1.0,
                        "wall_p95_um": defocus + 1.0,
                        "sample_count": 10,
                        "annotated_image": "annotation.png",
                    }
                )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_parse_image_name_rejects_unstructured_names() -> None:
    assert dashboard.parse_image_name("4mm_2_5.png") == (4.0, 2, 5)
    with pytest.raises(ValueError, match="Expected image name"):
        dashboard.parse_image_name("channel.png")


def test_defocus_statistics_and_outputs(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.csv"
    output_directory = tmp_path / "dashboard"
    _write_summary(summary_path)

    defocus_rows = dashboard.run(summary_path, output_directory)
    defocus_zero = next(row for row in defocus_rows if row["defocus_mm"] == 0.0)

    assert defocus_zero["mean_width_um"] == pytest.approx(16.0)
    assert defocus_zero["observed_channel_mean_variance_um2"] == pytest.approx(50.0)
    assert defocus_zero["pooled_within_channel_image_variance_um2"] == pytest.approx(2.0)
    assert defocus_zero["estimated_between_channel_variance_component_um2"] == pytest.approx(
        49.0
    )
    assert defocus_zero["mean_wall_roughness_p95_um"] == pytest.approx(1.0)

    for filename in (
        "image_metrics.csv",
        "channel_metrics.csv",
        "location_replicate_metrics.csv",
        "defocus_metrics.csv",
        "defocus_comparisons.csv",
    ):
        assert (output_directory / filename).is_file()
    for filename in ("defocus_dashboard.png", "defocus_replicate_heatmap.png"):
        image = cv2.imread(str(output_directory / filename))
        assert image is not None
        assert image.shape[0] > 1000
        assert image.shape[1] > 1000
