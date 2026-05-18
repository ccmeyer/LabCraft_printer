from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

import cv2
import numpy as np

try:
    from scipy.signal import find_peaks
except Exception:  # pragma: no cover - scipy is a project dependency, keep import robust.
    find_peaks = None


IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def _positive_float(value, *, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"{name} must be a positive finite value")
    return out


def _deskew_foreground(binary: np.ndarray) -> tuple[np.ndarray, float]:
    points = cv2.findNonZero(binary)
    if points is None or len(points) < 20:
        return binary, 0.0

    coords = points.reshape(-1, 2).astype(np.float32)
    coords -= coords.mean(axis=0)
    _eigvals, eigvecs = np.linalg.eigh(np.cov(coords.T))
    vx, vy = eigvecs[:, -1]
    angle = math.degrees(math.atan2(float(vy), float(vx)))
    while angle > 45.0:
        angle -= 90.0
    while angle < -45.0:
        angle += 90.0
    if abs(angle) > 20.0:
        return binary, 0.0
    if abs(angle) < 0.05:
        return binary, 0.0

    h, w = binary.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -angle, 1.0)
    rotated = cv2.warpAffine(
        binary,
        matrix,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return rotated, float(angle)


def _crop_foreground_band(binary: np.ndarray) -> np.ndarray:
    row_counts = binary.sum(axis=1).astype(np.float32) / 255.0
    if row_counts.size == 0 or float(row_counts.max(initial=0.0)) <= 0.0:
        return binary

    kernel_width = max(5, min(81, int(round(binary.shape[0] * 0.06)) | 1))
    smooth = cv2.GaussianBlur(row_counts.reshape(-1, 1), (1, kernel_width), 0).ravel()
    threshold = max(3.0, float(smooth.max()) * 0.20)
    rows = np.flatnonzero(smooth >= threshold)
    if rows.size == 0:
        return binary

    top = max(0, int(rows[0]) - 6)
    bottom = min(binary.shape[0], int(rows[-1]) + 7)
    if bottom <= top:
        return binary
    return binary[top:bottom, :]


def _local_contrast_binary(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape[:2]
    sigma = max(9.0, min(h, w) * 0.035)
    background = cv2.GaussianBlur(gray, (0, 0), sigma)
    contrast = cv2.absdiff(gray, background)
    threshold = max(12.0, float(np.percentile(contrast, 98.7)))
    binary = (contrast >= threshold).astype(np.uint8) * 255
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)


def _find_tick_peaks(column_signal: np.ndarray, *, min_spacing_px: int | None = None) -> np.ndarray:
    if column_signal.size < 3:
        return np.array([], dtype=int)

    signal = column_signal.astype(np.float32)
    if float(signal.max(initial=0.0)) <= 0.0:
        return np.array([], dtype=int)

    kernel_width = max(3, min(21, int(round(signal.size * 0.006)) | 1))
    smooth = cv2.GaussianBlur(signal.reshape(1, -1), (kernel_width, 1), 0).ravel()
    distance = int(min_spacing_px or max(3, round(signal.size * 0.003)))
    height = max(3.0, float(np.percentile(smooth, 85)) * 0.45, float(smooth.max()) * 0.18)

    if find_peaks is not None:
        peaks, _props = find_peaks(smooth, height=height, distance=distance, prominence=max(1.0, height * 0.25))
        return peaks.astype(int)

    # Small fallback for environments without scipy.
    peaks = []
    for idx in range(1, len(smooth) - 1):
        if smooth[idx] >= height and smooth[idx] >= smooth[idx - 1] and smooth[idx] > smooth[idx + 1]:
            if peaks and (idx - peaks[-1]) < distance:
                if smooth[idx] > smooth[peaks[-1]]:
                    peaks[-1] = idx
            else:
                peaks.append(idx)
    return np.asarray(peaks, dtype=int)


def _robust_spacing(peaks: np.ndarray) -> tuple[list[float], list[float]]:
    if peaks.size < 2:
        return [], []
    raw = np.diff(np.sort(peaks)).astype(float)
    raw = raw[raw > 0]
    if raw.size == 0:
        return [], []

    med = float(np.median(raw))
    mad = float(np.median(np.abs(raw - med)))
    if mad <= 1e-9:
        keep = np.abs(raw - med) <= max(2.0, med * 0.20)
    else:
        keep = np.abs(raw - med) <= max(2.5 * mad, med * 0.20)
    filtered = raw[keep]
    if filtered.size < max(2, raw.size // 3):
        filtered = raw
    return [float(x) for x in filtered], [float(x) for x in raw]


def _analyze_binary_scale_bar(
    image_path: Path,
    gray: np.ndarray,
    binary: np.ndarray,
    *,
    division_um: float,
    mask_source: str,
) -> dict:
    binary, angle_deg = _deskew_foreground(binary)
    band = _crop_foreground_band(binary)

    col_counts = band.sum(axis=0).astype(np.float32) / 255.0
    peaks = _find_tick_peaks(col_counts)
    spacings_px, raw_spacings_px = _robust_spacing(peaks)
    if len(spacings_px) < 2:
        return {
            "path": str(image_path),
            "filename": image_path.name,
            "status": "error",
            "error": "not_enough_tick_spacing",
            "division_um": float(division_um),
            "mask_source": mask_source,
            "peak_count": int(len(peaks)),
            "peaks_px": [int(x) for x in peaks.tolist()],
            "raw_spacings_px": raw_spacings_px,
            "rotation_deg": float(angle_deg),
        }

    spacing_px = float(np.mean(spacings_px))
    spacing_std = float(np.std(spacings_px, ddof=1)) if len(spacings_px) > 1 else 0.0
    um_per_pixel = float(division_um / spacing_px)
    return {
        "path": str(image_path),
        "filename": image_path.name,
        "status": "ok",
        "division_um": float(division_um),
        "mask_source": mask_source,
        "um_per_pixel": um_per_pixel,
        "spacing_px": spacing_px,
        "spacing_px_median": float(median(spacings_px)),
        "spacing_px_mean": float(np.mean(spacings_px)),
        "spacing_px_std": spacing_std,
        "spacing_px_cv_pct": float((spacing_std / spacing_px) * 100.0) if spacing_px else 0.0,
        "spacing_count": int(len(spacings_px)),
        "peak_count": int(len(peaks)),
        "peaks_px": [int(x) for x in peaks.tolist()],
        "raw_spacings_px": raw_spacings_px,
        "accepted_spacings_px": spacings_px,
        "rotation_deg": float(angle_deg),
        "image_shape": [int(gray.shape[0]), int(gray.shape[1])],
    }


def analyze_scale_bar_image(path: str | Path, division_um: float = 10.0) -> dict:
    """Measure one micrometer image and return a JSON-serializable result."""
    image_path = Path(path)
    division_um = _positive_float(division_um, name="division_um")
    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return {
            "path": str(image_path),
            "filename": image_path.name,
            "status": "error",
            "error": "image_read_failed",
        }
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    local_binary = _local_contrast_binary(gray)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _threshold, dark_binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    dark_binary = cv2.morphologyEx(dark_binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)

    candidates = [
        _analyze_binary_scale_bar(
            image_path,
            gray,
            local_binary,
            division_um=division_um,
            mask_source="local_contrast",
        ),
        _analyze_binary_scale_bar(
            image_path,
            gray,
            dark_binary,
            division_um=division_um,
            mask_source="dark_otsu",
        ),
    ]
    valid = [row for row in candidates if row.get("status") == "ok"]
    if not valid:
        return candidates[0]

    def _candidate_score(row):
        return (
            float(row.get("spacing_px_cv_pct") or 999.0),
            -int(row.get("spacing_count") or 0),
        )

    return sorted(valid, key=_candidate_score)[0]


def _aggregate_results(results: list[dict], *, division_um: float, directory: Path) -> dict:
    accepted = [row for row in results if row.get("status") == "ok" and row.get("um_per_pixel") is not None]
    values = np.asarray([float(row["um_per_pixel"]) for row in accepted], dtype=float)
    if values.size == 0:
        return {
            "status": "error",
            "error": "no_valid_images",
            "division_um": float(division_um),
            "run_directory": str(directory),
            "image_count": int(len(results)),
            "accepted_count": 0,
            "rejected_count": int(sum(1 for row in results if row.get("status") == "rejected")),
            "failed_count": int(sum(1 for row in results if row.get("status") == "error")),
        }

    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    cv_pct = float((std / mean) * 100.0) if mean else 0.0
    return {
        "status": "ok",
        "division_um": float(division_um),
        "run_directory": str(directory),
        "image_count": int(len(results)),
        "accepted_count": int(values.size),
        "rejected_count": int(sum(1 for row in results if row.get("status") == "rejected")),
        "failed_count": int(sum(1 for row in results if row.get("status") == "error")),
        "mean_um_per_pixel": mean,
        "median_um_per_pixel": float(np.median(values)),
        "std_um_per_pixel": std,
        "cv_pct": cv_pct,
        "min_um_per_pixel": float(np.min(values)),
        "max_um_per_pixel": float(np.max(values)),
    }


def analyze_scale_bar_directory(
    path: str | Path,
    division_um: float = 10.0,
    rejected_filenames: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Analyze every image in a directory and return per-image and aggregate results."""
    directory = Path(path)
    division_um = _positive_float(division_um, name="division_um")
    rejected = {str(name) for name in (rejected_filenames or [])}
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Scale-bar directory does not exist: {directory}")

    results = []
    for image_path in sorted(p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS):
        if image_path.name in rejected:
            results.append(
                {
                    "path": str(image_path),
                    "filename": image_path.name,
                    "status": "rejected",
                    "error": "rejected_by_manifest",
                    "division_um": float(division_um),
                }
            )
            continue
        results.append(analyze_scale_bar_image(image_path, division_um=division_um))

    summary = _aggregate_results(results, division_um=division_um, directory=directory)
    return {
        "schema_version": 1,
        "status": summary.get("status", "error"),
        "summary": summary,
        "results": results,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze micrometer scale-bar images.")
    parser.add_argument("path", help="Image file or directory containing scale-bar images.")
    parser.add_argument("--division-um", type=float, default=10.0, help="Micrometer spacing per division.")
    parser.add_argument("--reject", action="append", default=[], help="Filename to ignore. May be repeated.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_path = Path(args.path)
    if input_path.is_dir():
        payload = analyze_scale_bar_directory(
            input_path,
            division_um=float(args.division_um),
            rejected_filenames=set(args.reject or []),
        )
    else:
        payload = analyze_scale_bar_image(input_path, division_um=float(args.division_um))

    text = json.dumps(payload, indent=2, default=_json_default)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
