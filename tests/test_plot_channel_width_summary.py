from __future__ import annotations

import csv

from PIL import Image

from tools import plot_channel_width_summary as mod


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_summary_statistics_and_plots_are_generated(tmp_path):
    summary_rows = []
    sample_rows = []
    values_by_image = {
        ("thin_channels", "thin_1.png"): [98.0, 100.0, 102.0],
        ("thin_channels", "thin_2.png"): [108.0, 110.0, 112.0],
        ("wide_channels", "wide_1.png"): [198.0, 200.0, 202.0],
        ("wide_channels", "wide_2.png"): [218.0, 220.0, 222.0],
    }
    for (group, image), values in values_by_image.items():
        summary_rows.append(
            {
                "group": group,
                "image": image,
                "median_width_um": sorted(values)[1],
                "wall_rms_um": 1.5,
                "wall_p95_um": 3.0 if group == "thin_channels" else 2.0,
                "sample_count": len(values),
            }
        )
        for index, value in enumerate(values, start=1):
            sample_rows.append(
                {
                    "group": group,
                    "image": image,
                    "sample_index": index,
                    "width_um": value,
                }
            )
    summary_path = tmp_path / "summary.csv"
    samples_path = tmp_path / "samples.csv"
    output_directory = tmp_path / "plots"
    _write_csv(summary_path, summary_rows)
    _write_csv(samples_path, sample_rows)

    statistics = mod.run(summary_path, samples_path, output_directory)

    by_type = {row["channel_type"]: row for row in statistics}
    assert by_type["Thin"]["mean_channel_width_um"] == 105.0
    assert by_type["Wide"]["mean_channel_width_um"] == 210.0
    assert by_type["Thin"]["between_channel_variance_um2"] == 50.0
    assert by_type["Wide"]["mean_wall_roughness_p95_um"] == 2.0
    for filename in (
        "channel_type_dashboard.png",
        "per_channel_width_ranges.png",
    ):
        path = output_directory / filename
        assert path.exists()
        with Image.open(path) as image:
            assert image.width >= 1000
            assert image.height >= 700
    assert (output_directory / "channel_type_statistics.csv").exists()
    assert (output_directory / "per_image_metrics.csv").exists()
