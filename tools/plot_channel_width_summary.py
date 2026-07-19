from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


TYPE_LABELS = {
    "thin_channels": "Thin",
    "wide_channels": "Wide",
}
TYPE_COLORS = {
    "thin_channels": "#2878B5",
    "wide_channels": "#E07A1F",
}


@dataclass(frozen=True)
class ImageMetrics:
    group: str
    image: str
    median_width_um: float
    mean_width_um: float
    width_variance_um2: float
    width_sd_um: float
    width_iqr_um: float
    width_cv_percent: float
    wall_rms_um: float
    wall_p95_um: float
    sample_count: int
    width_q25_um: float
    width_q75_um: float
    width_min_um: float
    width_max_um: float


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_image_metrics(summary_path: Path, samples_path: Path) -> list[ImageMetrics]:
    summary_rows = _read_csv(summary_path)
    sample_rows = _read_csv(samples_path)
    samples_by_image: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in sample_rows:
        samples_by_image[(row["group"], row["image"])].append(float(row["width_um"]))

    metrics: list[ImageMetrics] = []
    for row in summary_rows:
        key = (row["group"], row["image"])
        values = np.asarray(samples_by_image[key], dtype=np.float64)
        if values.size < 2:
            raise ValueError(f"Fewer than two width samples are available for {key}")
        mean = float(np.mean(values))
        q25, q75 = np.percentile(values, [25, 75])
        metrics.append(
            ImageMetrics(
                group=row["group"],
                image=row["image"],
                median_width_um=float(row["median_width_um"]),
                mean_width_um=mean,
                width_variance_um2=float(np.var(values, ddof=1)),
                width_sd_um=float(np.std(values, ddof=1)),
                width_iqr_um=float(q75 - q25),
                width_cv_percent=float(np.std(values, ddof=1) / mean * 100.0),
                wall_rms_um=float(row["wall_rms_um"]),
                wall_p95_um=float(row["wall_p95_um"]),
                sample_count=int(row["sample_count"]),
                width_q25_um=float(q25),
                width_q75_um=float(q75),
                width_min_um=float(np.min(values)),
                width_max_um=float(np.max(values)),
            )
        )
    if not metrics:
        raise ValueError("No image metrics were loaded")
    return metrics


def _bootstrap_mean_ci(values: np.ndarray, *, seed: int = 20260718) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(5000, len(values)), replace=True).mean(axis=1)
    low, high = np.percentile(draws, [2.5, 97.5])
    return float(low), float(high)


def build_type_statistics(metrics: list[ImageMetrics]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    groups = sorted({metric.group for metric in metrics}, key=lambda value: TYPE_LABELS.get(value, value))
    for group in groups:
        group_metrics = [metric for metric in metrics if metric.group == group]
        representative_widths = np.asarray(
            [metric.median_width_um for metric in group_metrics], dtype=np.float64
        )
        within_sd = np.asarray([metric.width_sd_um for metric in group_metrics])
        within_iqr = np.asarray([metric.width_iqr_um for metric in group_metrics])
        roughness = np.asarray([metric.wall_p95_um for metric in group_metrics])
        mean_width = float(np.mean(representative_widths))
        ci_low, ci_high = _bootstrap_mean_ci(representative_widths)
        between_sd = float(np.std(representative_widths, ddof=1))
        rows.append(
            {
                "group": group,
                "channel_type": TYPE_LABELS.get(group, group),
                "channel_count": len(group_metrics),
                "mean_channel_width_um": mean_width,
                "mean_width_ci95_low_um": ci_low,
                "mean_width_ci95_high_um": ci_high,
                "median_channel_width_um": float(np.median(representative_widths)),
                "between_channel_variance_um2": float(np.var(representative_widths, ddof=1)),
                "between_channel_sd_um": between_sd,
                "between_channel_cv_percent": between_sd / mean_width * 100.0,
                "minimum_channel_width_um": float(np.min(representative_widths)),
                "maximum_channel_width_um": float(np.max(representative_widths)),
                "mean_within_channel_sd_um": float(np.mean(within_sd)),
                "median_within_channel_sd_um": float(np.median(within_sd)),
                "mean_within_channel_iqr_um": float(np.mean(within_iqr)),
                "median_within_channel_iqr_um": float(np.median(within_iqr)),
                "mean_wall_roughness_p95_um": float(np.mean(roughness)),
                "median_wall_roughness_p95_um": float(np.median(roughness)),
                "wall_roughness_p95_sd_um": float(np.std(roughness, ddof=1)),
            }
        )
    return rows


def _box_with_points(
    axis: plt.Axes,
    values_by_group: list[np.ndarray],
    groups: list[str],
    *,
    ylabel: str,
    title: str,
) -> None:
    positions = np.arange(1, len(groups) + 1)
    box = axis.boxplot(
        values_by_group,
        positions=positions,
        widths=0.48,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "black", "linewidth": 1.8},
    )
    for patch, group in zip(box["boxes"], groups):
        patch.set_facecolor(TYPE_COLORS.get(group, "#777777"))
        patch.set_alpha(0.32)
    for position, values, group in zip(positions, values_by_group, groups):
        jitter = np.linspace(-0.12, 0.12, len(values)) if len(values) > 1 else np.zeros(1)
        axis.scatter(
            position + jitter,
            values,
            s=42,
            color=TYPE_COLORS.get(group, "#777777"),
            edgecolor="white",
            linewidth=0.6,
            alpha=0.9,
            zorder=3,
        )
    axis.set_xticks(positions, [TYPE_LABELS.get(group, group) for group in groups])
    axis.set_ylabel(ylabel)
    axis.set_title(title, loc="left", fontweight="bold")
    axis.grid(axis="y", alpha=0.25)


def plot_type_dashboard(metrics: list[ImageMetrics], output_path: Path) -> None:
    groups = sorted({metric.group for metric in metrics}, key=lambda value: TYPE_LABELS.get(value, value))
    figure, axes = plt.subplots(2, 2, figsize=(14, 10), constrained_layout=True)

    all_widths = np.asarray([metric.median_width_um for metric in metrics])
    bins = np.linspace(float(all_widths.min()) - 8.0, float(all_widths.max()) + 8.0, 18)
    for group in groups:
        values = np.asarray(
            [metric.median_width_um for metric in metrics if metric.group == group]
        )
        color = TYPE_COLORS.get(group, "#777777")
        axes[0, 0].hist(
            values,
            bins=bins,
            alpha=0.48,
            color=color,
            edgecolor="white",
            label=f"{TYPE_LABELS.get(group, group)} (n={len(values)})",
        )
        axes[0, 0].axvline(np.mean(values), color=color, linewidth=2.2, linestyle="--")
    axes[0, 0].set_xlabel("Per-channel median width (µm)")
    axes[0, 0].set_ylabel("Channel count")
    axes[0, 0].set_title("A. Width distribution by channel type", loc="left", fontweight="bold")
    axes[0, 0].legend(frameon=False)
    axes[0, 0].grid(axis="y", alpha=0.25)

    _box_with_points(
        axes[0, 1],
        [np.asarray([m.median_width_um for m in metrics if m.group == group]) for group in groups],
        groups,
        ylabel="Per-channel median width (µm)",
        title="B. Between-channel variation",
    )
    _box_with_points(
        axes[1, 0],
        [np.asarray([m.width_sd_um for m in metrics if m.group == group]) for group in groups],
        groups,
        ylabel="SD of perpendicular widths within image (µm)",
        title="C. Within-channel width variation",
    )
    _box_with_points(
        axes[1, 1],
        [np.asarray([m.wall_p95_um for m in metrics if m.group == group]) for group in groups],
        groups,
        ylabel="Wall roughness, P95 absolute residual (µm)",
        title="D. Channel-wall roughness",
    )
    figure.suptitle(
        "Channel width and wall-quality summary\n"
        "Each point represents one image/channel; dashed histogram lines are type means",
        fontsize=16,
        fontweight="bold",
    )
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)


def _natural_image_key(image: str) -> tuple[str, int]:
    stem = Path(image).stem
    prefix, _, suffix = stem.rpartition("_")
    return prefix, int(suffix) if suffix.isdigit() else 0


def plot_per_channel_ranges(metrics: list[ImageMetrics], output_path: Path) -> None:
    groups = sorted({metric.group for metric in metrics}, key=lambda value: TYPE_LABELS.get(value, value))
    figure, axes = plt.subplots(
        len(groups), 1, figsize=(15, 8.5), constrained_layout=True, squeeze=False
    )
    for axis, group in zip(axes[:, 0], groups):
        selected = sorted(
            [metric for metric in metrics if metric.group == group],
            key=lambda metric: _natural_image_key(metric.image),
        )
        x = np.arange(len(selected))
        color = TYPE_COLORS.get(group, "#777777")
        for index, metric in enumerate(selected):
            axis.vlines(
                index,
                metric.width_min_um,
                metric.width_max_um,
                color=color,
                alpha=0.20,
                linewidth=3,
            )
            axis.vlines(
                index,
                metric.width_q25_um,
                metric.width_q75_um,
                color=color,
                linewidth=7,
                alpha=0.72,
            )
        axis.scatter(
            x,
            [metric.median_width_um for metric in selected],
            color=color,
            edgecolor="white",
            linewidth=0.7,
            s=50,
            zorder=3,
        )
        axis.axhline(
            np.mean([metric.median_width_um for metric in selected]),
            color="black",
            linestyle="--",
            linewidth=1.3,
            label="Type mean of channel medians",
        )
        axis.set_xticks(x, [Path(metric.image).stem for metric in selected], rotation=45, ha="right")
        axis.set_ylabel("Width (µm)")
        axis.set_title(f"{TYPE_LABELS.get(group, group)} channels", loc="left", fontweight="bold")
        axis.grid(axis="y", alpha=0.25)
        axis.legend(frameon=False, loc="upper left")
    figure.suptitle(
        "Per-channel width distributions\n"
        "Dot: median | thick line: IQR | thin line: observed range",
        fontsize=16,
        fontweight="bold",
    )
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(summary_path: Path, samples_path: Path, output_directory: Path) -> list[dict[str, object]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics = load_image_metrics(summary_path, samples_path)
    statistics = build_type_statistics(metrics)
    plot_type_dashboard(metrics, output_directory / "channel_type_dashboard.png")
    plot_per_channel_ranges(metrics, output_directory / "per_channel_width_ranges.png")
    _write_csv(output_directory / "channel_type_statistics.csv", statistics)
    _write_csv(
        output_directory / "per_image_metrics.csv",
        [metric.__dict__.copy() for metric in metrics],
    )
    return statistics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot channel-type width variation and wall-roughness summaries."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    statistics = run(args.summary, args.samples, args.output_dir)
    for row in statistics:
        print(
            f"{row['channel_type']}: mean {row['mean_channel_width_um']:.1f} um, "
            f"between-channel SD {row['between_channel_sd_um']:.1f} um, "
            f"mean wall P95 {row['mean_wall_roughness_p95_um']:.1f} um"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
