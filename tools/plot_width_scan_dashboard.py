from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


FILENAME_PATTERN = re.compile(
    r"^(?P<geometry>\d+(?:\.\d+)?)um_(?P<channel>\d+)_(?P<image>\d+)\.[^.]+$",
    re.IGNORECASE,
)
COLORS = {30.0: "#2c7fb8", 40.0: "#41ab5d", 50.0: "#e67e22"}


@dataclass(frozen=True)
class ImageMetric:
    geometry_um: float
    channel_replicate: int
    image_replicate: int
    group: str
    image: str
    median_width_um: float
    width_iqr_um: float
    wall_rms_um: float
    wall_p95_um: float
    sample_count: int
    annotated_image: str


def parse_image_name(image_name: str) -> tuple[float, int, int]:
    match = FILENAME_PATTERN.match(image_name)
    if match is None:
        raise ValueError(
            f"Expected image name '<geometry>um_<channel>_<image>.*', got {image_name!r}"
        )
    return (
        float(match.group("geometry")),
        int(match.group("channel")),
        int(match.group("image")),
    )


def load_image_metrics(summary_path: Path) -> list[ImageMetric]:
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    metrics: list[ImageMetric] = []
    identities: set[tuple[float, int, int]] = set()
    for row in rows:
        geometry_um, channel_replicate, image_replicate = parse_image_name(row["image"])
        identity = (geometry_um, channel_replicate, image_replicate)
        if identity in identities:
            raise ValueError(f"Duplicate image identity in summary: {identity}")
        identities.add(identity)
        metrics.append(
            ImageMetric(
                geometry_um=geometry_um,
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


def _sample_variance(values: np.ndarray) -> float:
    return 0.0 if values.size < 2 else float(np.var(values, ddof=1))


def build_channel_metrics(metrics: list[ImageMetric]) -> list[dict[str, object]]:
    grouped: dict[tuple[float, int], list[ImageMetric]] = {}
    for metric in metrics:
        grouped.setdefault((metric.geometry_um, metric.channel_replicate), []).append(metric)

    rows: list[dict[str, object]] = []
    for (geometry_um, channel_replicate), images in sorted(grouped.items()):
        images = sorted(images, key=lambda item: item.image_replicate)
        widths = np.asarray([item.median_width_um for item in images], dtype=np.float64)
        roughness = np.asarray([item.wall_p95_um for item in images], dtype=np.float64)
        mean_width = float(np.mean(widths))
        rows.append(
            {
                "geometry_um": geometry_um,
                "channel_replicate": channel_replicate,
                "image_count": len(images),
                "mean_width_um": mean_width,
                "median_width_um": float(np.median(widths)),
                "within_channel_image_variance_um2": _sample_variance(widths),
                "within_channel_image_sd_um": float(np.std(widths, ddof=1))
                if widths.size > 1
                else 0.0,
                "within_channel_image_cv_percent": 100.0 * float(np.std(widths, ddof=1)) / mean_width
                if widths.size > 1 and mean_width
                else 0.0,
                "minimum_image_width_um": float(np.min(widths)),
                "maximum_image_width_um": float(np.max(widths)),
                "image_width_range_um": float(np.ptp(widths)),
                "mean_image_width_iqr_um": float(
                    np.mean([item.width_iqr_um for item in images])
                ),
                "mean_wall_roughness_p95_um": float(np.mean(roughness)),
                "median_wall_roughness_p95_um": float(np.median(roughness)),
            }
        )
    return rows


def _bootstrap_mean_ci(
    values: np.ndarray, *, seed: int, draws: int = 10_000
) -> tuple[float, float]:
    if values.size == 1:
        return float(values[0]), float(values[0])
    rng = np.random.default_rng(seed)
    means = np.mean(rng.choice(values, size=(draws, values.size), replace=True), axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


def build_geometry_metrics(
    metrics: list[ImageMetric], channel_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    geometries = sorted({metric.geometry_um for metric in metrics})
    rows: list[dict[str, object]] = []
    for geometry_index, geometry_um in enumerate(geometries):
        geometry_images = [metric for metric in metrics if metric.geometry_um == geometry_um]
        geometry_channels = [
            row for row in channel_rows if float(row["geometry_um"]) == geometry_um
        ]
        channel_means = np.asarray(
            [float(row["mean_width_um"]) for row in geometry_channels], dtype=np.float64
        )
        grand_mean = float(np.mean(channel_means))
        ci_low, ci_high = _bootstrap_mean_ci(
            channel_means, seed=20260719 + geometry_index
        )

        image_groups: dict[int, np.ndarray] = {}
        for channel in sorted({item.channel_replicate for item in geometry_images}):
            image_groups[channel] = np.asarray(
                [
                    item.median_width_um
                    for item in geometry_images
                    if item.channel_replicate == channel
                ],
                dtype=np.float64,
            )
        total_images = sum(values.size for values in image_groups.values())
        within_df = total_images - len(image_groups)
        ss_within = sum(
            float(np.sum((values - np.mean(values)) ** 2)) for values in image_groups.values()
        )
        mean_square_within = ss_within / within_df if within_df > 0 else 0.0

        counts = np.asarray([values.size for values in image_groups.values()], dtype=np.float64)
        weighted_grand_mean = float(
            sum(float(np.sum(values)) for values in image_groups.values()) / total_images
        )
        ss_between = sum(
            values.size * (float(np.mean(values)) - weighted_grand_mean) ** 2
            for values in image_groups.values()
        )
        between_df = len(image_groups) - 1
        mean_square_between = ss_between / between_df if between_df > 0 else 0.0
        effective_images_per_channel = (
            (total_images - float(np.sum(counts * counts)) / total_images) / between_df
            if between_df > 0
            else 1.0
        )
        channel_variance_component = max(
            (mean_square_between - mean_square_within) / effective_images_per_channel, 0.0
        )
        total_variance_component = channel_variance_component + mean_square_within
        roughness = np.asarray(
            [metric.wall_p95_um for metric in geometry_images], dtype=np.float64
        )

        rows.append(
            {
                "geometry_um": geometry_um,
                "channel_count": len(geometry_channels),
                "image_count": len(geometry_images),
                "mean_width_um": grand_mean,
                "mean_width_ci95_low_um": ci_low,
                "mean_width_ci95_high_um": ci_high,
                "minimum_channel_mean_width_um": float(np.min(channel_means)),
                "maximum_channel_mean_width_um": float(np.max(channel_means)),
                "observed_channel_mean_variance_um2": _sample_variance(channel_means),
                "observed_channel_mean_sd_um": float(np.std(channel_means, ddof=1))
                if channel_means.size > 1
                else 0.0,
                "pooled_within_channel_image_variance_um2": mean_square_within,
                "pooled_within_channel_image_sd_um": float(np.sqrt(mean_square_within)),
                "estimated_between_channel_variance_component_um2": channel_variance_component,
                "estimated_between_channel_sd_component_um": float(
                    np.sqrt(channel_variance_component)
                ),
                "estimated_total_variance_um2": total_variance_component,
                "estimated_total_sd_um": float(np.sqrt(total_variance_component)),
                "estimated_total_cv_percent": 100.0
                * float(np.sqrt(total_variance_component))
                / grand_mean
                if grand_mean
                else 0.0,
                "mean_wall_roughness_p95_um": float(np.mean(roughness)),
                "median_wall_roughness_p95_um": float(np.median(roughness)),
                "mean_image_width_iqr_um": float(
                    np.mean([metric.width_iqr_um for metric in geometry_images])
                ),
            }
        )
    return rows


def build_geometry_comparisons(
    channel_rows: list[dict[str, object]], *, draws: int = 20_000
) -> list[dict[str, object]]:
    geometries = sorted({float(row["geometry_um"]) for row in channel_rows})
    rows: list[dict[str, object]] = []
    rng = np.random.default_rng(20260719)
    for first_index, first in enumerate(geometries):
        first_values = np.asarray(
            [
                float(row["mean_width_um"])
                for row in channel_rows
                if float(row["geometry_um"]) == first
            ]
        )
        for second in geometries[first_index + 1 :]:
            second_values = np.asarray(
                [
                    float(row["mean_width_um"])
                    for row in channel_rows
                    if float(row["geometry_um"]) == second
                ]
            )
            first_bootstrap = np.mean(
                rng.choice(first_values, size=(draws, first_values.size), replace=True), axis=1
            )
            second_bootstrap = np.mean(
                rng.choice(second_values, size=(draws, second_values.size), replace=True), axis=1
            )
            differences = second_bootstrap - first_bootstrap
            ci_low, ci_high = np.percentile(differences, [2.5, 97.5])
            first_mean = float(np.mean(first_values))
            second_mean = float(np.mean(second_values))
            rows.append(
                {
                    "first_geometry_um": first,
                    "second_geometry_um": second,
                    "mean_difference_second_minus_first_um": second_mean - first_mean,
                    "difference_ci95_low_um": float(ci_low),
                    "difference_ci95_high_um": float(ci_high),
                    "mean_width_ratio_second_over_first": second_mean / first_mean,
                    "bootstrap_probability_second_is_wider": float(np.mean(differences > 0.0)),
                }
            )
    return rows


def _color(geometry_um: float, index: int) -> str:
    defaults = ("#2c7fb8", "#41ab5d", "#e67e22", "#8856a7")
    return COLORS.get(geometry_um, defaults[index % len(defaults)])


def _box_with_points(
    ax: plt.Axes,
    grouped_values: list[np.ndarray],
    labels: list[str],
    colors: list[str],
    *,
    ylabel: str,
) -> None:
    box = ax.boxplot(grouped_values, patch_artist=True, widths=0.55, showfliers=False)
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.28)
    for median in box["medians"]:
        median.set_color("black")
        median.set_linewidth(2.0)
    for index, (values, color) in enumerate(zip(grouped_values, colors), start=1):
        offsets = np.linspace(-0.12, 0.12, values.size)
        ax.scatter(index + offsets, values, s=52, color=color, edgecolor="white", zorder=3)
    ax.set_xticks(range(1, len(labels) + 1), labels)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25)


def plot_dashboard(
    metrics: list[ImageMetric],
    channel_rows: list[dict[str, object]],
    geometry_rows: list[dict[str, object]],
    output_path: Path,
    *,
    factor_name: str = "Design geometry",
    factor_unit: str = "um",
    figure_title: str = "Laser-cut channel width scan: hierarchical batch dashboard",
    figure_subtitle: str = (
        "Design labels describe source geometry, not expected measured channel width"
    ),
) -> None:
    geometries = sorted({metric.geometry_um for metric in metrics})
    colors = [_color(geometry, index) for index, geometry in enumerate(geometries)]
    figure = plt.figure(figsize=(19, 15), constrained_layout=True)
    grid = figure.add_gridspec(3, 2, height_ratios=(1.35, 1.0, 1.0))
    ax_all = figure.add_subplot(grid[0, :])
    ax_geometry = figure.add_subplot(grid[1, 0])
    ax_within = figure.add_subplot(grid[1, 1])
    ax_variance = figure.add_subplot(grid[2, 0])
    ax_roughness = figure.add_subplot(grid[2, 1])

    x_index = 0
    x_ticks: list[int] = []
    x_labels: list[str] = []
    image_offsets = np.linspace(-0.27, 0.27, 5)
    for geometry_index, geometry in enumerate(geometries):
        color = colors[geometry_index]
        geometry_positions: list[int] = []
        geometry_row = next(
            row for row in geometry_rows if float(row["geometry_um"]) == geometry
        )
        channels = sorted(
            {item.channel_replicate for item in metrics if item.geometry_um == geometry}
        )
        for channel in channels:
            images = [
                item
                for item in metrics
                if item.geometry_um == geometry and item.channel_replicate == channel
            ]
            positions = [
                x_index + image_offsets[min(item.image_replicate - 1, 4)] for item in images
            ]
            widths = [item.median_width_um for item in images]
            ax_all.scatter(
                positions,
                widths,
                s=44,
                color=color,
                alpha=0.82,
                edgecolor="white",
                linewidth=0.6,
                zorder=3,
            )
            channel_row = next(
                row
                for row in channel_rows
                if float(row["geometry_um"]) == geometry
                and int(row["channel_replicate"]) == channel
            )
            ax_all.scatter(
                x_index,
                float(channel_row["mean_width_um"]),
                marker="D",
                s=72,
                color="black",
                edgecolor="white",
                linewidth=0.8,
                zorder=4,
            )
            geometry_positions.append(x_index)
            x_ticks.append(x_index)
            x_labels.append(f"{geometry:g}-{channel}")
            x_index += 1
        ax_all.hlines(
            float(geometry_row["mean_width_um"]),
            min(geometry_positions) - 0.42,
            max(geometry_positions) + 0.42,
            color=color,
            linewidth=2.1,
            linestyle="--",
            label=f"{geometry:g} {factor_unit} {factor_name.lower()} mean",
        )
        if geometry_index < len(geometries) - 1:
            ax_all.axvline(x_index - 0.5, color="0.65", linewidth=1.1)
    ax_all.set_xticks(x_ticks, x_labels, rotation=45, ha="right")
    ax_all.set_ylabel("Per-image median measured width (um)")
    ax_all.set_xlabel(f"{factor_name} - physical channel replicate")
    ax_all.set_title(
        "A. All 75 image/location measurements\n"
        "Five colored points per channel are image replicates 1 to 5 (left to right); "
        "black diamond is channel mean"
    )
    ax_all.grid(axis="y", alpha=0.25)
    ax_all.legend(ncol=len(geometries), loc="upper left")

    geometry_x = np.arange(len(geometries))
    means = np.asarray(
        [
            float(next(row for row in geometry_rows if float(row["geometry_um"]) == geometry)["mean_width_um"])
            for geometry in geometries
        ]
    )
    lows = np.asarray(
        [
            float(next(row for row in geometry_rows if float(row["geometry_um"]) == geometry)["mean_width_ci95_low_um"])
            for geometry in geometries
        ]
    )
    highs = np.asarray(
        [
            float(next(row for row in geometry_rows if float(row["geometry_um"]) == geometry)["mean_width_ci95_high_um"])
            for geometry in geometries
        ]
    )
    for index, geometry in enumerate(geometries):
        values = np.asarray(
            [
                float(row["mean_width_um"])
                for row in channel_rows
                if float(row["geometry_um"]) == geometry
            ]
        )
        ax_geometry.scatter(
            index + np.linspace(-0.10, 0.10, values.size),
            values,
            color=colors[index],
            s=58,
            edgecolor="white",
            zorder=3,
        )
    ax_geometry.errorbar(
        geometry_x,
        means,
        yerr=np.vstack((means - lows, highs - means)),
        fmt="D",
        color="black",
        capsize=6,
        linewidth=2,
        label="Mean and channel-bootstrap 95% CI",
    )
    factor_labels = [f"{value:g} {factor_unit}" for value in geometries]
    ax_geometry.set_xticks(geometry_x, factor_labels)
    ax_geometry.set_ylabel("Physical-channel mean width (um)")
    ax_geometry.set_title(
        f"B. {factor_name} comparison (each colored point is one channel)"
    )
    ax_geometry.grid(axis="y", alpha=0.25)
    ax_geometry.legend(loc="best")

    within_values = [
        np.asarray(
            [
                float(row["within_channel_image_sd_um"])
                for row in channel_rows
                if float(row["geometry_um"]) == geometry
            ]
        )
        for geometry in geometries
    ]
    _box_with_points(
        ax_within,
        within_values,
        factor_labels,
        colors,
        ylabel="SD among 5 image/location medians (um)",
    )
    ax_within.set_title("C. Within-channel spatial/image variation")

    within_variances = np.asarray(
        [
            float(next(row for row in geometry_rows if float(row["geometry_um"]) == geometry)["pooled_within_channel_image_variance_um2"])
            for geometry in geometries
        ]
    )
    between_variances = np.asarray(
        [
            float(next(row for row in geometry_rows if float(row["geometry_um"]) == geometry)["estimated_between_channel_variance_component_um2"])
            for geometry in geometries
        ]
    )
    ax_variance.bar(
        geometry_x,
        within_variances,
        color=colors,
        alpha=0.38,
        label="Within channel: location/image",
    )
    ax_variance.bar(
        geometry_x,
        between_variances,
        bottom=within_variances,
        color=colors,
        alpha=0.9,
        hatch="//",
        label="Between physical channels",
    )
    ax_variance.set_xticks(geometry_x, factor_labels)
    ax_variance.set_ylabel("Estimated variance component (um^2)")
    ax_variance.set_title("D. Nested variance decomposition")
    ax_variance.grid(axis="y", alpha=0.25)
    ax_variance.legend(loc="best")

    roughness_values = [
        np.asarray(
            [metric.wall_p95_um for metric in metrics if metric.geometry_um == geometry]
        )
        for geometry in geometries
    ]
    _box_with_points(
        ax_roughness,
        roughness_values,
        factor_labels,
        colors,
        ylabel="P95 absolute wall residual (um)",
    )
    ax_roughness.set_title("E. Wall roughness across all images")

    figure.suptitle(
        f"{figure_title}\n{figure_subtitle}",
        fontsize=20,
        fontweight="bold",
    )
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_replicate_heatmap(
    metrics: list[ImageMetric],
    output_path: Path,
    *,
    factor_name: str = "Design geometry",
    factor_unit: str = "um",
) -> None:
    geometries = sorted({metric.geometry_um for metric in metrics})
    row_keys = [
        (geometry, channel)
        for geometry in geometries
        for channel in sorted(
            {item.channel_replicate for item in metrics if item.geometry_um == geometry}
        )
    ]
    image_replicates = sorted({metric.image_replicate for metric in metrics})
    values = np.full((len(row_keys), len(image_replicates)), np.nan)
    lookup = {
        (metric.geometry_um, metric.channel_replicate, metric.image_replicate): metric
        for metric in metrics
    }
    for row_index, (geometry, channel) in enumerate(row_keys):
        for column_index, image_replicate in enumerate(image_replicates):
            metric = lookup.get((geometry, channel, image_replicate))
            if metric is not None:
                values[row_index, column_index] = metric.median_width_um

    figure, ax = plt.subplots(figsize=(9.5, 10.5), constrained_layout=True)
    image = ax.imshow(values, cmap="viridis", aspect="auto")
    for row_index in range(values.shape[0]):
        for column_index in range(values.shape[1]):
            value = values[row_index, column_index]
            if np.isfinite(value):
                normalized = (value - np.nanmin(values)) / (np.nanmax(values) - np.nanmin(values))
                text_color = "white" if normalized < 0.40 or normalized > 0.82 else "black"
                ax.text(
                    column_index,
                    row_index,
                    f"{value:.1f}",
                    ha="center",
                    va="center",
                    color=text_color,
                    fontsize=9,
                )
    for boundary in np.cumsum(
        [sum(1 for geometry, _channel in row_keys if geometry == item) for item in geometries]
    )[:-1]:
        ax.axhline(boundary - 0.5, color="white", linewidth=3)
    ax.set_xticks(range(len(image_replicates)), [str(value) for value in image_replicates])
    ax.set_yticks(
        range(len(row_keys)),
        [
            f"{geometry:g} {factor_unit} - channel {channel}"
            for geometry, channel in row_keys
        ],
    )
    ax.set_xlabel("Image/location replicate")
    ax.set_ylabel(f"{factor_name} and physical channel replicate")
    ax.set_title("Every per-image median width (um)", fontsize=17, fontweight="bold")
    colorbar = figure.colorbar(image, ax=ax)
    colorbar.set_label("Measured width (um)")
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _image_rows(metrics: list[ImageMetric]) -> list[dict[str, object]]:
    return [
        {
            "geometry_um": metric.geometry_um,
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


def run(summary_path: Path, output_directory: Path) -> list[dict[str, object]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics = load_image_metrics(summary_path)
    channel_rows = build_channel_metrics(metrics)
    geometry_rows = build_geometry_metrics(metrics, channel_rows)
    comparison_rows = build_geometry_comparisons(channel_rows)
    _write_csv(output_directory / "image_metrics.csv", _image_rows(metrics))
    _write_csv(output_directory / "channel_metrics.csv", channel_rows)
    _write_csv(output_directory / "geometry_metrics.csv", geometry_rows)
    _write_csv(output_directory / "geometry_comparisons.csv", comparison_rows)
    plot_dashboard(
        metrics,
        channel_rows,
        geometry_rows,
        output_directory / "width_scan_dashboard.png",
    )
    plot_replicate_heatmap(metrics, output_directory / "width_replicate_heatmap.png")
    return geometry_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create hierarchical width, variance, and roughness summaries for a channel scan."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = run(args.summary, args.output_dir)
    for row in rows:
        print(
            f"{float(row['geometry_um']):g} um geometry: "
            f"mean={float(row['mean_width_um']):.1f} um, "
            f"within-channel SD={float(row['pooled_within_channel_image_sd_um']):.1f} um, "
            f"between-channel component SD="
            f"{float(row['estimated_between_channel_sd_component_um']):.1f} um, "
            f"wall P95={float(row['mean_wall_roughness_p95_um']):.1f} um"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
