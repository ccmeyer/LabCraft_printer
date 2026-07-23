from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import plot_defocus_scan_dashboard as defocus_dashboard
import plot_width_scan_dashboard as width_dashboard


COLOR = "#2c7fb8"
REPLICATE_COLORS = ("#2166ac", "#67a9cf", "#1a9850", "#fdae61", "#d73027")


def _bootstrap_difference_ci(
    first: np.ndarray,
    second: np.ndarray,
    *,
    seed: int = 20260720,
    draws: int = 20_000,
) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    first_means = np.mean(
        rng.choice(first, size=(draws, first.size), replace=True), axis=1
    )
    second_means = np.mean(
        rng.choice(second, size=(draws, second.size), replace=True), axis=1
    )
    differences = second_means - first_means
    low, high = np.percentile(differences, [2.5, 97.5])
    return float(np.mean(second) - np.mean(first)), float(low), float(high)


def build_batch_summary(
    metrics: list[width_dashboard.ImageMetric],
    channel_rows: list[dict[str, object]],
) -> dict[str, object]:
    conditions = sorted({metric.geometry_um for metric in metrics})
    if len(conditions) != 1:
        raise ValueError(f"Expected one defocus condition, found {conditions}")
    row = dict(width_dashboard.build_geometry_metrics(metrics, channel_rows)[0])
    channel_widths = np.asarray(
        [float(item["mean_width_um"]) for item in channel_rows], dtype=np.float64
    )
    channel_roughness = np.asarray(
        [float(item["mean_wall_roughness_p95_um"]) for item in channel_rows],
        dtype=np.float64,
    )
    roughness_values = np.asarray(
        [metric.wall_p95_um for metric in metrics], dtype=np.float64
    )
    correlation = (
        float(np.corrcoef(channel_widths, channel_roughness)[0, 1])
        if channel_widths.size > 1
        and np.std(channel_widths) > 0.0
        and np.std(channel_roughness) > 0.0
        else 0.0
    )
    channels = sorted({metric.channel_replicate for metric in metrics})
    locations = sorted({metric.image_replicate for metric in metrics})
    matrix = np.asarray(
        [
            [
                next(
                    metric.median_width_um
                    for metric in metrics
                    if metric.channel_replicate == channel
                    and metric.image_replicate == location
                )
                for location in locations
            ]
            for channel in channels
        ],
        dtype=np.float64,
    )
    grand_mean = float(np.mean(matrix))
    channel_means = np.mean(matrix, axis=1)
    location_means = np.mean(matrix, axis=0)
    residuals = (
        matrix
        - channel_means[:, np.newaxis]
        - location_means[np.newaxis, :]
        + grand_mean
    )
    channel_ms = matrix.shape[1] * float(np.var(channel_means, ddof=1))
    location_ms = matrix.shape[0] * float(np.var(location_means, ddof=1))
    residual_variance = float(
        np.sum(residuals * residuals)
        / ((matrix.shape[0] - 1) * (matrix.shape[1] - 1))
    )
    channel_component = max(
        (channel_ms - residual_variance) / matrix.shape[1], 0.0
    )
    location_component = max(
        (location_ms - residual_variance) / matrix.shape[0], 0.0
    )
    crossed_total_variance = (
        channel_component + location_component + residual_variance
    )
    for key in (
        "estimated_between_channel_variance_component_um2",
        "estimated_between_channel_sd_component_um",
        "estimated_total_variance_um2",
        "estimated_total_sd_um",
        "estimated_total_cv_percent",
    ):
        row.pop(key)
    row.update(
        {
            "defocus_mm": row.pop("geometry_um"),
            "median_channel_mean_width_um": float(np.median(channel_widths)),
            "channel_mean_cv_percent": 100.0
            * float(np.std(channel_widths, ddof=1))
            / float(np.mean(channel_widths)),
            "channel_mean_p05_um": float(np.percentile(channel_widths, 5)),
            "channel_mean_p95_um": float(np.percentile(channel_widths, 95)),
            "wall_roughness_p95_across_images_um": float(
                np.percentile(roughness_values, 95)
            ),
            "channel_width_roughness_pearson_r": correlation,
            "crossed_channel_variance_component_um2": channel_component,
            "crossed_channel_sd_component_um": float(np.sqrt(channel_component)),
            "crossed_location_variance_component_um2": location_component,
            "crossed_location_sd_component_um": float(np.sqrt(location_component)),
            "crossed_channel_by_location_residual_variance_um2": residual_variance,
            "crossed_channel_by_location_residual_sd_um": float(
                np.sqrt(residual_variance)
            ),
            "crossed_total_variance_um2": crossed_total_variance,
            "crossed_total_sd_um": float(np.sqrt(crossed_total_variance)),
            "crossed_total_cv_percent": 100.0
            * float(np.sqrt(crossed_total_variance))
            / grand_mean,
        }
    )
    return row


def build_subset_comparison(
    channel_rows: list[dict[str, object]], *, original_channel_count: int = 5
) -> dict[str, object]:
    original = np.asarray(
        [
            float(row["mean_width_um"])
            for row in channel_rows
            if int(row["channel_replicate"]) <= original_channel_count
        ],
        dtype=np.float64,
    )
    additional = np.asarray(
        [
            float(row["mean_width_um"])
            for row in channel_rows
            if int(row["channel_replicate"]) > original_channel_count
        ],
        dtype=np.float64,
    )
    if original.size == 0 or additional.size == 0:
        raise ValueError("Both original and additional channel subsets must be present")
    difference, ci_low, ci_high = _bootstrap_difference_ci(original, additional)
    original_roughness = np.asarray(
        [
            float(row["mean_wall_roughness_p95_um"])
            for row in channel_rows
            if int(row["channel_replicate"]) <= original_channel_count
        ],
        dtype=np.float64,
    )
    additional_roughness = np.asarray(
        [
            float(row["mean_wall_roughness_p95_um"])
            for row in channel_rows
            if int(row["channel_replicate"]) > original_channel_count
        ],
        dtype=np.float64,
    )
    roughness_difference, roughness_ci_low, roughness_ci_high = (
        _bootstrap_difference_ci(
            original_roughness, additional_roughness, seed=20260721
        )
    )
    original_spatial_sd = np.asarray(
        [
            float(row["within_channel_image_sd_um"])
            for row in channel_rows
            if int(row["channel_replicate"]) <= original_channel_count
        ],
        dtype=np.float64,
    )
    additional_spatial_sd = np.asarray(
        [
            float(row["within_channel_image_sd_um"])
            for row in channel_rows
            if int(row["channel_replicate"]) > original_channel_count
        ],
        dtype=np.float64,
    )
    return {
        "original_channel_count": original.size,
        "additional_channel_count": additional.size,
        "original_mean_width_um": float(np.mean(original)),
        "original_channel_sd_um": float(np.std(original, ddof=1))
        if original.size > 1
        else 0.0,
        "additional_mean_width_um": float(np.mean(additional)),
        "additional_channel_sd_um": float(np.std(additional, ddof=1))
        if additional.size > 1
        else 0.0,
        "additional_minus_original_mean_difference_um": difference,
        "difference_ci95_low_um": ci_low,
        "difference_ci95_high_um": ci_high,
        "original_mean_wall_roughness_p95_um": float(np.mean(original_roughness)),
        "additional_mean_wall_roughness_p95_um": float(
            np.mean(additional_roughness)
        ),
        "additional_minus_original_roughness_difference_um": roughness_difference,
        "roughness_difference_ci95_low_um": roughness_ci_low,
        "roughness_difference_ci95_high_um": roughness_ci_high,
        "original_mean_within_channel_spatial_sd_um": float(
            np.mean(original_spatial_sd)
        ),
        "additional_mean_within_channel_spatial_sd_um": float(
            np.mean(additional_spatial_sd)
        ),
    }


def _channel_arrays(
    metrics: list[width_dashboard.ImageMetric],
) -> tuple[list[int], dict[int, list[width_dashboard.ImageMetric]]]:
    channels = sorted({metric.channel_replicate for metric in metrics})
    grouped = {
        channel: sorted(
            [metric for metric in metrics if metric.channel_replicate == channel],
            key=lambda metric: metric.image_replicate,
        )
        for channel in channels
    }
    return channels, grouped


def plot_dashboard(
    metrics: list[width_dashboard.ImageMetric],
    channel_rows: list[dict[str, object]],
    batch_row: dict[str, object],
    subset_row: dict[str, object],
    output_path: Path,
) -> None:
    channels, grouped = _channel_arrays(metrics)
    figure = plt.figure(figsize=(19, 20), constrained_layout=True)
    grid = figure.add_gridspec(4, 2, height_ratios=(1.35, 1.0, 1.0, 0.9))
    ax_all = figure.add_subplot(grid[0, :])
    ax_distribution = figure.add_subplot(grid[1, 0])
    ax_location = figure.add_subplot(grid[1, 1])
    ax_within = figure.add_subplot(grid[2, 0])
    ax_roughness = figure.add_subplot(grid[2, 1])
    ax_variance = figure.add_subplot(grid[3, 0])
    ax_subsets = figure.add_subplot(grid[3, 1])

    image_offsets = np.linspace(-0.27, 0.27, 5)
    for channel in channels:
        images = grouped[channel]
        for metric in images:
            replicate_index = min(metric.image_replicate - 1, 4)
            ax_all.scatter(
                channel + image_offsets[replicate_index],
                metric.median_width_um,
                color=REPLICATE_COLORS[replicate_index],
                s=42,
                edgecolor="white",
                linewidth=0.5,
                zorder=3,
                label=f"Location {metric.image_replicate}" if channel == channels[0] else None,
            )
        channel_row = next(
            row for row in channel_rows if int(row["channel_replicate"]) == channel
        )
        ax_all.scatter(
            channel,
            float(channel_row["mean_width_um"]),
            marker="D",
            s=62,
            color="black",
            edgecolor="white",
            linewidth=0.7,
            zorder=4,
            label="Channel mean" if channel == channels[0] else None,
        )
    ax_all.axhline(
        float(batch_row["mean_width_um"]),
        color="black",
        linestyle="--",
        linewidth=1.8,
        label="Batch mean",
    )
    ax_all.axvline(5.5, color="0.6", linewidth=1.2)
    ax_all.text(3, ax_all.get_ylim()[1], "original 5", ha="center", va="top")
    ax_all.text(13, ax_all.get_ylim()[1], "additional 15", ha="center", va="top")
    ax_all.set_xticks(channels)
    ax_all.set_xlabel("Physical channel replicate")
    ax_all.set_ylabel("Per-image median width (um)")
    ax_all.set_title(
        "A. All 100 image/location measurements\n"
        "Colored points are five locations; black diamonds are channel means"
    )
    ax_all.grid(axis="y", alpha=0.25)
    ax_all.legend(ncol=7, loc="lower right")

    channel_widths = np.asarray(
        [float(row["mean_width_um"]) for row in channel_rows], dtype=np.float64
    )
    bins = max(5, int(np.ceil(np.sqrt(channel_widths.size))))
    ax_distribution.hist(
        channel_widths, bins=bins, color=COLOR, alpha=0.68, edgecolor="white"
    )
    ax_distribution.axvline(
        float(batch_row["mean_width_um"]),
        color="black",
        linestyle="--",
        linewidth=2,
        label=f"Mean {float(batch_row['mean_width_um']):.1f} um",
    )
    ax_distribution.axvspan(
        float(batch_row["mean_width_ci95_low_um"]),
        float(batch_row["mean_width_ci95_high_um"]),
        color="black",
        alpha=0.12,
        label="Channel-bootstrap 95% CI",
    )
    ax_distribution.set_xlabel("Physical-channel mean width (um)")
    ax_distribution.set_ylabel("Channel count")
    ax_distribution.set_title("B. Production distribution across 20 channels")
    ax_distribution.grid(axis="y", alpha=0.25)
    ax_distribution.legend(loc="best")

    image_replicates = sorted({metric.image_replicate for metric in metrics})
    for channel in channels:
        values = [metric.median_width_um for metric in grouped[channel]]
        ax_location.plot(
            image_replicates, values, color="0.72", alpha=0.45, linewidth=1
        )
    location_means = np.asarray(
        [
            np.mean(
                [
                    metric.median_width_um
                    for metric in metrics
                    if metric.image_replicate == replicate
                ]
            )
            for replicate in image_replicates
        ]
    )
    location_sds = np.asarray(
        [
            np.std(
                [
                    metric.median_width_um
                    for metric in metrics
                    if metric.image_replicate == replicate
                ],
                ddof=1,
            )
            for replicate in image_replicates
        ]
    )
    ax_location.errorbar(
        image_replicates,
        location_means,
        yerr=location_sds,
        color=COLOR,
        marker="o",
        linewidth=2.6,
        capsize=5,
        label="Mean +/- SD across channels",
    )
    ax_location.set_xticks(image_replicates)
    ax_location.set_xlabel("Image/location replicate")
    ax_location.set_ylabel("Per-image median width (um)")
    ax_location.set_title("C. Repeated spatial profile across channels")
    ax_location.grid(alpha=0.25)
    ax_location.legend(loc="best")

    within_sds = np.asarray(
        [float(row["within_channel_image_sd_um"]) for row in channel_rows]
    )
    ax_within.bar(channels, within_sds, color=COLOR, alpha=0.72)
    ax_within.axhline(
        float(batch_row["pooled_within_channel_image_sd_um"]),
        color="black",
        linestyle="--",
        label="Pooled within-channel SD",
    )
    ax_within.set_xticks(channels)
    ax_within.set_xlabel("Physical channel replicate")
    ax_within.set_ylabel("SD among five locations (um)")
    ax_within.set_title("D. Within-channel spatial variation")
    ax_within.grid(axis="y", alpha=0.25)
    ax_within.legend(loc="best")

    for channel in channels:
        roughness = [metric.wall_p95_um for metric in grouped[channel]]
        ax_roughness.scatter(
            [channel] * len(roughness),
            roughness,
            color=COLOR,
            alpha=0.6,
            s=30,
            edgecolor="white",
            linewidth=0.4,
        )
        channel_row = next(
            row for row in channel_rows if int(row["channel_replicate"]) == channel
        )
        ax_roughness.scatter(
            channel,
            float(channel_row["mean_wall_roughness_p95_um"]),
            marker="D",
            color="black",
            s=45,
            zorder=3,
        )
    ax_roughness.axhline(
        float(batch_row["mean_wall_roughness_p95_um"]),
        color="black",
        linestyle="--",
        label="Batch mean roughness",
    )
    ax_roughness.set_xticks(channels)
    ax_roughness.set_xlabel("Physical channel replicate")
    ax_roughness.set_ylabel("P95 absolute wall residual (um)")
    ax_roughness.set_title("E. Wall roughness: images and channel means")
    ax_roughness.grid(axis="y", alpha=0.25)
    ax_roughness.legend(loc="best")

    variance_values = [
        float(batch_row["crossed_channel_variance_component_um2"]),
        float(batch_row["crossed_location_variance_component_um2"]),
        float(batch_row["crossed_channel_by_location_residual_variance_um2"]),
    ]
    bars = ax_variance.bar(
        [0, 1, 2],
        variance_values,
        color=("#ef8a62", "#67a9cf", "#b2abd2"),
        alpha=0.85,
    )
    ax_variance.bar_label(bars, fmt="%.1f")
    ax_variance.set_xticks(
        [0, 1, 2],
        [
            "Physical\nchannel",
            "Systematic\nlocation profile",
            "Channel x location\nresidual",
        ],
    )
    ax_variance.set_ylabel("Estimated variance component (um^2)")
    ax_variance.set_title("F. Crossed channel x location variance decomposition")
    ax_variance.grid(axis="y", alpha=0.25)

    original = channel_widths[:5]
    additional = channel_widths[5:]
    box = ax_subsets.boxplot(
        [original, additional], patch_artist=True, widths=0.55, showfliers=False
    )
    for patch, color in zip(box["boxes"], ("#92c5de", "#f4a582")):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    for index, values in enumerate((original, additional), start=1):
        ax_subsets.scatter(
            index + np.linspace(-0.12, 0.12, values.size),
            values,
            color="black",
            s=38,
            alpha=0.75,
        )
    ax_subsets.set_xticks([1, 2], ["Original channels 1-5", "Additional channels 6-20"])
    ax_subsets.set_ylabel("Physical-channel mean width (um)")
    ax_subsets.set_title(
        "G. Original versus additional channels\n"
        f"Difference {float(subset_row['additional_minus_original_mean_difference_um']):+.1f} um "
        f"(95% CI {float(subset_row['difference_ci95_low_um']):+.1f} to "
        f"{float(subset_row['difference_ci95_high_um']):+.1f})\n"
        f"Roughness difference "
        f"{float(subset_row['additional_minus_original_roughness_difference_um']):+.1f} um"
    )
    ax_subsets.grid(axis="y", alpha=0.25)

    figure.suptitle(
        "Zero-defocus channel production replicate study\n"
        "20 physical channels x 5 image locations",
        fontsize=21,
        fontweight="bold",
    )
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_heatmap(
    metrics: list[width_dashboard.ImageMetric], output_path: Path
) -> None:
    channels, grouped = _channel_arrays(metrics)
    image_replicates = sorted({metric.image_replicate for metric in metrics})
    values = np.asarray(
        [
            [
                next(
                    metric.median_width_um
                    for metric in grouped[channel]
                    if metric.image_replicate == image_replicate
                )
                for image_replicate in image_replicates
            ]
            for channel in channels
        ]
    )
    figure, ax = plt.subplots(figsize=(10, 13), constrained_layout=True)
    image = ax.imshow(values, cmap="viridis", aspect="auto")
    value_min, value_max = float(np.min(values)), float(np.max(values))
    for row_index in range(values.shape[0]):
        for column_index in range(values.shape[1]):
            value = values[row_index, column_index]
            normalized = (value - value_min) / (value_max - value_min)
            text_color = "white" if normalized < 0.38 or normalized > 0.82 else "black"
            ax.text(
                column_index,
                row_index,
                f"{value:.1f}",
                ha="center",
                va="center",
                color=text_color,
                fontsize=8.5,
            )
    ax.axhline(4.5, color="white", linewidth=3)
    ax.set_xticks(range(len(image_replicates)), image_replicates)
    ax.set_yticks(range(len(channels)), [f"Channel {channel}" for channel in channels])
    ax.set_xlabel("Image/location replicate")
    ax.set_ylabel("Physical channel replicate")
    ax.set_title("Every per-image median width (um)", fontsize=18, fontweight="bold")
    colorbar = figure.colorbar(image, ax=ax)
    colorbar.set_label("Measured width (um)")
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _image_rows(
    metrics: list[width_dashboard.ImageMetric],
) -> list[dict[str, object]]:
    return [
        {
            "defocus_mm": metric.geometry_um,
            "channel_replicate": metric.channel_replicate,
            "image_replicate": metric.image_replicate,
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


def run(summary_path: Path, output_directory: Path) -> dict[str, object]:
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics = defocus_dashboard.load_image_metrics(summary_path)
    channel_rows = width_dashboard.build_channel_metrics(metrics)
    batch_row = build_batch_summary(metrics, channel_rows)
    subset_row = build_subset_comparison(channel_rows)
    location_rows = defocus_dashboard.build_location_replicate_metrics(metrics)

    width_dashboard._write_csv(output_directory / "image_metrics.csv", _image_rows(metrics))
    width_dashboard._write_csv(output_directory / "channel_metrics.csv", channel_rows)
    width_dashboard._write_csv(output_directory / "batch_statistics.csv", [batch_row])
    width_dashboard._write_csv(output_directory / "subset_comparison.csv", [subset_row])
    width_dashboard._write_csv(
        output_directory / "location_replicate_metrics.csv", location_rows
    )
    plot_dashboard(
        metrics,
        channel_rows,
        batch_row,
        subset_row,
        output_directory / "channel_replicate_dashboard.png",
    )
    plot_heatmap(metrics, output_directory / "channel_replicate_heatmap.png")
    return batch_row


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize width, variance, and roughness across replicate channels."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    row = run(args.summary, args.output_dir)
    print(
        f"Channels={int(row['channel_count'])}, images={int(row['image_count'])}, "
        f"mean={float(row['mean_width_um']):.1f} um, "
        f"channel SD={float(row['observed_channel_mean_sd_um']):.1f} um, "
        f"within-channel SD={float(row['pooled_within_channel_image_sd_um']):.1f} um, "
        f"wall P95={float(row['mean_wall_roughness_p95_um']):.1f} um"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
