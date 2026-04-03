from __future__ import annotations

import argparse

from tools.stream_analysis.annotations import (
    diagnose_nozzle_candidates,
    evaluate_nozzle_annotations,
    launch_nozzle_annotation_session,
)
from tools.stream_analysis.baseline import export_stage1_baseline
from tools.stream_analysis.dataset import _print_json, export_stage0_inventory
from tools.stream_analysis.fit import export_stage5_fit
from tools.stream_analysis.nozzle import export_stage2_nozzle
from tools.stream_analysis.silhouette import export_stage3_silhouette
from tools.stream_analysis.volume import export_stage4_volume


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

    silhouette = subparsers.add_parser(
        "silhouette",
        help="Build Stage 3 filled-silhouette artifacts.",
    )
    silhouette.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    silhouette.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    silhouette.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to export. May be provided multiple times.",
    )
    silhouette.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    silhouette.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to export.",
    )
    silhouette.add_argument(
        "--sample-count",
        type=int,
        default=6,
        help="Number of evenly spaced sample frames to render per run.",
    )
    silhouette.add_argument(
        "--extra-frame-index",
        action="append",
        type=int,
        default=[],
        help="Additional 1-based frame indices to include in the review artifacts.",
    )
    silhouette.add_argument(
        "--search-width-frac",
        type=float,
        default=0.22,
        help="Fraction of image width to search for nozzle structure around the frame center.",
    )
    silhouette.add_argument(
        "--search-top-frac",
        type=float,
        default=0.08,
        help="Top search boundary as a fraction of image height.",
    )
    silhouette.add_argument(
        "--search-bottom-frac",
        type=float,
        default=0.30,
        help="Bottom search boundary as a fraction of image height.",
    )
    silhouette.add_argument(
        "--blur-sigma",
        type=float,
        default=12.0,
        help="Gaussian blur sigma used to estimate the local background for dark-structure detection.",
    )
    silhouette.add_argument(
        "--residual-threshold",
        type=int,
        default=18,
        help="Threshold applied to the local dark-structure residual mask.",
    )
    silhouette.add_argument(
        "--shift-threshold-px",
        type=float,
        default=6.0,
        help="Median jump threshold used to declare a grip-refresh segment boundary.",
    )
    silhouette.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.55,
        help="Minimum raw confidence needed before a frame is trusted as an anchor for smoothing.",
    )
    silhouette.add_argument(
        "--roi-width-frac",
        type=float,
        default=0.35,
        help="Fraction of image width to keep around the tracked nozzle x position.",
    )
    silhouette.add_argument(
        "--roi-top-frac",
        type=float,
        default=0.10,
        help="Top crop boundary as a fraction of image height.",
    )
    silhouette.add_argument(
        "--roi-bottom-frac",
        type=float,
        default=1.0,
        help="Bottom crop boundary as a fraction of image height.",
    )
    silhouette.add_argument(
        "--corridor-width-frac",
        type=float,
        default=0.70,
        help="Fraction of the dynamic ROI width to keep around the tracked nozzle x position.",
    )
    silhouette.add_argument(
        "--nozzle-guard-px",
        type=int,
        default=2,
        help="Extra pixels below the tracked nozzle row before silhouette rows become eligible.",
    )
    silhouette.add_argument(
        "--min-component-area-px",
        type=int,
        default=120,
        help="Minimum filled connected-component area eligible for selection.",
    )

    volume = subparsers.add_parser(
        "volume",
        help="Build Stage 4 visible-volume artifacts.",
    )
    volume.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    volume.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    volume.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to export. May be provided multiple times.",
    )
    volume.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    volume.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to export.",
    )
    volume.add_argument(
        "--sample-count",
        type=int,
        default=6,
        help="Number of evenly spaced sample frames to render per run.",
    )
    volume.add_argument(
        "--extra-frame-index",
        action="append",
        type=int,
        default=[],
        help="Additional 1-based frame indices to include in the review artifacts.",
    )
    volume.add_argument(
        "--search-width-frac",
        type=float,
        default=0.22,
        help="Fraction of image width to search for nozzle structure around the frame center.",
    )
    volume.add_argument(
        "--search-top-frac",
        type=float,
        default=0.08,
        help="Top search boundary as a fraction of image height.",
    )
    volume.add_argument(
        "--search-bottom-frac",
        type=float,
        default=0.30,
        help="Bottom search boundary as a fraction of image height.",
    )
    volume.add_argument(
        "--blur-sigma",
        type=float,
        default=12.0,
        help="Gaussian blur sigma used to estimate the local background for dark-structure detection.",
    )
    volume.add_argument(
        "--residual-threshold",
        type=int,
        default=18,
        help="Threshold applied to the local dark-structure residual mask.",
    )
    volume.add_argument(
        "--shift-threshold-px",
        type=float,
        default=6.0,
        help="Median jump threshold used to declare a grip-refresh segment boundary.",
    )
    volume.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.55,
        help="Minimum raw confidence needed before a frame is trusted as an anchor for smoothing.",
    )
    volume.add_argument(
        "--roi-width-frac",
        type=float,
        default=0.35,
        help="Fraction of image width to keep around the tracked nozzle x position.",
    )
    volume.add_argument(
        "--roi-top-frac",
        type=float,
        default=0.10,
        help="Top crop boundary as a fraction of image height.",
    )
    volume.add_argument(
        "--roi-bottom-frac",
        type=float,
        default=1.0,
        help="Bottom crop boundary as a fraction of image height.",
    )
    volume.add_argument(
        "--corridor-width-frac",
        type=float,
        default=0.70,
        help="Fraction of the dynamic ROI width to keep around the tracked nozzle x position.",
    )
    volume.add_argument(
        "--nozzle-guard-px",
        type=int,
        default=2,
        help="Extra pixels below the tracked nozzle row before silhouette rows become eligible.",
    )
    volume.add_argument(
        "--min-component-area-px",
        type=int,
        default=120,
        help="Minimum filled connected-component area eligible for selection.",
    )

    fit = subparsers.add_parser(
        "fit",
        help="Build Stage 5 steady-rate fit and middle-extrapolation artifacts.",
    )
    fit.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, stream_metadata.csv, calibration_recordings dir, process dir, or run dir.",
    )
    fit.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to the experiment-local analysis directory.",
    )
    fit.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run id to export. May be provided multiple times.",
    )
    fit.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Include unmatched run directories when no explicit run ids are supplied.",
    )
    fit.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Optional cap on the number of selected runs to export.",
    )
    fit.add_argument(
        "--sample-count",
        type=int,
        default=6,
        help="Number of evenly spaced sample frames to render per run.",
    )
    fit.add_argument(
        "--extra-frame-index",
        action="append",
        type=int,
        default=[],
        help="Additional 1-based frame indices to include in the review artifacts.",
    )
    fit.add_argument(
        "--search-width-frac",
        type=float,
        default=0.22,
        help="Fraction of image width to search for nozzle structure around the frame center.",
    )
    fit.add_argument(
        "--search-top-frac",
        type=float,
        default=0.08,
        help="Top search boundary as a fraction of image height.",
    )
    fit.add_argument(
        "--search-bottom-frac",
        type=float,
        default=0.30,
        help="Bottom search boundary as a fraction of image height.",
    )
    fit.add_argument(
        "--blur-sigma",
        type=float,
        default=12.0,
        help="Gaussian blur sigma used to estimate the local background for dark-structure detection.",
    )
    fit.add_argument(
        "--residual-threshold",
        type=int,
        default=18,
        help="Threshold applied to the local dark-structure residual mask.",
    )
    fit.add_argument(
        "--shift-threshold-px",
        type=float,
        default=6.0,
        help="Median jump threshold used to declare a grip-refresh segment boundary.",
    )
    fit.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.55,
        help="Minimum raw confidence needed before a frame is trusted as an anchor for smoothing.",
    )
    fit.add_argument(
        "--roi-width-frac",
        type=float,
        default=0.35,
        help="Fraction of image width to keep around the tracked nozzle x position.",
    )
    fit.add_argument(
        "--roi-top-frac",
        type=float,
        default=0.10,
        help="Top crop boundary as a fraction of image height.",
    )
    fit.add_argument(
        "--roi-bottom-frac",
        type=float,
        default=1.0,
        help="Bottom crop boundary as a fraction of image height.",
    )
    fit.add_argument(
        "--corridor-width-frac",
        type=float,
        default=0.70,
        help="Fraction of the dynamic ROI width to keep around the tracked nozzle x position.",
    )
    fit.add_argument(
        "--nozzle-guard-px",
        type=int,
        default=2,
        help="Extra pixels below the tracked nozzle row before silhouette rows become eligible.",
    )
    fit.add_argument(
        "--min-component-area-px",
        type=int,
        default=120,
        help="Minimum filled connected-component area eligible for selection.",
    )
    fit.add_argument(
        "--near-nozzle-band-top-px",
        type=int,
        default=24,
        help="Top offset below the tracked nozzle for the width band.",
    )
    fit.add_argument(
        "--near-nozzle-band-height-px",
        type=int,
        default=40,
        help="Height of the attached-stream width band below the nozzle.",
    )
    fit.add_argument(
        "--min-band-valid-rows",
        type=int,
        default=24,
        help="Minimum number of attached edge rows required for a valid near-nozzle width sample.",
    )
    fit.add_argument(
        "--width-smooth-window",
        type=int,
        default=5,
        help="Centered rolling-median window used to smooth the width trace.",
    )
    fit.add_argument(
        "--min-steady-frames",
        type=int,
        default=8,
        help="Minimum contiguous trusted frames required for a steady-window fit.",
    )
    fit.add_argument(
        "--steady-width-tol-frac",
        type=float,
        default=0.08,
        help="Maximum allowed width span as a fraction of the steady width plateau.",
    )
    fit.add_argument(
        "--steady-width-tol-px",
        type=float,
        default=4.0,
        help="Minimum absolute width-span tolerance for the steady window.",
    )
    fit.add_argument(
        "--steady-fit-r2-min",
        type=float,
        default=0.985,
        help="Minimum R^2 required for the steady Theil-Sen fit.",
    )
    fit.add_argument(
        "--steady-fit-nrmse-max",
        type=float,
        default=0.03,
        help="Maximum normalized RMSE allowed for the steady Theil-Sen fit.",
    )
    fit.add_argument(
        "--tail-drop-frac",
        type=float,
        default=0.08,
        help="Fractional drop below the steady width plateau that indicates tail onset.",
    )
    fit.add_argument(
        "--tail-persist-frames",
        type=int,
        default=3,
        help="Number of consecutive width-drop frames required to declare tail onset.",
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
    elif args.command == "silhouette":
        payload = export_stage3_silhouette(
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
            roi_width_frac=float(args.roi_width_frac),
            roi_top_frac=float(args.roi_top_frac),
            roi_bottom_frac=float(args.roi_bottom_frac),
            corridor_width_frac=float(args.corridor_width_frac),
            nozzle_guard_px=int(args.nozzle_guard_px),
            min_component_area_px=int(args.min_component_area_px),
        )
    elif args.command == "volume":
        payload = export_stage4_volume(
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
            roi_width_frac=float(args.roi_width_frac),
            roi_top_frac=float(args.roi_top_frac),
            roi_bottom_frac=float(args.roi_bottom_frac),
            corridor_width_frac=float(args.corridor_width_frac),
            nozzle_guard_px=int(args.nozzle_guard_px),
            min_component_area_px=int(args.min_component_area_px),
        )
    elif args.command == "fit":
        payload = export_stage5_fit(
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
            roi_width_frac=float(args.roi_width_frac),
            roi_top_frac=float(args.roi_top_frac),
            roi_bottom_frac=float(args.roi_bottom_frac),
            corridor_width_frac=float(args.corridor_width_frac),
            nozzle_guard_px=int(args.nozzle_guard_px),
            min_component_area_px=int(args.min_component_area_px),
            near_nozzle_band_top_px=int(args.near_nozzle_band_top_px),
            near_nozzle_band_height_px=int(args.near_nozzle_band_height_px),
            min_band_valid_rows=int(args.min_band_valid_rows),
            width_smooth_window=int(args.width_smooth_window),
            min_steady_frames=int(args.min_steady_frames),
            steady_width_tol_frac=float(args.steady_width_tol_frac),
            steady_width_tol_px=float(args.steady_width_tol_px),
            steady_fit_r2_min=float(args.steady_fit_r2_min),
            steady_fit_nrmse_max=float(args.steady_fit_nrmse_max),
            tail_drop_frac=float(args.tail_drop_frac),
            tail_persist_frames=int(args.tail_persist_frames),
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
