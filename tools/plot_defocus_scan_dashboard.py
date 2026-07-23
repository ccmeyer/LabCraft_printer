from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np

import plot_width_scan_dashboard as width_dashboard


FILENAME_PATTERN = re.compile(
    r"^(?P<defocus>\d+(?:\.\d+)?)mm_(?P<channel>\d+)_(?P<image>\d+)\.[^.]+$",
    re.IGNORECASE,
)


def parse_image_name(image_name: str) -> tuple[float, int, int]:
    match = FILENAME_PATTERN.match(image_name)
    if match is None:
        raise ValueError(
            f"Expected image name '<defocus>mm_<channel>_<image>.*', got {image_name!r}"
        )
    return (
        float(match.group("defocus")),
        int(match.group("channel")),
        int(match.group("image")),
    )


def load_image_metrics(summary_path: Path) -> list[width_dashboard.ImageMetric]:
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    metrics: list[width_dashboard.ImageMetric] = []
    identities: set[tuple[float, int, int]] = set()
    for row in rows:
        defocus_mm, channel_replicate, image_replicate = parse_image_name(row["image"])
        identity = (defocus_mm, channel_replicate, image_replicate)
        if identity in identities:
            raise ValueError(f"Duplicate image identity in summary: {identity}")
        identities.add(identity)
        metrics.append(
            width_dashboard.ImageMetric(
                geometry_um=defocus_mm,
                channel_replicate=channel_replicate,
                image_replicate=image_replicate,
                group=row["group"],
                image=row["image"],
                median_width_um=float(row["median_width_um"]),
                width_iqr_um=float(row["width_iqr_um"]),
                wall_rms_um=float(row["wall_rms_um"]),
                wall_p95_um=float(row["wall_p95_um"]),
                sample_count=int(row["sample_count"]),
                annotated_image=row.get("annotated_image", ""),
            )
        )
    if not metrics:
        raise ValueError(f"No image measurements found in {summary_path}")
    return sorted(
        metrics,
        key=lambda metric: (
            metric.geometry_um,
            metric.channel_replicate,
            metric.image_replicate,
        ),
    )


def _rename_key(
    rows: list[dict[str, object]], replacements: dict[str, str]
) -> list[dict[str, object]]:
    return [
        {replacements.get(key, key): value for key, value in row.items()} for row in rows
    ]


def _image_rows(
    metrics: list[width_dashboard.ImageMetric],
) -> list[dict[str, object]]:
    return [
        {
            "defocus_mm": metric.geometry_um,
            "channel_replicate": metric.channel_replicate,
            "image_replicate": metric.image_replicate,
            "group": metric.group,
            "image": metric.image,
            "median_width_um": metric.median_width_um,
            "width_iqr_um": metric.width_iqr_um,
            "wall_rms_um": metric.wall_rms_um,
            "wall_p95_um": metric.wall_p95_um,
            "sample_count": metric.sample_count,
            "annotated_image": metric.annotated_image,
        }
        for metric in metrics
    ]


def build_location_replicate_metrics(
    metrics: list[width_dashboard.ImageMetric],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    identities = sorted(
        {(metric.geometry_um, metric.image_replicate) for metric in metrics}
    )
    for defocus_mm, image_replicate in identities:
        values = np.asarray(
            [
                metric.median_width_um
                for metric in metrics
                if metric.geometry_um == defocus_mm
                and metric.image_replicate == image_replicate
            ],
            dtype=np.float64,
        )
        rows.append(
            {
                "defocus_mm": defocus_mm,
                "image_replicate": image_replicate,
                "channel_count": values.size,
                "mean_width_um": float(np.mean(values)),
                "channel_variance_um2": float(np.var(values, ddof=1))
                if values.size > 1
                else 0.0,
                "channel_sd_um": float(np.std(values, ddof=1))
                if values.size > 1
                else 0.0,
                "minimum_width_um": float(np.min(values)),
                "maximum_width_um": float(np.max(values)),
            }
        )
    return rows


def run(summary_path: Path, output_directory: Path) -> list[dict[str, object]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics = load_image_metrics(summary_path)
    channel_rows_internal = width_dashboard.build_channel_metrics(metrics)
    defocus_rows_internal = width_dashboard.build_geometry_metrics(
        metrics, channel_rows_internal
    )
    comparison_rows_internal = width_dashboard.build_geometry_comparisons(
        channel_rows_internal
    )

    channel_rows = _rename_key(
        channel_rows_internal, {"geometry_um": "defocus_mm"}
    )
    defocus_rows = _rename_key(
        defocus_rows_internal, {"geometry_um": "defocus_mm"}
    )
    comparison_rows = _rename_key(
        comparison_rows_internal,
        {
            "first_geometry_um": "first_defocus_mm",
            "second_geometry_um": "second_defocus_mm",
        },
    )
    location_rows = build_location_replicate_metrics(metrics)
    width_dashboard._write_csv(output_directory / "image_metrics.csv", _image_rows(metrics))
    width_dashboard._write_csv(output_directory / "channel_metrics.csv", channel_rows)
    width_dashboard._write_csv(
        output_directory / "location_replicate_metrics.csv", location_rows
    )
    width_dashboard._write_csv(output_directory / "defocus_metrics.csv", defocus_rows)
    width_dashboard._write_csv(
        output_directory / "defocus_comparisons.csv", comparison_rows
    )
    width_dashboard.plot_dashboard(
        metrics,
        channel_rows_internal,
        defocus_rows_internal,
        output_directory / "defocus_dashboard.png",
        factor_name="Defocus",
        factor_unit="mm",
        figure_title="Laser-cut single-line channels: defocus batch dashboard",
        figure_subtitle="Defocus setting is the controlled cutting parameter",
    )
    width_dashboard.plot_replicate_heatmap(
        metrics,
        output_directory / "defocus_replicate_heatmap.png",
        factor_name="Defocus",
        factor_unit="mm",
    )
    return defocus_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create nested width, variance, and roughness summaries by defocus."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = run(args.summary, args.output_dir)
    for row in rows:
        print(
            f"{float(row['defocus_mm']):g} mm defocus: "
            f"mean={float(row['mean_width_um']):.1f} um, "
            f"within-channel SD={float(row['pooled_within_channel_image_sd_um']):.1f} um, "
            f"observed channel-mean SD="
            f"{float(row['observed_channel_mean_sd_um']):.1f} um, "
            f"wall P95={float(row['mean_wall_roughness_p95_um']):.1f} um"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
