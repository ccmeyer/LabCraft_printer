from __future__ import annotations

import math
import json
from pathlib import Path

import cv2

from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)
from tools.stream_analysis import fov as fov_mod
from tools.stream_analysis import silhouette as silhouette_mod


VOLUME_STAGE_DIRNAME = "stage_04_volume"
PIXEL_SIZE_UM = 1.5696
DEFAULT_PIXEL_SIZE_UM = PIXEL_SIZE_UM
REPO_ROOT = Path(__file__).resolve().parents[2]
OPTICS_CONFIG_PATH = REPO_ROOT / "local" / "droplet_imager_optics.json"
UM3_PER_NL = 1_000_000.0

FRAME_METRIC_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "image_relpath",
    "image_exists",
    "captured_at_utc",
    "flash_delay_us",
    "delay_from_emergence_us",
    "tracked_nozzle_x_px",
    "tracked_nozzle_y_px",
    "tracked_confidence",
    "raw_mode",
    "final_mode",
    "segment_id",
    "shift_event_before",
    "silhouette_status",
    "failure_reason",
    "accepted_component_count",
    "accepted_detached_component_count",
    "plausible_unaccepted_component_count",
    "attached_visible_volume_nl",
    "detached_visible_volume_nl",
    "plausible_unaccepted_visible_volume_nl",
    "total_visible_volume_nl",
    "volume_is_trusted",
    "volume_trust_label",
    "accepted_fluid_near_fov_exit",
    "fov_near_component_count",
    "min_accepted_fluid_distance_from_bottom_px",
    "fov_exit_triggered",
    "fov_exit_reason",
    "sample_frame",
]

COMPONENT_VOLUME_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "flash_delay_us",
    "component_id",
    "component_role",
    "component_rank",
    "component_volume_nl",
    "valid_row_count",
    "top_y_px",
    "bottom_y_px",
    "bbox_x_px",
    "bbox_y_px",
    "bbox_w_px",
    "bbox_h_px",
]

TIMESERIES_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "flash_delay_us",
    "delay_from_emergence_us",
    "silhouette_status",
    "accepted_component_count",
    "accepted_detached_component_count",
    "attached_visible_volume_nl",
    "detached_visible_volume_nl",
    "total_visible_volume_nl",
    "volume_is_trusted",
    "volume_trust_label",
    "accepted_fluid_near_fov_exit",
    "fov_near_component_count",
    "min_accepted_fluid_distance_from_bottom_px",
    "fov_exit_triggered",
    "fov_exit_reason",
]


def _component_row_key(row: dict):
    return (
        _capture_key(row),
        _clean_text(row.get("component_id")),
    )


def _capture_key(row: dict):
    capture_id = _clean_text(row.get("capture_id"))
    if capture_id is not None:
        return capture_id
    capture_index = _int_or_none(row.get("capture_index"))
    return None if capture_index is None else f"capture_index:{capture_index}"


def _valid_pixel_size_um(value):
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out) or out <= 0:
        return None
    return out


def resolve_pixel_size_um(pixel_size_um: float | None = None, *, config_path: str | Path | None = None):
    explicit = _valid_pixel_size_um(pixel_size_um)
    if explicit is not None:
        return explicit

    path = Path(config_path) if config_path is not None else OPTICS_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            configured = _valid_pixel_size_um(json.load(f).get("um_per_pixel"))
    except Exception:
        configured = None
    return configured if configured is not None else float(DEFAULT_PIXEL_SIZE_UM)


def _row_volume_um3(edge_row: dict, *, pixel_size_um: float | None = None):
    pixel_size_um = resolve_pixel_size_um(pixel_size_um)
    # Edge traces are inclusive pixel bounds, so convert the occupied span to
    # diameter with a +1 px width before halving to a radius.
    radius_px = max(0.0, (float(edge_row["x_right_px"]) - float(edge_row["x_left_px"]) + 1.0) / 2.0)
    radius_um = radius_px * float(pixel_size_um)
    return math.pi * (radius_um**2) * float(pixel_size_um)


def _component_volume_um3(edge_rows: list[dict], *, pixel_size_um: float | None = None):
    pixel_size_um = resolve_pixel_size_um(pixel_size_um)
    return float(sum(_row_volume_um3(row, pixel_size_um=pixel_size_um) for row in edge_rows))


def _um3_to_nl(value_um3: float | None):
    if value_um3 is None:
        return None
    return float(value_um3) / float(UM3_PER_NL)


def _format_volume_text(value_nl):
    if value_nl is None:
        return "n/a"
    return f"{float(value_nl):.3f}"


def _trust_color(volume_trust_label: str | None):
    label = _clean_text(volume_trust_label)
    if label == fov_mod.TRUST_LABEL_TRUSTED:
        return (0, 220, 0)
    if label == fov_mod.TRUST_LABEL_UNAVAILABLE_GEOMETRY:
        return (180, 180, 180)
    return (0, 0, 255)


def _annotate_component_volumes(
    overlay,
    accepted_components: list[dict],
    component_volume_map: dict[str, dict],
    *,
    roi: dict,
):
    for component in accepted_components:
        component_id = _clean_text(component.get("component_id"))
        if component_id is None:
            continue
        label_row = component_volume_map.get(component_id)
        volume_nl = None if label_row is None else label_row.get("component_volume_nl")
        text = f"{component_id} {_format_volume_text(volume_nl)} nL"
        x_local = max(0, int(component["bbox_x_px"]) - int(roi["x0"]))
        y_local = max(18, int(component["top_y_px"]) - int(roi["y0"]) - 4)
        cv2.putText(
            overlay,
            text,
            (x_local, y_local),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            silhouette_mod._component_color(component.get("component_role", "detached_accepted")),
            1,
            cv2.LINE_AA,
        )
    return overlay


def _trigger_component_text(fov_report: dict):
    trigger_components = list(fov_report.get("trigger_components") or [])
    if not trigger_components:
        return None
    parts = []
    for component in trigger_components:
        component_id = _clean_text(component.get("component_id")) or "unknown"
        distance_from_bottom_px = _int_or_none(component.get("distance_from_bottom_px"))
        if distance_from_bottom_px is None:
            parts.append(component_id)
        else:
            parts.append(f"{component_id} ({distance_from_bottom_px}px)")
    return ", ".join(parts)


def _build_sample_panel(
    gray,
    sample_input: dict,
    frame_metric_row: dict,
    component_volume_rows: list[dict],
    *,
    fov_report: dict,
):
    roi = sample_input["roi"]
    corridor = sample_input["corridor"]
    tracked_row = sample_input["tracked_row"]
    raw_mask = sample_input["raw_mask"]
    accepted_components = list(sample_input["accepted_components"])
    cutoff_y_px = _int_or_none(sample_input["metric_row"].get("cutoff_y_px"))

    attached_volume = frame_metric_row.get("attached_visible_volume_nl")
    detached_volume = frame_metric_row.get("detached_visible_volume_nl")
    total_volume = frame_metric_row.get("total_visible_volume_nl")
    trust_label = _clean_text(frame_metric_row.get("volume_trust_label"))
    trust_color = _trust_color(trust_label)
    min_distance_from_bottom_px = _int_or_none(frame_metric_row.get("min_accepted_fluid_distance_from_bottom_px"))

    full = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(full, (int(roi["x0"]), int(roi["y0"])), (int(roi["x1"]), int(roi["y1"])), (0, 255, 255), 2)
    cv2.line(full, (int(corridor["x0"]), int(roi["y0"])), (int(corridor["x0"]), int(roi["y1"]) - 1), (255, 255, 0), 1)
    cv2.line(full, (int(corridor["x1"]) - 1, int(roi["y0"])), (int(corridor["x1"]) - 1, int(roi["y1"]) - 1), (255, 255, 0), 1)
    full = silhouette_mod._draw_nozzle_context(
        full,
        nozzle_x_px=tracked_row.get("tracked_nozzle_x_px"),
        nozzle_y_px=tracked_row.get("tracked_nozzle_y_px"),
        cutoff_y_px=cutoff_y_px,
        x0_px=int(roi["x0"]),
        x1_px=max(int(roi["x0"]), int(roi["x1"]) - 1),
    )
    cv2.rectangle(full, (2, 2), (full.shape[1] - 3, full.shape[0] - 3), trust_color, 3)
    full = silhouette_mod._draw_label(
        full,
        (
            f"frame {frame_metric_row.get('capture_index')}  "
            f"trust={trust_label or 'n/a'}  "
            f"att={_format_volume_text(attached_volume)}  "
            f"det={_format_volume_text(detached_volume)}  "
            f"tot={_format_volume_text(total_volume)} nL"
        ),
    )
    if bool(frame_metric_row.get("fov_exit_triggered")):
        cv2.putText(
            full,
            "FIRST UNTRUSTED FRAME",
            (12, 54),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        if min_distance_from_bottom_px is not None:
            cv2.putText(
                full,
                f"accepted fluid near bottom ({min_distance_from_bottom_px}px min distance)",
                (12, 82),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        trigger_text = _trigger_component_text(fov_report)
        if trigger_text:
            cv2.putText(
                full,
                trigger_text,
                (12, 106),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )

    roi_gray = gray[roi["y0"] : roi["y1"], roi["x0"] : roi["x1"]]
    roi_panel = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)
    roi_panel = silhouette_mod._draw_nozzle_context(
        roi_panel,
        nozzle_x_px=None
        if tracked_row.get("tracked_nozzle_x_px") is None
        else float(tracked_row["tracked_nozzle_x_px"]) - float(roi["x0"]),
        nozzle_y_px=None
        if tracked_row.get("tracked_nozzle_y_px") is None
        else float(tracked_row["tracked_nozzle_y_px"]) - float(roi["y0"]),
        cutoff_y_px=None if cutoff_y_px is None else int(cutoff_y_px) - int(roi["y0"]),
        x0_px=0,
        x1_px=max(0, roi_gray.shape[1] - 1),
    )
    roi_panel = silhouette_mod._draw_label(roi_panel, "grayscale ROI")

    accepted_mask_panel = silhouette_mod._accepted_mask_panel(raw_mask.shape, accepted_components, "accepted fluid mask")
    contour_panel = silhouette_mod._contour_overlay(
        roi_gray,
        accepted_components,
        roi=roi,
        tracked_row=tracked_row,
        cutoff_y_px=cutoff_y_px,
    )
    component_volume_map = {
        _clean_text(row.get("component_id")): row
        for row in component_volume_rows
        if _clean_text(row.get("component_id")) is not None
    }
    contour_panel = _annotate_component_volumes(
        contour_panel,
        accepted_components,
        component_volume_map,
        roi=roi,
    )
    contour_panel = silhouette_mod._draw_label(contour_panel, "component volumes")
    if bool(frame_metric_row.get("fov_exit_triggered")):
        cv2.rectangle(contour_panel, (2, 2), (contour_panel.shape[1] - 3, contour_panel.shape[0] - 3), (0, 0, 255), 3)

    target_height = 280
    row_images = [
        silhouette_mod._resize_to_height(full, target_height),
        silhouette_mod._resize_to_height(roi_panel, target_height),
        silhouette_mod._resize_to_height(silhouette_mod._mask_panel(raw_mask, "raw threshold mask"), target_height),
        silhouette_mod._resize_to_height(accepted_mask_panel, target_height),
        silhouette_mod._resize_to_height(contour_panel, target_height),
    ]
    return cv2.hconcat(row_images)


def _component_volume_rows(component_rows: list[dict], edge_rows: list[dict], *, pixel_size_um: float | None = None):
    pixel_size_um = resolve_pixel_size_um(pixel_size_um)
    edges_by_component = {}
    for row in edge_rows:
        edges_by_component.setdefault(_component_row_key(row), []).append(row)

    volume_rows = []
    for component_row in component_rows:
        key = _component_row_key(component_row)
        component_edge_rows = edges_by_component.get(key, [])
        volume_rows.append(
            {
                "run_id": component_row.get("run_id"),
                "capture_id": component_row.get("capture_id"),
                "capture_index": _int_or_none(component_row.get("capture_index")),
                "flash_delay_us": _int_or_none(component_row.get("flash_delay_us")),
                "component_id": component_row.get("component_id"),
                "component_role": component_row.get("component_role"),
                "component_rank": _int_or_none(component_row.get("component_rank")),
                "component_volume_nl": _um3_to_nl(
                    _component_volume_um3(component_edge_rows, pixel_size_um=pixel_size_um)
                ),
                "valid_row_count": _int_or_none(component_row.get("valid_row_count")),
                "top_y_px": _int_or_none(component_row.get("top_y_px")),
                "bottom_y_px": _int_or_none(component_row.get("bottom_y_px")),
                "bbox_x_px": _int_or_none(component_row.get("bbox_x_px")),
                "bbox_y_px": _int_or_none(component_row.get("bbox_y_px")),
                "bbox_w_px": _int_or_none(component_row.get("bbox_w_px")),
                "bbox_h_px": _int_or_none(component_row.get("bbox_h_px")),
            }
        )
    return volume_rows


def _analyze_stage4_frame(
    stage3_frame: dict,
    *,
    near_bottom_px: int = fov_mod.FOV_NEAR_BOTTOM_PX,
    pixel_size_um: float | None = None,
):
    pixel_size_um = resolve_pixel_size_um(pixel_size_um)
    stage3_metric_row = dict(stage3_frame.get("metric_row") or {})
    component_rows = [dict(row) for row in list(stage3_frame.get("component_rows") or [])]
    edge_rows = [dict(row) for row in list(stage3_frame.get("edge_rows") or [])]
    labeled_stage3_rows, fov_report = fov_mod.label_frame_trust(
        [stage3_metric_row],
        component_rows,
        near_bottom_px=int(near_bottom_px),
    )
    component_volume_rows = _component_volume_rows(component_rows, edge_rows, pixel_size_um=pixel_size_um)
    frame_metric_rows = _frame_metric_rows(labeled_stage3_rows, component_volume_rows)
    return {
        "pixel_size_um": float(pixel_size_um),
        "labeled_stage3_row": (
            dict(labeled_stage3_rows[0])
            if labeled_stage3_rows
            else dict(stage3_metric_row)
        ),
        "component_volume_rows": component_volume_rows,
        "frame_metric_row": (
            dict(frame_metric_rows[0])
            if frame_metric_rows
            else {}
        ),
        "fov_report": dict(fov_report),
    }


def _frame_metric_rows(stage3_metric_rows: list[dict], component_volume_rows: list[dict]):
    components_by_capture = {}
    for row in component_volume_rows:
        components_by_capture.setdefault(_capture_key(row), []).append(row)

    frame_rows = []
    for stage3_row in stage3_metric_rows:
        capture_id = _capture_key(stage3_row)
        frame_components = components_by_capture.get(capture_id, [])
        silhouette_status = _clean_text(stage3_row.get("silhouette_status"))
        attached_volume = None
        detached_volume = None
        plausible_unaccepted_volume = None
        total_volume = None
        if silhouette_status == "ok":
            attached_volume = sum(
                float(row["component_volume_nl"])
                for row in frame_components
                if _clean_text(row.get("component_role")) == "attached_primary"
            )
            detached_volume = sum(
                float(row["component_volume_nl"])
                for row in frame_components
                if _clean_text(row.get("component_role")) == "detached_accepted"
            )
            plausible_unaccepted_volume = sum(
                float(row["component_volume_nl"])
                for row in frame_components
                if _clean_text(row.get("component_role")) == "detached_plausible_unaccepted"
            )
            total_volume = float(attached_volume + detached_volume)
        frame_rows.append(
            {
                "run_id": stage3_row.get("run_id"),
                "capture_id": stage3_row.get("capture_id"),
                "capture_index": _int_or_none(stage3_row.get("capture_index")),
                "image_relpath": stage3_row.get("image_relpath"),
                "image_exists": bool(stage3_row.get("image_exists")),
                "captured_at_utc": stage3_row.get("captured_at_utc"),
                "flash_delay_us": _int_or_none(stage3_row.get("flash_delay_us")),
                "delay_from_emergence_us": _int_or_none(stage3_row.get("delay_from_emergence_us")),
                "tracked_nozzle_x_px": stage3_row.get("tracked_nozzle_x_px"),
                "tracked_nozzle_y_px": stage3_row.get("tracked_nozzle_y_px"),
                "tracked_confidence": stage3_row.get("tracked_confidence"),
                "raw_mode": stage3_row.get("raw_mode"),
                "final_mode": stage3_row.get("final_mode"),
                "segment_id": _int_or_none(stage3_row.get("segment_id")),
                "shift_event_before": bool(stage3_row.get("shift_event_before")),
                "silhouette_status": stage3_row.get("silhouette_status"),
                "failure_reason": stage3_row.get("failure_reason"),
                "accepted_component_count": _int_or_none(stage3_row.get("accepted_component_count")),
                "accepted_detached_component_count": _int_or_none(stage3_row.get("accepted_detached_component_count")),
                "plausible_unaccepted_component_count": _int_or_none(
                    stage3_row.get("plausible_unaccepted_component_count")
                ),
                "attached_visible_volume_nl": attached_volume,
                "detached_visible_volume_nl": detached_volume,
                "plausible_unaccepted_visible_volume_nl": plausible_unaccepted_volume,
                "total_visible_volume_nl": total_volume,
                "volume_is_trusted": bool(stage3_row.get("volume_is_trusted")),
                "volume_trust_label": stage3_row.get("volume_trust_label"),
                "accepted_fluid_near_fov_exit": bool(stage3_row.get("accepted_fluid_near_fov_exit")),
                "fov_near_component_count": _int_or_none(stage3_row.get("fov_near_component_count")),
                "min_accepted_fluid_distance_from_bottom_px": _int_or_none(
                    stage3_row.get("min_accepted_fluid_distance_from_bottom_px")
                ),
                "fov_exit_triggered": bool(stage3_row.get("fov_exit_triggered")),
                "fov_exit_reason": stage3_row.get("fov_exit_reason"),
                "sample_frame": bool(stage3_row.get("sample_frame")),
            }
        )
    return frame_rows


def _timeseries_rows(frame_metric_rows: list[dict]):
    rows = []
    for row in frame_metric_rows:
        rows.append(
            {
                "run_id": row.get("run_id"),
                "capture_id": row.get("capture_id"),
                "capture_index": row.get("capture_index"),
                "flash_delay_us": row.get("flash_delay_us"),
                "delay_from_emergence_us": row.get("delay_from_emergence_us"),
                "silhouette_status": row.get("silhouette_status"),
                "accepted_component_count": row.get("accepted_component_count"),
                "accepted_detached_component_count": row.get("accepted_detached_component_count"),
                "attached_visible_volume_nl": row.get("attached_visible_volume_nl"),
                "detached_visible_volume_nl": row.get("detached_visible_volume_nl"),
                "total_visible_volume_nl": row.get("total_visible_volume_nl"),
                "volume_is_trusted": row.get("volume_is_trusted"),
                "volume_trust_label": row.get("volume_trust_label"),
                "accepted_fluid_near_fov_exit": row.get("accepted_fluid_near_fov_exit"),
                "fov_near_component_count": row.get("fov_near_component_count"),
                "min_accepted_fluid_distance_from_bottom_px": row.get(
                    "min_accepted_fluid_distance_from_bottom_px"
                ),
                "fov_exit_triggered": row.get("fov_exit_triggered"),
                "fov_exit_reason": row.get("fov_exit_reason"),
            }
        )
    return rows


def _summary_from_frame_rows(frame_metric_rows: list[dict], component_volume_rows: list[dict]):
    total_volumes = [
        float(row["total_visible_volume_nl"])
        for row in frame_metric_rows
        if row.get("total_visible_volume_nl") is not None
    ]
    detached_volumes = [
        float(row["detached_visible_volume_nl"])
        for row in frame_metric_rows
        if row.get("detached_visible_volume_nl") is not None
    ]
    trusted_frame_count = sum(
        1
        for row in frame_metric_rows
        if _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_TRUSTED
    )
    untrusted_frame_count = sum(
        1
        for row in frame_metric_rows
        if _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    )
    unavailable_geometry_frame_count = sum(
        1
        for row in frame_metric_rows
        if _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_UNAVAILABLE_GEOMETRY
    )
    return {
        "frame_count": len(frame_metric_rows),
        "ok_frame_count": sum(1 for row in frame_metric_rows if _clean_text(row.get("silhouette_status")) == "ok"),
        "detached_frame_count": sum(
            1 for row in frame_metric_rows if int(row.get("accepted_detached_component_count") or 0) > 0
        ),
        "component_volume_row_count": len(component_volume_rows),
        "trusted_frame_count": trusted_frame_count,
        "untrusted_frame_count": untrusted_frame_count,
        "unavailable_geometry_frame_count": unavailable_geometry_frame_count,
        "total_visible_volume_nl_min": min(total_volumes) if total_volumes else None,
        "total_visible_volume_nl_max": max(total_volumes) if total_volumes else None,
        "detached_visible_volume_nl_max": max(detached_volumes) if detached_volumes else None,
    }


def _plot_x_values(frame_metric_rows: list[dict]):
    if any(_int_or_none(row.get("delay_from_emergence_us")) is not None for row in frame_metric_rows):
        return (
            "Delay from emergence (us)",
            [
                _int_or_none(row.get("delay_from_emergence_us"))
                if _int_or_none(row.get("delay_from_emergence_us")) is not None
                else _int_or_none(row.get("capture_index"))
                for row in frame_metric_rows
            ],
        )
    return (
        "Capture index",
        [_int_or_none(row.get("capture_index")) for row in frame_metric_rows],
    )


def _write_vt_plot(path: Path, frame_metric_rows: list[dict], *, run_id: str, fov_report: dict):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    x_label, x_values = _plot_x_values(frame_metric_rows)
    available_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, frame_metric_rows)
        if x_value is not None and row.get("total_visible_volume_nl") is not None
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    if available_rows:
        ax.plot(
            [x for x, _row in available_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in available_rows],
            color="#8aa5c8",
            linewidth=1.5,
            alpha=0.8,
            label="all available frames",
        )

    trusted_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, frame_metric_rows)
        if x_value is not None
        and row.get("total_visible_volume_nl") is not None
        and _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_TRUSTED
    ]
    untrusted_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, frame_metric_rows)
        if x_value is not None
        and row.get("total_visible_volume_nl") is not None
        and _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    ]
    unavailable_rows = [
        x_value
        for x_value, row in zip(x_values, frame_metric_rows)
        if x_value is not None
        and _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_UNAVAILABLE_GEOMETRY
    ]

    if trusted_rows:
        ax.scatter(
            [x for x, _row in trusted_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in trusted_rows],
            color="#228b22",
            s=24,
            label="trusted",
            zorder=3,
        )
    if untrusted_rows:
        ax.scatter(
            [x for x, _row in untrusted_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in untrusted_rows],
            color="#d62728",
            s=26,
            label="untrusted_fov_exit",
            zorder=3,
        )
    if unavailable_rows:
        unavailable_y = 0.0 if not available_rows else min(float(row["total_visible_volume_nl"]) for _x, row in available_rows) * 0.9
        ax.scatter(
            unavailable_rows,
            [unavailable_y for _ in unavailable_rows],
            color="#777777",
            marker="x",
            s=32,
            label="unavailable_geometry",
            zorder=3,
        )

    first_untrusted_capture_index = _int_or_none(fov_report.get("first_untrusted_capture_index"))
    if first_untrusted_capture_index is not None:
        first_untrusted_x = None
        first_untrusted_row = None
        for x_value, row in zip(x_values, frame_metric_rows):
            if _int_or_none(row.get("capture_index")) == first_untrusted_capture_index:
                first_untrusted_x = x_value
                first_untrusted_row = row
                break
        if first_untrusted_x is not None:
            ax.axvline(
                first_untrusted_x,
                color="#d62728",
                linestyle="--",
                linewidth=1.4,
                label="first accepted-fluid near bottom",
            )
            trigger_text = _trigger_component_text(fov_report)
            min_distance_from_bottom_px = None if first_untrusted_row is None else _int_or_none(
                first_untrusted_row.get("min_accepted_fluid_distance_from_bottom_px")
            )
            annotation_parts = []
            if min_distance_from_bottom_px is not None:
                annotation_parts.append(f"min distance {min_distance_from_bottom_px}px")
            if trigger_text:
                annotation_parts.append(trigger_text)
            if annotation_parts:
                annotation_y = max(
                    (float(row["total_visible_volume_nl"]) for _x, row in available_rows),
                    default=0.0,
                )
                annotation_text = "; ".join(annotation_parts)
                if hasattr(ax, "annotate"):
                    ax.annotate(
                        annotation_text,
                        xy=(first_untrusted_x, annotation_y),
                        xytext=(8, -18),
                        textcoords="offset points",
                        fontsize=8,
                        color="#d62728",
                    )

    ax.set_title(f"Visible Volume V(t) - {run_id}")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Visible volume (nL)")
    ax.grid(True, alpha=0.25)
    if hasattr(ax, "get_legend_handles_labels"):
        handles, labels = ax.get_legend_handles_labels()
        if labels:
            by_label = dict(zip(labels, handles))
            ax.legend(by_label.values(), by_label.keys(), loc="best")
    elif hasattr(ax, "legend"):
        ax.legend(loc="best")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _build_stage4_run(
    run_id: str,
    frame_rows: list[dict],
    *,
    tracking_mode: str = "dynamic",
    sample_count: int,
    extra_frame_indices: list[int] | None,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
    blur_sigma: float,
    residual_threshold: int,
    shift_threshold_px: float,
    confidence_threshold: float,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
    corridor_width_frac: float,
    nozzle_guard_px: int,
    min_component_area_px: int,
    pixel_size_um: float | None = None,
):
    pixel_size_um = resolve_pixel_size_um(pixel_size_um)
    stage3_run = silhouette_mod._build_stage3_run(
        run_id,
        frame_rows,
        tracking_mode=tracking_mode,
        sample_count=sample_count,
        extra_frame_indices=extra_frame_indices,
        search_width_frac=search_width_frac,
        search_top_frac=search_top_frac,
        search_bottom_frac=search_bottom_frac,
        blur_sigma=blur_sigma,
        residual_threshold=residual_threshold,
        shift_threshold_px=shift_threshold_px,
        confidence_threshold=confidence_threshold,
        roi_width_frac=roi_width_frac,
        roi_top_frac=roi_top_frac,
        roi_bottom_frac=roi_bottom_frac,
        corridor_width_frac=corridor_width_frac,
        nozzle_guard_px=nozzle_guard_px,
        min_component_area_px=min_component_area_px,
    )
    labeled_stage3_rows, fov_report = fov_mod.label_frame_trust(
        list(stage3_run["metric_rows"]),
        list(stage3_run["component_rows"]),
        near_bottom_px=fov_mod.FOV_NEAR_BOTTOM_PX,
    )
    component_volume_rows = _component_volume_rows(
        list(stage3_run["component_rows"]),
        list(stage3_run["edge_rows"]),
        pixel_size_um=pixel_size_um,
    )
    frame_metric_rows = _frame_metric_rows(
        labeled_stage3_rows,
        component_volume_rows,
    )
    timeseries_rows = _timeseries_rows(frame_metric_rows)
    summary_counts = _summary_from_frame_rows(frame_metric_rows, component_volume_rows)
    return {
        **stage3_run,
        "pixel_size_um": float(pixel_size_um),
        "labeled_stage3_rows": labeled_stage3_rows,
        "component_volume_rows": component_volume_rows,
        "frame_metric_rows": frame_metric_rows,
        "timeseries_rows": timeseries_rows,
        "fov_report": fov_report,
        "summary_counts": summary_counts,
    }


def export_stage4_volume(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    sample_count: int = 6,
    extra_frame_indices: list[int] | None = None,
    search_width_frac: float = 0.22,
    search_top_frac: float = 0.08,
    search_bottom_frac: float = 0.30,
    blur_sigma: float = 12.0,
    residual_threshold: int = 18,
    shift_threshold_px: float = 6.0,
    confidence_threshold: float = 0.55,
    roi_width_frac: float = 0.35,
    roi_top_frac: float = 0.10,
    roi_bottom_frac: float = 1.0,
    corridor_width_frac: float = 0.70,
    nozzle_guard_px: int = 2,
    min_component_area_px: int = 120,
    pixel_size_um: float | None = None,
):
    pixel_size_um = resolve_pixel_size_um(pixel_size_um)
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )

    output_path = Path(output_root).expanduser().resolve() if output_root else default_output_root(experiment_root)
    output_path.mkdir(parents=True, exist_ok=True)

    run_manifests = []
    for run_row in inventory["selected_runs"]:
        run_id = str(run_row["run_id"])
        tracking_mode = str(run_row.get("tracking_mode") or "dynamic")
        frame_rows = list(inventory["frames_by_run_id"][run_id])
        if not frame_rows:
            raise ValueError(f"No frame index rows available for run: {run_id}")

        stage4_run = _build_stage4_run(
            run_id,
            frame_rows,
            tracking_mode=tracking_mode,
            sample_count=sample_count,
            extra_frame_indices=extra_frame_indices,
            search_width_frac=search_width_frac,
            search_top_frac=search_top_frac,
            search_bottom_frac=search_bottom_frac,
            blur_sigma=blur_sigma,
            residual_threshold=residual_threshold,
            shift_threshold_px=shift_threshold_px,
            confidence_threshold=confidence_threshold,
            roi_width_frac=roi_width_frac,
            roi_top_frac=roi_top_frac,
            roi_bottom_frac=roi_bottom_frac,
            corridor_width_frac=corridor_width_frac,
            nozzle_guard_px=nozzle_guard_px,
            min_component_area_px=min_component_area_px,
            pixel_size_um=pixel_size_um,
        )
        component_volume_rows = list(stage4_run["component_volume_rows"])
        frame_metric_rows = list(stage4_run["frame_metric_rows"])
        timeseries_rows = list(stage4_run["timeseries_rows"])
        summary_counts = dict(stage4_run["summary_counts"])

        fov_report = {
            **dict(stage4_run["fov_report"]),
            "stage": "volume",
            "run_id": run_id,
            "volume_unit": "nL",
            "trusted_frame_count": int(summary_counts["trusted_frame_count"]),
            "untrusted_frame_count": int(summary_counts["untrusted_frame_count"]),
            "unavailable_geometry_frame_count": int(summary_counts["unavailable_geometry_frame_count"]),
        }

        stage_dir = output_path / "runs" / run_id / VOLUME_STAGE_DIRNAME
        stage_dir.mkdir(parents=True, exist_ok=True)
        sample_dir = stage_dir / "samples"
        if sample_dir.exists():
            for stale_panel in sample_dir.glob("*.png"):
                stale_panel.unlink()
        else:
            sample_dir.mkdir(parents=True, exist_ok=True)

        component_rows_by_capture = {}
        for row in component_volume_rows:
            component_rows_by_capture.setdefault(_capture_key(row), []).append(row)

        sample_panels = []
        sample_panel_paths = []
        for capture_index in stage4_run["sample_indices"]:
            sample_input = stage4_run["sample_inputs"].get(int(capture_index))
            if sample_input is None:
                continue
            frame_metric_row = next(
                (
                    row
                    for row in frame_metric_rows
                    if int(row.get("capture_index") or 0) == int(capture_index)
                ),
                None,
            )
            if frame_metric_row is None:
                continue
            gray = silhouette_mod._load_gray_image(Path(str(sample_input["image_path"])))
            panel = _build_sample_panel(
                gray,
                sample_input,
                frame_metric_row,
                component_rows_by_capture.get(_capture_key(frame_metric_row), []),
                fov_report=fov_report,
            )
            panel_path = sample_dir / f"frame_{int(capture_index):03d}_panel.png"
            cv2.imwrite(str(panel_path), panel)
            sample_panels.append(panel)
            sample_panel_paths.append(str(panel_path))

        frame_metrics_csv = stage_dir / "frame_metrics.csv"
        component_volumes_csv = stage_dir / "component_volumes.csv"
        timeseries_csv = stage_dir / "volume_timeseries.csv"
        timeseries_json = stage_dir / "volume_timeseries.json"
        fov_exit_report_json = stage_dir / "fov_exit_report.json"
        vt_png = stage_dir / "Vt.png"
        summary_json = stage_dir / "volume_manifest.json"
        contact_sheet_png = stage_dir / "sample_contact_sheet.png"

        _write_csv(frame_metrics_csv, _preferred_columns(frame_metric_rows, FRAME_METRIC_COLUMNS), frame_metric_rows)
        _write_csv(component_volumes_csv, _preferred_columns(component_volume_rows, COMPONENT_VOLUME_COLUMNS), component_volume_rows)
        _write_csv(timeseries_csv, _preferred_columns(timeseries_rows, TIMESERIES_COLUMNS), timeseries_rows)
        _write_json(
            timeseries_json,
            {
                "schema_version": 1,
                "stage": "volume",
                "run_id": run_id,
                "volume_unit": "nL",
                "row_count": len(timeseries_rows),
                "rows": timeseries_rows,
            },
        )
        _write_json(fov_exit_report_json, fov_report)
        _write_vt_plot(vt_png, frame_metric_rows, run_id=run_id, fov_report=fov_report)
        if sample_panels:
            cv2.imwrite(str(contact_sheet_png), cv2.vconcat(sample_panels))

        summary = {
            "schema_version": 1,
            "stage": "volume",
            "run_id": run_id,
            "run_dir": run_row["run_dir"],
            "pixel_size_um": float(pixel_size_um),
            "volume_unit": "nL",
            "fov_near_bottom_px": int(fov_mod.FOV_NEAR_BOTTOM_PX),
            "sample_capture_indices": list(stage4_run["sample_indices"]),
            "sample_panel_paths": sample_panel_paths,
            "outputs": {
                "frame_metrics_csv": str(frame_metrics_csv),
                "component_volumes_csv": str(component_volumes_csv),
                "volume_timeseries_csv": str(timeseries_csv),
                "volume_timeseries_json": str(timeseries_json),
                "fov_exit_report_json": str(fov_exit_report_json),
                "vt_png": str(vt_png),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
            },
            "first_fov_exit_capture_index": fov_report.get("first_fov_exit_capture_index"),
            "first_fov_exit_capture_id": fov_report.get("first_fov_exit_capture_id"),
            "first_untrusted_capture_index": fov_report.get("first_untrusted_capture_index"),
            "trusted_frame_count": int(summary_counts["trusted_frame_count"]),
            "untrusted_frame_count": int(summary_counts["untrusted_frame_count"]),
            "unavailable_geometry_frame_count": int(summary_counts["unavailable_geometry_frame_count"]),
            "summary": summary_counts,
            "shift_events": list(stage4_run["shift_events"]),
        }
        _write_json(summary_json, summary)
        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": run_row["run_dir"],
                "frame_metrics_csv": str(frame_metrics_csv),
                "component_volumes_csv": str(component_volumes_csv),
                "volume_timeseries_csv": str(timeseries_csv),
                "volume_timeseries_json": str(timeseries_json),
                "fov_exit_report_json": str(fov_exit_report_json),
                "vt_png": str(vt_png),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
                "frame_count": len(frame_metric_rows),
                "component_volume_row_count": len(component_volume_rows),
                "sample_frame_count": len(stage4_run["sample_indices"]),
            }
        )

    manifest = {
        "schema_version": 1,
        "stage": "volume",
        "experiment_root": inventory["experiment_root"],
        "output_root": str(output_path),
        "pixel_size_um": float(pixel_size_um),
        "volume_unit": "nL",
        "fov_near_bottom_px": int(fov_mod.FOV_NEAR_BOTTOM_PX),
        "selected_run_count": len(run_manifests),
        "run_ids": [row["run_id"] for row in run_manifests],
        "search_width_frac": float(search_width_frac),
        "search_top_frac": float(search_top_frac),
        "search_bottom_frac": float(search_bottom_frac),
        "blur_sigma": float(blur_sigma),
        "residual_threshold": int(residual_threshold),
        "shift_threshold_px": float(shift_threshold_px),
        "confidence_threshold": float(confidence_threshold),
        "roi_width_frac": float(roi_width_frac),
        "roi_top_frac": float(roi_top_frac),
        "roi_bottom_frac": float(roi_bottom_frac),
        "corridor_width_frac": float(corridor_width_frac),
        "nozzle_guard_px": int(nozzle_guard_px),
        "min_component_area_px": int(min_component_area_px),
        "sample_count": int(sample_count),
        "extra_frame_indices": list(extra_frame_indices or []),
        "runs": run_manifests,
    }
    manifest_path = output_path / "volume_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest
