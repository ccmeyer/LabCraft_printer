from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares


IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}


@dataclass(frozen=True)
class WidthSample:
    along_px: float
    center_xy: np.ndarray
    tangent_xy: np.ndarray
    normal_xy: np.ndarray
    first_wall_xy: np.ndarray
    second_wall_xy: np.ndarray
    width_px: float


@dataclass
class ChannelAnalysis:
    source_bgr: np.ndarray
    green: np.ndarray
    mask: np.ndarray
    threshold: float
    origin_xy: np.ndarray
    major_axis_xy: np.ndarray
    minor_axis_xy: np.ndarray
    along_px: np.ndarray
    first_wall_across_px: np.ndarray
    second_wall_across_px: np.ndarray
    center_across_px: np.ndarray
    center_slope: np.ndarray
    accepted_along_range_px: tuple[float, float]
    first_observation_along_px: np.ndarray
    first_observation_across_px: np.ndarray
    second_observation_along_px: np.ndarray
    second_observation_across_px: np.ndarray
    first_wall_residual_px: np.ndarray
    second_wall_residual_px: np.ndarray
    aperture_circle: tuple[float, float, float] | None
    aperture_margin_px: float
    samples: list[WidthSample]
    micrometers_per_pixel: float

    @property
    def widths_px(self) -> np.ndarray:
        return np.asarray([sample.width_px for sample in self.samples], dtype=np.float64)

    @property
    def median_width_px(self) -> float:
        return float(np.median(self.widths_px))

    @property
    def width_iqr_px(self) -> float:
        values = self.widths_px
        return float(np.percentile(values, 75) - np.percentile(values, 25))

    @property
    def median_width_um(self) -> float:
        return self.median_width_px * self.micrometers_per_pixel

    @property
    def width_iqr_um(self) -> float:
        return self.width_iqr_px * self.micrometers_per_pixel

    @property
    def wall_residuals_px(self) -> np.ndarray:
        return np.concatenate((self.first_wall_residual_px, self.second_wall_residual_px))

    @property
    def wall_rms_um(self) -> float:
        residuals = self.wall_residuals_px
        return float(np.sqrt(np.mean(residuals * residuals))) * self.micrometers_per_pixel

    @property
    def wall_p95_um(self) -> float:
        return float(np.percentile(np.abs(self.wall_residuals_px), 95)) * self.micrometers_per_pixel

    def _residual_rms_um(self, residuals: np.ndarray) -> float:
        return float(np.sqrt(np.mean(residuals * residuals))) * self.micrometers_per_pixel

    def _residual_p95_um(self, residuals: np.ndarray) -> float:
        return float(np.percentile(np.abs(residuals), 95)) * self.micrometers_per_pixel

    @property
    def first_wall_rms_um(self) -> float:
        return self._residual_rms_um(self.first_wall_residual_px)

    @property
    def second_wall_rms_um(self) -> float:
        return self._residual_rms_um(self.second_wall_residual_px)

    @property
    def first_wall_p95_um(self) -> float:
        return self._residual_p95_um(self.first_wall_residual_px)

    @property
    def second_wall_p95_um(self) -> float:
        return self._residual_p95_um(self.second_wall_residual_px)

    @property
    def normal_angles_deg(self) -> np.ndarray:
        angles = np.asarray(
            [math.atan2(sample.normal_xy[1], sample.normal_xy[0]) for sample in self.samples]
        )
        return np.unwrap(angles) * (180.0 / math.pi)

    @property
    def normal_angle_range_deg(self) -> float:
        return float(np.ptp(self.normal_angles_deg))

    @property
    def normal_angle_step_p95_deg(self) -> float:
        differences = np.diff(self.normal_angles_deg)
        return 0.0 if differences.size == 0 else float(np.percentile(np.abs(differences), 95))

    @property
    def normal_angle_bend_p95_deg(self) -> float:
        differences = np.diff(self.normal_angles_deg, n=2)
        return 0.0 if differences.size == 0 else float(np.percentile(np.abs(differences), 95))


def estimate_aperture(image_paths: list[Path]) -> tuple[float, float, float]:
    """Estimate the fixed circular microscope field from an image ensemble."""
    if len(image_paths) < 3:
        raise ValueError("At least three images are required to estimate the microscope aperture")
    gradients: list[np.ndarray] = []
    expected_shape: tuple[int, int] | None = None
    for path in image_paths:
        source = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError(f"Could not read image while estimating aperture: {path}")
        green = source[:, :, 1].astype(np.float32)
        if expected_shape is None:
            expected_shape = green.shape
        elif green.shape != expected_shape:
            raise ValueError("All images must have the same dimensions to estimate the aperture")
        smooth = cv2.GaussianBlur(green, (0, 0), 3.0)
        gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
        gradients.append(cv2.magnitude(gx, gy))

    aggregate = np.percentile(np.stack(gradients), 40, axis=0)
    high = float(np.percentile(aggregate, 99.5))
    normalized = np.clip(aggregate * (255.0 / max(high, 1e-6)), 0, 255).astype(np.uint8)
    normalized = cv2.GaussianBlur(normalized, (0, 0), 3.0)
    height, width = normalized.shape
    minimum_radius = int(round(min(height, width) * 0.60))
    maximum_radius = int(round(min(height, width) * 0.85))
    circles = cv2.HoughCircles(
        normalized,
        cv2.HOUGH_GRADIENT,
        dp=1.5,
        minDist=min(height, width) * 0.3,
        param1=30,
        param2=80,
        minRadius=minimum_radius,
        maxRadius=maximum_radius,
    )
    if circles is None:
        raise ValueError("Could not estimate the circular microscope aperture")
    initial = np.asarray(circles[0, 0], dtype=np.float64)

    yy, xx = np.indices(aggregate.shape)
    distance = np.hypot(xx - initial[0], yy - initial[1])
    annulus = np.abs(distance - initial[2]) <= 25.0
    edge_threshold = float(np.percentile(aggregate[annulus], 85))
    keep = (
        annulus
        & (aggregate >= edge_threshold)
        & (xx >= 5)
        & (xx < width - 5)
        & (yy >= 5)
        & (yy < height - 5)
    )
    fit_x = xx[keep][::2].astype(np.float64)
    fit_y = yy[keep][::2].astype(np.float64)
    if fit_x.size < 100:
        return tuple(float(value) for value in initial)

    def residual(parameters: np.ndarray) -> np.ndarray:
        return np.hypot(fit_x - parameters[0], fit_y - parameters[1]) - parameters[2]

    fitted = least_squares(
        residual,
        initial,
        loss="soft_l1",
        f_scale=2.0,
        max_nfev=100,
    ).x
    return tuple(float(value) for value in fitted)


def estimate_aperture_margin(
    image_paths: list[Path], aperture_circle: tuple[float, float, float]
) -> float:
    """Estimate the vignette-safe inset from repeated channel cutoff radii."""
    center_x, center_y, outer_radius = aperture_circle
    contour_radii: list[np.ndarray] = []
    for path in image_paths:
        source = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError(f"Could not read image while estimating vignette: {path}")
        mask, _threshold = _largest_bright_component(source[:, :, 1])
        contours, _hierarchy = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        if not contours:
            continue
        points = max(contours, key=cv2.contourArea).reshape(-1, 2)
        contour_radii.append(
            np.hypot(points[:, 0] - center_x, points[:, 1] - center_y)
        )
    if not contour_radii:
        raise ValueError("No channel contours were available to estimate vignetting")
    radii = np.concatenate(contour_radii)
    search_low = outer_radius * 0.70
    search_high = outer_radius * 0.90
    edges = np.arange(math.floor(search_low), math.ceil(search_high) + 2.0, 2.0)
    histogram, edges = np.histogram(radii, bins=edges)
    if histogram.size == 0 or int(histogram.max(initial=0)) < 20:
        raise ValueError("Could not identify the repeated inner vignette cutoff")
    peak_index = int(np.argmax(gaussian_filter1d(histogram.astype(np.float64), 1.0)))
    inner_cutoff_radius = 0.5 * (float(edges[peak_index]) + float(edges[peak_index + 1]))
    usable_radius = inner_cutoff_radius - 5.0
    margin = outer_radius - usable_radius
    return float(np.clip(margin, 50.0, 150.0))


def _largest_bright_component(green: np.ndarray) -> tuple[np.ndarray, float]:
    blurred = cv2.GaussianBlur(green, (0, 0), 2.0)
    threshold, binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    if count <= 1:
        raise ValueError("No bright channel component was detected")
    component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (labels == component).astype(np.uint8) * 255
    if int(np.count_nonzero(mask)) < 1000:
        raise ValueError("Detected channel component is too small")
    return mask, float(threshold)


def _valid_geometry_mask(
    shape: tuple[int, int],
    *,
    aperture_circle: tuple[float, float, float] | None,
    aperture_margin_px: float,
    image_border_margin_px: float,
) -> np.ndarray:
    height, width = shape
    yy, xx = np.indices(shape)
    valid = (
        (xx >= image_border_margin_px)
        & (xx <= width - 1 - image_border_margin_px)
        & (yy >= image_border_margin_px)
        & (yy <= height - 1 - image_border_margin_px)
    )
    if aperture_circle is not None:
        center_x, center_y, radius = aperture_circle
        safe_radius = radius - aperture_margin_px
        if safe_radius <= 0:
            raise ValueError("aperture_margin_px leaves no valid aperture area")
        valid &= np.hypot(xx - center_x, yy - center_y) <= safe_radius
    return valid


def _pca_axes(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    y, x = np.nonzero(mask)
    points = np.column_stack((x, y)).astype(np.float64)
    origin = points.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(points - origin, rowvar=False))
    major = eigenvectors[:, int(np.argmax(eigenvalues))]
    if major[0] < 0 or (abs(float(major[0])) < 1e-9 and major[1] < 0):
        major = -major
    minor = np.array([-major[1], major[0]], dtype=np.float64)
    return origin, major, minor, points


def _wall_observations(
    mask: np.ndarray,
    origin_xy: np.ndarray,
    major_axis_xy: np.ndarray,
    minor_axis_xy: np.ndarray,
    valid_geometry: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    y, x = np.nonzero(mask)
    points_xy = np.column_stack((x, y)).astype(np.float64)
    centered = points_xy - origin_xy
    along = centered @ major_axis_xy
    across = centered @ minor_axis_xy
    bins = np.floor(along).astype(np.int32)
    order = np.argsort(bins, kind="stable")
    sorted_bins = bins[order]
    sorted_across = across[order]
    unique_bins, starts, counts = np.unique(
        sorted_bins, return_index=True, return_counts=True
    )
    first = np.minimum.reduceat(sorted_across, starts)
    second = np.maximum.reduceat(sorted_across, starts)
    keep = counts >= 3
    along_centers = unique_bins[keep].astype(np.float64) + 0.5
    first = first[keep]
    second = second[keep]
    first_xy = (
        origin_xy[None, :]
        + along_centers[:, None] * major_axis_xy[None, :]
        + first[:, None] * minor_axis_xy[None, :]
    )
    second_xy = (
        origin_xy[None, :]
        + along_centers[:, None] * major_axis_xy[None, :]
        + second[:, None] * minor_axis_xy[None, :]
    )
    height, width = mask.shape
    first_indices = np.rint(first_xy).astype(np.int32)
    second_indices = np.rint(second_xy).astype(np.int32)
    first_inside = (
        (first_indices[:, 0] >= 0)
        & (first_indices[:, 0] < width)
        & (first_indices[:, 1] >= 0)
        & (first_indices[:, 1] < height)
    )
    second_inside = (
        (second_indices[:, 0] >= 0)
        & (second_indices[:, 0] < width)
        & (second_indices[:, 1] >= 0)
        & (second_indices[:, 1] < height)
    )
    first_valid = first_inside.copy()
    second_valid = second_inside.copy()
    first_valid[first_inside] &= valid_geometry[
        first_indices[first_inside, 1], first_indices[first_inside, 0]
    ]
    second_valid[second_inside] &= valid_geometry[
        second_indices[second_inside, 1], second_indices[second_inside, 0]
    ]
    return (
        along_centers[first_valid],
        first[first_valid],
        along_centers[second_valid],
        second[second_valid],
    )


def _fit_wall_model(
    observation_along: np.ndarray,
    observation_across: np.ndarray,
    model_along: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if observation_along.size < 30:
        raise ValueError("Too few valid observations remain for a wall model")
    order = np.argsort(observation_along)
    observation_along = observation_along[order]
    observation_across = observation_across[order]
    midpoint = 0.5 * (float(model_along[0]) + float(model_along[-1]))
    scale = max(1.0, 0.5 * (float(model_along[-1]) - float(model_along[0])))
    scaled_observation = (observation_along - midpoint) / scale
    scaled_model = (model_along - midpoint) / scale
    initial_coefficients = np.polyfit(scaled_observation, observation_across, 3)
    coefficients = least_squares(
        lambda candidate: np.polyval(candidate, scaled_observation) - observation_across,
        initial_coefficients,
        loss="soft_l1",
        f_scale=2.0,
        max_nfev=200,
    ).x
    model = np.polyval(coefficients, scaled_model)
    slope = np.gradient(model, model_along)
    residual = observation_across - np.interp(observation_along, model_along, model)
    local_slope = np.interp(observation_along, model_along, slope)
    normal_residual = residual / np.sqrt(1.0 + (local_slope * local_slope))
    return model, normal_residual


def _intersect_wall_with_normal(
    *,
    center_xy: np.ndarray,
    tangent_xy: np.ndarray,
    origin_xy: np.ndarray,
    major_axis_xy: np.ndarray,
    minor_axis_xy: np.ndarray,
    wall_along: np.ndarray,
    wall_across: np.ndarray,
    near_along: float,
) -> np.ndarray:
    wall_xy = (
        origin_xy[None, :]
        + wall_along[:, None] * major_axis_xy[None, :]
        + wall_across[:, None] * minor_axis_xy[None, :]
    )
    signed_tangent_distance = (wall_xy - center_xy[None, :]) @ tangent_xy
    crossings = np.flatnonzero(
        signed_tangent_distance[:-1] * signed_tangent_distance[1:] <= 0.0
    )
    if crossings.size == 0:
        raise ValueError("Centerline normal did not intersect a wall model")
    index = int(crossings[np.argmin(np.abs(wall_along[crossings] - near_along))])
    left_value = float(signed_tangent_distance[index])
    right_value = float(signed_tangent_distance[index + 1])
    denominator = left_value - right_value
    fraction = 0.5 if abs(denominator) < 1e-12 else left_value / denominator
    return wall_xy[index] + float(np.clip(fraction, 0.0, 1.0)) * (
        wall_xy[index + 1] - wall_xy[index]
    )


def analyze_image(
    source_bgr: np.ndarray,
    *,
    micrometers_per_pixel: float = 0.771,
    end_trim_fraction: float = 0.15,
    sample_spacing_px: float = 10.0,
    aperture_circle: tuple[float, float, float] | None = None,
    aperture_margin_px: float = 110.0,
    image_border_margin_px: float = 6.0,
) -> ChannelAnalysis:
    if source_bgr is None or source_bgr.ndim != 3 or source_bgr.shape[2] != 3:
        raise ValueError("Expected a BGR color image")
    if not math.isfinite(micrometers_per_pixel) or micrometers_per_pixel <= 0:
        raise ValueError("micrometers_per_pixel must be positive and finite")
    if not 0.0 <= end_trim_fraction < 0.45:
        raise ValueError("end_trim_fraction must be between 0 and 0.45")
    if sample_spacing_px <= 0:
        raise ValueError("sample_spacing_px must be positive")
    if aperture_margin_px < 0 or image_border_margin_px < 0:
        raise ValueError("geometry exclusion margins cannot be negative")

    green = source_bgr[:, :, 1]
    mask, threshold = _largest_bright_component(green)
    valid_geometry = _valid_geometry_mask(
        green.shape,
        aperture_circle=aperture_circle,
        aperture_margin_px=aperture_margin_px,
        image_border_margin_px=image_border_margin_px,
    )
    fit_mask = ((mask > 0) & valid_geometry).astype(np.uint8) * 255
    if int(np.count_nonzero(fit_mask)) < 1000:
        raise ValueError("Too little channel area remains after aperture exclusion")
    origin, major, minor, _fit_points = _pca_axes(fit_mask)
    first_a, first_v, second_a, second_v = _wall_observations(
        mask, origin, major, minor, valid_geometry
    )
    overlap_start = max(float(first_a.min()), float(second_a.min()))
    overlap_end = min(float(first_a.max()), float(second_a.max()))
    if overlap_end - overlap_start < 100.0:
        raise ValueError("The two valid wall sections overlap by less than 100 pixels")
    first_keep = (first_a >= overlap_start) & (first_a <= overlap_end)
    second_keep = (second_a >= overlap_start) & (second_a <= overlap_end)
    first_a, first_v = first_a[first_keep], first_v[first_keep]
    second_a, second_v = second_a[second_keep], second_v[second_keep]
    along = np.arange(
        math.ceil(overlap_start), math.floor(overlap_end) + 1, dtype=np.float64
    )
    first_wall, first_residual = _fit_wall_model(first_a, first_v, along)
    second_wall, second_residual = _fit_wall_model(second_a, second_v, along)
    center = 0.5 * (first_wall + second_wall)
    slope = np.gradient(center, along)

    accepted_start, accepted_end = np.quantile(along, [end_trim_fraction, 1.0 - end_trim_fraction])
    requested_along = np.arange(
        math.ceil(float(accepted_start)),
        math.floor(float(accepted_end)) + 0.1,
        sample_spacing_px,
    )
    samples: list[WidthSample] = []
    for position in requested_along:
        local_center = float(np.interp(position, along, center))
        local_slope = float(np.interp(position, along, slope))
        tangent = major + (local_slope * minor)
        tangent /= np.linalg.norm(tangent)
        normal = (-local_slope * major) + minor
        normal /= np.linalg.norm(normal)
        center_xy = origin + (position * major) + (local_center * minor)
        try:
            first_xy = _intersect_wall_with_normal(
                center_xy=center_xy,
                tangent_xy=tangent,
                origin_xy=origin,
                major_axis_xy=major,
                minor_axis_xy=minor,
                wall_along=along,
                wall_across=first_wall,
                near_along=position,
            )
            second_xy = _intersect_wall_with_normal(
                center_xy=center_xy,
                tangent_xy=tangent,
                origin_xy=origin,
                major_axis_xy=major,
                minor_axis_xy=minor,
                wall_along=along,
                wall_across=second_wall,
                near_along=position,
            )
        except ValueError:
            continue
        wall_xy = np.vstack((first_xy, second_xy))
        wall_indices = np.rint(wall_xy).astype(np.int32)
        image_height, image_width = green.shape
        inside = (
            (wall_indices[:, 0] >= 0)
            & (wall_indices[:, 0] < image_width)
            & (wall_indices[:, 1] >= 0)
            & (wall_indices[:, 1] < image_height)
        )
        if not np.all(inside) or not np.all(
            valid_geometry[wall_indices[:, 1], wall_indices[:, 0]]
        ):
            continue
        measured_width = float(np.linalg.norm(second_xy - first_xy))
        if measured_width <= 10.0:
            continue
        samples.append(
            WidthSample(
                along_px=float(position),
                center_xy=center_xy,
                tangent_xy=tangent,
                normal_xy=normal,
                first_wall_xy=first_xy,
                second_wall_xy=second_xy,
                width_px=measured_width,
            )
        )

    if len(samples) < 10:
        raise ValueError(f"Only {len(samples)} valid perpendicular measurements were found")
    return ChannelAnalysis(
        source_bgr=source_bgr,
        green=green,
        mask=mask,
        threshold=threshold,
        origin_xy=origin,
        major_axis_xy=major,
        minor_axis_xy=minor,
        along_px=along,
        first_wall_across_px=first_wall,
        second_wall_across_px=second_wall,
        center_across_px=center,
        center_slope=slope,
        accepted_along_range_px=(float(accepted_start), float(accepted_end)),
        first_observation_along_px=first_a,
        first_observation_across_px=first_v,
        second_observation_along_px=second_a,
        second_observation_across_px=second_v,
        first_wall_residual_px=first_residual,
        second_wall_residual_px=second_residual,
        aperture_circle=aperture_circle,
        aperture_margin_px=float(aperture_margin_px),
        samples=samples,
        micrometers_per_pixel=float(micrometers_per_pixel),
    )


def analyze_file(
    image_path: Path,
    *,
    micrometers_per_pixel: float = 0.771,
    end_trim_fraction: float = 0.15,
    sample_spacing_px: float = 10.0,
    aperture_circle: tuple[float, float, float] | None = None,
    aperture_margin_px: float = 110.0,
    image_border_margin_px: float = 6.0,
) -> ChannelAnalysis:
    source = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError(f"Could not read image: {image_path}")
    return analyze_image(
        source,
        micrometers_per_pixel=micrometers_per_pixel,
        end_trim_fraction=end_trim_fraction,
        sample_spacing_px=sample_spacing_px,
        aperture_circle=aperture_circle,
        aperture_margin_px=aperture_margin_px,
        image_border_margin_px=image_border_margin_px,
    )


def _curve_points(analysis: ChannelAnalysis, across: np.ndarray) -> np.ndarray:
    points = (
        analysis.origin_xy[None, :]
        + analysis.along_px[:, None] * analysis.major_axis_xy[None, :]
        + across[:, None] * analysis.minor_axis_xy[None, :]
    )
    return np.rint(points).astype(np.int32).reshape(-1, 1, 2)


def _observation_points(
    analysis: ChannelAnalysis, along: np.ndarray, across: np.ndarray
) -> np.ndarray:
    points = (
        analysis.origin_xy[None, :]
        + along[:, None] * analysis.major_axis_xy[None, :]
        + across[:, None] * analysis.minor_axis_xy[None, :]
    )
    return np.rint(points).astype(np.int32)


def _dimmed(image: np.ndarray, factor: float = 0.62) -> np.ndarray:
    return np.clip(image.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def _tile(image: np.ndarray, title: str, subtitle: str) -> np.ndarray:
    tile = cv2.resize(image, (800, 450), interpolation=cv2.INTER_AREA)
    overlay = tile.copy()
    cv2.rectangle(overlay, (0, 0), (800, 62), (0, 0, 0), -1)
    tile = cv2.addWeighted(overlay, 0.76, tile, 0.24, 0)
    cv2.putText(tile, title, (16, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(tile, subtitle, (16, 51), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (220, 220, 220), 1, cv2.LINE_AA)
    return tile


def render_stages(analysis: ChannelAnalysis, *, image_name: str) -> np.ndarray:
    source = analysis.source_bgr
    panel1 = source.copy()

    panel2 = cv2.cvtColor(analysis.green, cv2.COLOR_GRAY2BGR)
    tint = np.zeros_like(panel2)
    tint[:, :, 1] = analysis.mask
    panel2 = cv2.addWeighted(panel2, 0.55, tint, 0.45, 0)
    contours, _hierarchy = cv2.findContours(
        analysis.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(panel2, contours, -1, (0, 255, 255), 2, cv2.LINE_AA)
    if analysis.aperture_circle is not None:
        center_x, center_y, radius = analysis.aperture_circle
        center = (int(round(center_x)), int(round(center_y)))
        cv2.circle(panel2, center, int(round(radius)), (0, 0, 255), 3, cv2.LINE_AA)
        cv2.circle(
            panel2,
            center,
            int(round(radius - analysis.aperture_margin_px)),
            (0, 140, 255),
            3,
            cv2.LINE_AA,
        )

    first_curve = _curve_points(analysis, analysis.first_wall_across_px)
    second_curve = _curve_points(analysis, analysis.second_wall_across_px)
    center_curve = _curve_points(analysis, analysis.center_across_px)
    panel3 = _dimmed(source)
    first_observations = _observation_points(
        analysis,
        analysis.first_observation_along_px,
        analysis.first_observation_across_px,
    )
    second_observations = _observation_points(
        analysis,
        analysis.second_observation_along_px,
        analysis.second_observation_across_px,
    )
    for point in first_observations[::3]:
        cv2.circle(panel3, tuple(point), 2, (180, 40, 180), -1, cv2.LINE_AA)
    for point in second_observations[::3]:
        cv2.circle(panel3, tuple(point), 2, (180, 180, 0), -1, cv2.LINE_AA)
    cv2.polylines(panel3, [first_curve], False, (255, 80, 255), 4, cv2.LINE_AA)
    cv2.polylines(panel3, [second_curve], False, (255, 255, 0), 4, cv2.LINE_AA)
    sample_along = np.asarray([sample.along_px for sample in analysis.samples])
    spacing = float(np.median(np.diff(sample_along))) if len(sample_along) > 1 else 10.0
    distance_to_sample = np.min(
        np.abs(analysis.along_px[:, None] - sample_along[None, :]), axis=1
    )
    accepted = distance_to_sample <= max(1.0, spacing * 0.55)
    for keep, color in ((~accepted, (0, 140, 255)), (accepted, (80, 255, 80))):
        indices = np.flatnonzero(keep)
        if indices.size > 1:
            breaks = np.flatnonzero(np.diff(indices) > 1) + 1
            for run in np.split(indices, breaks):
                if run.size > 1:
                    cv2.polylines(panel3, [center_curve[run]], False, color, 4, cv2.LINE_AA)

    panel4 = _dimmed(source, 0.72)
    accepted_center = center_curve[accepted]
    if len(accepted_center) > 1:
        cv2.polylines(panel4, [accepted_center], False, (80, 255, 80), 3, cv2.LINE_AA)
    stride = max(1, math.ceil(len(analysis.samples) / 24))
    for sample in analysis.samples[::stride]:
        first = tuple(np.rint(sample.first_wall_xy).astype(int))
        second = tuple(np.rint(sample.second_wall_xy).astype(int))
        cv2.line(panel4, first, second, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(panel4, first, 4, (255, 80, 255), -1, cv2.LINE_AA)
        cv2.circle(panel4, second, 4, (255, 255, 0), -1, cv2.LINE_AA)

    used_percent = 100.0 * float(np.count_nonzero(accepted)) / len(accepted)
    tiles = [
        _tile(panel1, f"1. Original - {image_name}", "RGB source; colored fringes are optical chromatic aberration"),
        _tile(panel2, "2. Segmentation and aperture exclusion", f"Yellow: raw channel | red: aperture | orange: {analysis.aperture_margin_px:.0f} px safe boundary"),
        _tile(panel3, "3. Raw walls and robust cubic models", f"Dots: valid raw walls | lines: global cubic fits | green: measured center ({used_percent:.0f}%)"),
        _tile(panel4, "4. Model-to-model perpendicular widths", f"Median {analysis.median_width_um:.1f} um | IQR {analysis.width_iqr_um:.1f} um | normal bend P95 {analysis.normal_angle_bend_p95_deg:.2f} deg"),
    ]
    return np.vstack((np.hstack(tiles[:2]), np.hstack(tiles[2:])))


def _image_paths(input_directories: list[Path]) -> list[tuple[Path, Path]]:
    paths: list[tuple[Path, Path]] = []
    for directory in input_directories:
        if not directory.is_dir():
            raise ValueError(f"Input directory does not exist: {directory}")
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                paths.append((directory, path))
    return paths


def run_analysis(
    input_directories: list[Path],
    output_directory: Path,
    *,
    micrometers_per_pixel: float,
    end_trim_fraction: float,
    sample_spacing_px: float,
    aperture_circle: tuple[float, float, float] | None = None,
    aperture_margin_px: float | None = None,
    image_border_margin_px: float = 6.0,
) -> list[dict[str, object]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, object]] = []
    sample_rows: list[dict[str, object]] = []
    wall_rows: list[dict[str, object]] = []
    paths = _image_paths(input_directories)
    image_paths = [path for _directory, path in paths]
    if aperture_circle is None:
        aperture_circle = estimate_aperture(image_paths)
    if aperture_margin_px is None:
        aperture_margin_px = estimate_aperture_margin(image_paths, aperture_circle)
    print(
        "Estimated aperture: "
        f"center=({aperture_circle[0]:.1f}, {aperture_circle[1]:.1f}), "
        f"radius={aperture_circle[2]:.1f} px, usable inset={aperture_margin_px:.1f} px"
    )
    for input_directory, image_path in paths:
        analysis = analyze_file(
            image_path,
            micrometers_per_pixel=micrometers_per_pixel,
            end_trim_fraction=end_trim_fraction,
            sample_spacing_px=sample_spacing_px,
            aperture_circle=aperture_circle,
            aperture_margin_px=aperture_margin_px,
            image_border_margin_px=image_border_margin_px,
        )
        group = input_directory.name
        group_output = output_directory / group
        group_output.mkdir(parents=True, exist_ok=True)
        annotated_path = group_output / f"{image_path.stem}_analysis.png"
        cv2.imwrite(str(annotated_path), render_stages(analysis, image_name=image_path.name))
        summary_rows.append(
            {
                "group": group,
                "image": image_path.name,
                "threshold_green": analysis.threshold,
                "sample_count": len(analysis.samples),
                "median_width_px": analysis.median_width_px,
                "width_iqr_px": analysis.width_iqr_px,
                "median_width_um": analysis.median_width_um,
                "width_iqr_um": analysis.width_iqr_um,
                "wall_rms_um": analysis.wall_rms_um,
                "wall_p95_um": analysis.wall_p95_um,
                "first_wall_rms_um": analysis.first_wall_rms_um,
                "first_wall_p95_um": analysis.first_wall_p95_um,
                "second_wall_rms_um": analysis.second_wall_rms_um,
                "second_wall_p95_um": analysis.second_wall_p95_um,
                "normal_angle_range_deg": analysis.normal_angle_range_deg,
                "normal_angle_step_p95_deg": analysis.normal_angle_step_p95_deg,
                "normal_angle_bend_p95_deg": analysis.normal_angle_bend_p95_deg,
                "aperture_center_x_px": aperture_circle[0],
                "aperture_center_y_px": aperture_circle[1],
                "aperture_radius_px": aperture_circle[2],
                "aperture_margin_px": aperture_margin_px,
                "micrometers_per_pixel": micrometers_per_pixel,
                "annotated_image": str(annotated_path),
            }
        )
        for index, sample in enumerate(analysis.samples, start=1):
            sample_rows.append(
                {
                    "group": group,
                    "image": image_path.name,
                    "sample_index": index,
                    "center_x_px": float(sample.center_xy[0]),
                    "center_y_px": float(sample.center_xy[1]),
                    "first_wall_x_px": float(sample.first_wall_xy[0]),
                    "first_wall_y_px": float(sample.first_wall_xy[1]),
                    "second_wall_x_px": float(sample.second_wall_xy[0]),
                    "second_wall_y_px": float(sample.second_wall_xy[1]),
                    "width_px": sample.width_px,
                    "width_um": sample.width_px * micrometers_per_pixel,
                }
            )
        for wall_name, wall_along, wall_across, wall_residual in (
            (
                "first",
                analysis.first_observation_along_px,
                analysis.first_observation_across_px,
                analysis.first_wall_residual_px,
            ),
            (
                "second",
                analysis.second_observation_along_px,
                analysis.second_observation_across_px,
                analysis.second_wall_residual_px,
            ),
        ):
            observation_xy = _observation_points(analysis, wall_along, wall_across)
            for index, (along, point, residual) in enumerate(
                zip(wall_along, observation_xy, wall_residual), start=1
            ):
                wall_rows.append(
                    {
                        "group": group,
                        "image": image_path.name,
                        "wall": wall_name,
                        "observation_index": index,
                        "along_px": float(along),
                        "x_px": int(point[0]),
                        "y_px": int(point[1]),
                        "normal_residual_px": float(residual),
                        "normal_residual_um": float(residual) * micrometers_per_pixel,
                    }
                )

    for filename, rows in (
        ("summary.csv", summary_rows),
        ("width_samples.csv", sample_rows),
        ("wall_residuals.csv", wall_rows),
    ):
        if not rows:
            continue
        with (output_directory / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return summary_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure curved microscope channels and create staged diagnostic overlays."
    )
    parser.add_argument("input_directories", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--micrometers-per-pixel", type=float, default=0.771)
    parser.add_argument("--end-trim-fraction", type=float, default=0.15)
    parser.add_argument("--sample-spacing-px", type=float, default=10.0)
    parser.add_argument(
        "--aperture-circle",
        type=float,
        nargs=3,
        metavar=("CENTER_X", "CENTER_Y", "RADIUS"),
        help="Explicit microscope aperture; otherwise estimated from all input images.",
    )
    parser.add_argument(
        "--aperture-margin-px",
        type=float,
        help="Explicit inward vignette margin; otherwise estimated from all inputs.",
    )
    parser.add_argument("--image-border-margin-px", type=float, default=6.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = run_analysis(
        args.input_directories,
        args.output_dir,
        micrometers_per_pixel=args.micrometers_per_pixel,
        end_trim_fraction=args.end_trim_fraction,
        sample_spacing_px=args.sample_spacing_px,
        aperture_circle=None if args.aperture_circle is None else tuple(args.aperture_circle),
        aperture_margin_px=args.aperture_margin_px,
        image_border_margin_px=args.image_border_margin_px,
    )
    for row in rows:
        print(
            f"{row['group']}/{row['image']}: "
            f"{row['median_width_um']:.1f} um "
            f"(IQR {row['width_iqr_um']:.1f} um, "
            f"wall RMS {row['wall_rms_um']:.1f} um, n={row['sample_count']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
