#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from CalibrationClasses.Model import DropletCameraModel


def _camera_stub():
    cam = DropletCameraModel.__new__(DropletCameraModel)
    cam._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cam._last_droplet_center_px = None
    return cam


def _percentile(values, p):
    if not values:
        return None
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    idx = (len(vals) - 1) * float(p)
    lo = int(np.floor(idx))
    hi = int(np.ceil(idx))
    if lo == hi:
        return vals[lo]
    frac = idx - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def _summarize_ms(samples):
    vals = [float(v) for v in samples]
    if not vals:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    return {
        "count": len(vals),
        "mean": float(np.mean(vals)),
        "p50": float(_percentile(vals, 0.50)),
        "p95": float(_percentile(vals, 0.95)),
    }


def _synthetic_pair(rng, width, height):
    bg = rng.integers(95, 106, size=(height, width, 3), dtype=np.uint8)
    img = bg.copy()

    cx = int(rng.integers(width // 4, (3 * width) // 4))
    cy = int(rng.integers(height // 4, (3 * height) // 4))
    r = int(rng.integers(max(10, width // 20), max(12, width // 10)))
    intensity = int(rng.integers(150, 220))
    cv2.circle(img, (cx, cy), r, (intensity, intensity, intensity), -1)

    if rng.random() < 0.35:
        cx2 = int(rng.integers(width // 6, (5 * width) // 6))
        cy2 = int(rng.integers(height // 6, (5 * height) // 6))
        r2 = int(max(8, r * 0.85))
        cv2.circle(img, (cx2, cy2), r2, (intensity, intensity, intensity), -1)

    return bg, img


def run_benchmark(*, iterations=50, width=420, height=420, seed=7):
    rng = np.random.default_rng(int(seed))
    cam = _camera_stub()

    t_nozzle = []
    t_contour = []
    t_char = []

    counts = {
        "nozzle_detected": 0,
        "contour_detected": 0,
        "characterized": 0,
        "multiple": 0,
    }

    for _ in range(int(iterations)):
        bg, img = _synthetic_pair(rng, int(width), int(height))

        t0 = time.perf_counter()
        center, _, _ = cam.identify_nozzle(bg, img.copy())
        t_nozzle.append((time.perf_counter() - t0) * 1000.0)
        if center is not None:
            counts["nozzle_detected"] += 1

        t1 = time.perf_counter()
        contour, _ = cam.identify_droplet_contour(img.copy(), bg)
        t_contour.append((time.perf_counter() - t1) * 1000.0)
        if contour is not None:
            counts["contour_detected"] += 1

        t2 = time.perf_counter()
        result, _ = cam.characterize_droplet(img.copy(), bg)
        t_char.append((time.perf_counter() - t2) * 1000.0)
        if isinstance(result, dict):
            counts["characterized"] += 1
        elif result == "Multiple":
            counts["multiple"] += 1

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "iterations": int(iterations),
        "image_size": {"width": int(width), "height": int(height)},
        "timings_ms": {
            "identify_nozzle": _summarize_ms(t_nozzle),
            "identify_droplet_contour": _summarize_ms(t_contour),
            "characterize_droplet": _summarize_ms(t_char),
        },
        "detections": counts,
    }


def write_json(path, payload):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out)


def main():
    p = argparse.ArgumentParser(description="Benchmark droplet CV routines on synthetic frames.")
    p.add_argument("--iterations", type=int, default=50)
    p.add_argument("--width", type=int, default=420)
    p.add_argument("--height", type=int, default=420)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default="")
    args = p.parse_args()

    payload = run_benchmark(
        iterations=max(1, int(args.iterations)),
        width=max(64, int(args.width)),
        height=max(64, int(args.height)),
        seed=int(args.seed),
    )
    if args.out:
        out = write_json(args.out, payload)
        print(f"Wrote benchmark: {out}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
