from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import cv2
import pytest


TOOLS_DIRECTORY = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIRECTORY))
MODULE_PATH = TOOLS_DIRECTORY / "plot_channel_replicate_dashboard.py"
SPEC = importlib.util.spec_from_file_location("plot_channel_replicate_dashboard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


def _write_summary(path: Path) -> None:
    rows = []
    for channel in range(1, 11):
        for image_replicate in range(1, 6):
            rows.append(
                {
                    "group": "zero_defocus",
                    "image": f"0mm_{channel}_{image_replicate}.png",
                    "median_width_um": 100.0 + channel + 2.0 * image_replicate,
                    "width_iqr_um": 2.0,
                    "wall_rms_um": 1.0,
                    "wall_p95_um": 3.0 + 0.1 * channel,
                    "sample_count": 10,
                    "annotated_image": "annotation.png",
                }
            )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_replicate_statistics_and_outputs(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.csv"
    output_directory = tmp_path / "dashboard"
    _write_summary(summary_path)

    batch = dashboard.run(summary_path, output_directory)

    assert batch["channel_count"] == 10
    assert batch["image_count"] == 50
    assert batch["mean_width_um"] == pytest.approx(111.5)
    assert batch["observed_channel_mean_variance_um2"] == pytest.approx(9.1666667)
    assert batch["pooled_within_channel_image_variance_um2"] == pytest.approx(10.0)
    assert batch["mean_wall_roughness_p95_um"] == pytest.approx(3.55)
    assert batch["crossed_channel_variance_component_um2"] == pytest.approx(9.1666667)
    assert batch["crossed_location_variance_component_um2"] == pytest.approx(10.0)
    assert batch["crossed_channel_by_location_residual_variance_um2"] == pytest.approx(0.0)

    for filename in (
        "image_metrics.csv",
        "channel_metrics.csv",
        "batch_statistics.csv",
        "subset_comparison.csv",
        "location_replicate_metrics.csv",
    ):
        assert (output_directory / filename).is_file()
    for filename in (
        "channel_replicate_dashboard.png",
        "channel_replicate_heatmap.png",
    ):
        image = cv2.imread(str(output_directory / filename))
        assert image is not None
        assert image.shape[0] > 1000
        assert image.shape[1] > 1000
