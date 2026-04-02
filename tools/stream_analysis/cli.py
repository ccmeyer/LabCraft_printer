from __future__ import annotations

import argparse

from tools.stream_analysis.annotations import (
    diagnose_nozzle_candidates,
    evaluate_nozzle_annotations,
    launch_nozzle_annotation_session,
)
from tools.stream_analysis.baseline import export_stage1_baseline
from tools.stream_analysis.dataset import _print_json, export_stage0_inventory
from tools.stream_analysis.nozzle import export_stage2_nozzle


def build_parser():
    parser = argparse.ArgumentParser(
        description="Offline stream-characterization analysis tooling."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory",
        help="Build Stage 0 run inventory and per-run frame indexes.",
    )
    inventory.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    inventory.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    inventory.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to export. May be provided multiple times.",
    )
    inventory.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories in the selected export set.",
    )
    inventory.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to export.",
    )

    baseline = subparsers.add_parser(
        "baseline",
        help="Build Stage 1 ROI-first direct-threshold artifacts.",
    )
    baseline.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    baseline.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    baseline.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to export. May be provided multiple times.",
    )
    baseline.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    baseline.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to export.",
    )
    baseline.add_argument(
        "--sample-count",
        type=int,
        default=6,
        help="Number of evenly spaced sample frames to render per run.",
    )
    baseline.add_argument(
        "--extra-frame-index",
        action="append",
        type=int,
        default=[],
        help="Additional 1-based frame indices to include in the review artifacts.",
    )
    baseline.add_argument(
        "--roi-width-frac",
        type=float,
        default=0.35,
        help="Fraction of image width to keep around the frame center.",
    )
    baseline.add_argument(
        "--roi-top-frac",
        type=float,
        default=0.10,
        help="Top crop boundary as a fraction of image height.",
    )
    baseline.add_argument(
        "--roi-bottom-frac",
        type=float,
        default=1.0,
        help="Bottom crop boundary as a fraction of image height.",
    )
    baseline.add_argument(
        "--corridor-width-frac",
        type=float,
        default=0.70,
        help="Fraction of the ROI width to keep around the frame center after thresholding.",
    )

    nozzle = subparsers.add_parser(
        "nozzle",
        help="Build Stage 2 per-frame nozzle-tracking artifacts.",
    )
    nozzle.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    nozzle.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    nozzle.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to export. May be provided multiple times.",
    )
    nozzle.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    nozzle.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to export.",
    )
    nozzle.add_argument(
        "--sample-count",
        type=int,
        default=6,
        help="Number of evenly spaced sample frames to render per run.",
    )
    nozzle.add_argument(
        "--extra-frame-index",
        action="append",
        type=int,
        default=[],
        help="Additional 1-based frame indices to include in the review artifacts.",
    )
    nozzle.add_argument(
        "--search-width-frac",
        type=float,
        default=0.22,
        help="Fraction of image width to search for nozzle structure around the frame center.",
    )
    nozzle.add_argument(
        "--search-top-frac",
        type=float,
        default=0.08,
        help="Top search boundary as a fraction of image height.",
    )
    nozzle.add_argument(
        "--search-bottom-frac",
        type=float,
        default=0.30,
        help="Bottom search boundary as a fraction of image height.",
    )
    nozzle.add_argument(
        "--blur-sigma",
        type=float,
        default=12.0,
        help="Gaussian blur sigma used to estimate the local background for dark-structure detection.",
    )
    nozzle.add_argument(
        "--residual-threshold",
        type=int,
        default=18,
        help="Threshold applied to the local dark-structure residual mask.",
    )
    nozzle.add_argument(
        "--shift-threshold-px",
        type=float,
        default=6.0,
        help="Median jump threshold used to declare a grip-refresh segment boundary.",
    )
    nozzle.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.55,
        help="Minimum raw confidence needed before a frame is trusted as an anchor for smoothing.",
    )

    annotate = subparsers.add_parser(
        "annotate-nozzle",
        help="Launch the offline nozzle-annotation UI.",
    )
    annotate.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    annotate.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    annotate.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to annotate. May be provided multiple times.",
    )
    annotate.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    annotate.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to annotate.",
    )
    annotate.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last saved annotation state for this experiment.",
    )
    annotate.add_argument(
        "--start-run-id",
        default="",
        help="Optional run id to start annotation from.",
    )
    annotate.add_argument(
        "--start-frame-index",
        type=int,
        default=0,
        help="Optional 1-based frame index to start annotation from.",
    )
    annotate.add_argument(
        "--zoom-half-width",
        type=int,
        default=90,
        help="Half-width of the zoomed annotation panel in pixels.",
    )
    annotate.add_argument(
        "--show-prediction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show or hide the Stage 2 prediction as a ghost reference overlay.",
    )

    evaluate = subparsers.add_parser(
        "evaluate-nozzle",
        help="Compare saved nozzle annotations against Stage 2 predictions.",
    )
    evaluate.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    evaluate.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    evaluate.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to evaluate. May be provided multiple times.",
    )
    evaluate.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    evaluate.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to evaluate.",
    )
    evaluate.add_argument(
        "--limit-worst-frames",
        type=int,
        default=50,
        help="Maximum number of worst-frame overlays to export.",
    )

    diagnose = subparsers.add_parser(
        "diagnose-nozzle",
        help="Score Stage 2 raw nozzle candidates against saved annotations.",
    )
    diagnose.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    diagnose.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    diagnose.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to diagnose. May be provided multiple times.",
    )
    diagnose.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    diagnose.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to diagnose.",
    )
    diagnose.add_argument(
        "--limit-worst-frames",
        type=int,
        default=50,
        help="Maximum number of overlay frames to export per diagnostics category.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inventory":
        payload = export_stage0_inventory(
            args.experiment_root,
            output_root=args.output_root or None,
            include_unmatched=bool(args.include_unmatched),
            run_ids=args.run_id or None,
            limit_runs=(args.limit_runs or None),
        )
    elif args.command == "baseline":
        payload = export_stage1_baseline(
            args.experiment_root,
            output_root=args.output_root or None,
            run_ids=args.run_id or None,
            limit_runs=(args.limit_runs or None),
            include_unmatched=bool(args.include_unmatched),
            sample_count=int(args.sample_count),
            extra_frame_indices=list(args.extra_frame_index or []),
            roi_width_frac=float(args.roi_width_frac),
            roi_top_frac=float(args.roi_top_frac),
            roi_bottom_frac=float(args.roi_bottom_frac),
            corridor_width_frac=float(args.corridor_width_frac),
        )
    elif args.command == "nozzle":
        payload = export_stage2_nozzle(
            args.experiment_root,
            output_root=args.output_root or None,
            run_ids=args.run_id or None,
            limit_runs=(args.limit_runs or None),
            include_unmatched=bool(args.include_unmatched),
            sample_count=int(args.sample_count),
            extra_frame_indices=list(args.extra_frame_index or []),
            search_width_frac=float(args.search_width_frac),
            search_top_frac=float(args.search_top_frac),
            search_bottom_frac=float(args.search_bottom_frac),
            blur_sigma=float(args.blur_sigma),
            residual_threshold=int(args.residual_threshold),
            shift_threshold_px=float(args.shift_threshold_px),
            confidence_threshold=float(args.confidence_threshold),
        )
    elif args.command == "annotate-nozzle":
        payload = launch_nozzle_annotation_session(
            args.experiment_root,
            output_root=args.output_root or None,
            run_ids=args.run_id or None,
            limit_runs=(args.limit_runs or None),
            include_unmatched=bool(args.include_unmatched),
            resume=bool(args.resume),
            start_run_id=args.start_run_id or None,
            start_frame_index=(args.start_frame_index or None),
            zoom_half_width=int(args.zoom_half_width),
            show_prediction=bool(args.show_prediction),
        )
    elif args.command == "evaluate-nozzle":
        payload = evaluate_nozzle_annotations(
            args.experiment_root,
            output_root=args.output_root or None,
            run_ids=args.run_id or None,
            limit_runs=(args.limit_runs or None),
            include_unmatched=bool(args.include_unmatched),
            limit_worst_frames=int(args.limit_worst_frames),
        )
    elif args.command == "diagnose-nozzle":
        payload = diagnose_nozzle_candidates(
            args.experiment_root,
            output_root=args.output_root or None,
            run_ids=args.run_id or None,
            limit_runs=(args.limit_runs or None),
            include_unmatched=bool(args.include_unmatched),
            limit_worst_frames=int(args.limit_worst_frames),
        )
    else:
        parser.error(f"Unsupported command: {args.command}")

    _print_json(payload)
    return 0
