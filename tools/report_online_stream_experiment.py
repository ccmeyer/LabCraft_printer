#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stream_analysis import dataset as dataset_mod  # noqa: E402
from tools.stream_analysis import online_report as online_report_mod  # noqa: E402


def _um_per_pixel_from_manifest(manifest_path: Path) -> float:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    optics_layer = payload.get("optics_layer") if isinstance(payload, dict) else None
    if not isinstance(optics_layer, dict):
        raise ValueError(f"Manifest has no optics_layer: {manifest_path}")
    try:
        value = float(optics_layer.get("um_per_pixel"))
    except Exception as exc:
        raise ValueError(f"Manifest optics_layer.um_per_pixel is invalid: {manifest_path}") from exc
    if value <= 0.0:
        raise ValueError(f"Manifest optics_layer.um_per_pixel must be positive: {manifest_path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an offline report for archived online-stream calibration experiments."
    )
    parser.add_argument(
        "--experiment-root",
        required=True,
        type=Path,
        help="Experiment directory, stream_metadata.csv, process root, or run directory.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Optional output directory. Defaults to <experiment>/analysis/online_stream_report.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional Dataset name filter to generate a report for a single run.",
    )
    parser.add_argument(
        "--density-g-per-ml",
        type=float,
        default=1.0,
        help="Gravimetric fluid density in g/mL used to convert mg to nL. Defaults to 1.0.",
    )
    parser.add_argument(
        "--um-per-pixel",
        type=float,
        default=None,
        help="Optional optics conversion for saved-image replay volume recomputation.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help=(
            "Optional validation manifest. If --um-per-pixel is omitted, "
            "optics_layer.um_per_pixel is used for saved-image replay."
        ),
    )
    parser.add_argument(
        "--correction-mode",
        choices=["none", "chroma_edge_v2", "runtime_rgb_fix"],
        default="none",
        help=(
            "Optional replay correction mode. Use runtime_rgb_fix to recompute from saved images "
            "with the corrected runtime path."
        ),
    )
    parser.add_argument(
        "--settling-aware-fit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable or disable the conservative settling-aware late-window flow-fit rule when "
            "the report is recomputed. Defaults to the runtime/replay default."
        ),
    )
    parser.add_argument(
        "--tail-settling-rule",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable or disable the settling-aware tail-start rule when the report is recomputed. "
            "Defaults to the runtime/replay default."
        ),
    )
    parser.add_argument(
        "--segmented-tail-review",
        action="store_true",
        help="Write an offline segmented-regression tail-start review alongside the report.",
    )
    args = parser.parse_args(argv)
    um_per_pixel = (
        float(args.um_per_pixel)
        if args.um_per_pixel is not None
        else (_um_per_pixel_from_manifest(args.manifest) if args.manifest is not None else None)
    )

    payload = online_report_mod.export_online_stream_experiment_report(
        args.experiment_root,
        output_root=args.output_root,
        run_id=args.run_id,
        density_g_per_ml=args.density_g_per_ml,
        correction_mode=(None if args.correction_mode == "none" else args.correction_mode),
        um_per_pixel=um_per_pixel,
        settling_aware_fit_enabled=args.settling_aware_fit,
        tail_settling_rule_enabled=args.tail_settling_rule,
        segmented_tail_review=bool(args.segmented_tail_review),
    )
    dataset_mod._print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
