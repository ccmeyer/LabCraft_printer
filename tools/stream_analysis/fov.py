from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from tools.stream_analysis.dataset import _clean_text, _int_or_none


TRUST_LABEL_TRUSTED = "trusted"
TRUST_LABEL_UNTRUSTED_FOV_EXIT = "untrusted_fov_exit"
TRUST_LABEL_UNAVAILABLE_GEOMETRY = "unavailable_geometry"

FOV_NEAR_BOTTOM_PX = 32

FOV_EXIT_REASON_TRIGGER = "accepted_fluid_near_bottom_roi"
FOV_EXIT_REASON_LATCHED = "latched_after_accepted_fluid_near_bottom_roi"
FOV_EXIT_REASON_GEOMETRY_UNAVAILABLE = "accepted_fluid_geometry_unavailable"

ACCEPTED_COMPONENT_ROLES = {
    "attached_primary",
    "detached_accepted",
}


def _capture_key(row: dict):
    capture_id = _clean_text(row.get("capture_id"))
    if capture_id is not None:
        return capture_id
    capture_index = _int_or_none(row.get("capture_index"))
    return None if capture_index is None else f"capture_index:{capture_index}"


def _group_component_rows(component_rows: list[dict]):
    grouped = defaultdict(list)
    for row in component_rows:
        grouped[_capture_key(row)].append(row)
    return grouped


def _accepted_component_rows(component_rows: list[dict]):
    return [
        row
        for row in component_rows
        if _clean_text(row.get("component_role")) in ACCEPTED_COMPONENT_ROLES
    ]


def _distance_from_bottom_px(frame_row: dict, component_row: dict):
    roi_y1 = _int_or_none(frame_row.get("roi_y1"))
    last_valid_y_px = _int_or_none(component_row.get("last_valid_y_px"))
    if roi_y1 is None or last_valid_y_px is None:
        return None
    return int((roi_y1 - 1) - last_valid_y_px)


def _frame_component_distances(frame_row: dict, component_rows: list[dict]):
    distances = []
    for component_row in _accepted_component_rows(component_rows):
        distance_from_bottom_px = _distance_from_bottom_px(frame_row, component_row)
        if distance_from_bottom_px is None:
            continue
        distances.append(
            {
                "component_id": _clean_text(component_row.get("component_id")),
                "component_role": _clean_text(component_row.get("component_role")),
                "component_rank": _int_or_none(component_row.get("component_rank")),
                "last_valid_y_px": _int_or_none(component_row.get("last_valid_y_px")),
                "distance_from_bottom_px": int(distance_from_bottom_px),
            }
        )
    distances.sort(
        key=lambda row: (
            int(row["distance_from_bottom_px"]),
            int(row["component_rank"] if row["component_rank"] is not None else 10_000),
            "" if row["component_id"] is None else str(row["component_id"]),
        )
    )
    return distances


def _trigger_components(frame_row: dict, component_rows: list[dict], *, near_bottom_px: int):
    if _clean_text(frame_row.get("silhouette_status")) != "ok":
        return []
    return [
        row
        for row in _frame_component_distances(frame_row, component_rows)
        if int(row["distance_from_bottom_px"]) <= int(near_bottom_px)
    ]


def label_frame_trust(frame_rows: list[dict], component_rows: list[dict], *, near_bottom_px: int = FOV_NEAR_BOTTOM_PX):
    labeled_rows = []
    first_exit_row = None
    first_trigger_components = []
    component_rows_by_capture = _group_component_rows(component_rows)

    for row in frame_rows:
        labeled = deepcopy(row)
        silhouette_status = _clean_text(labeled.get("silhouette_status"))
        geometry_available = silhouette_status == "ok"
        capture_component_rows = component_rows_by_capture.get(_capture_key(labeled), [])
        frame_component_distances = _frame_component_distances(labeled, capture_component_rows)
        trigger_components = _trigger_components(
            labeled,
            capture_component_rows,
            near_bottom_px=int(near_bottom_px),
        )
        min_distance_from_bottom_px = min(
            (int(component["distance_from_bottom_px"]) for component in frame_component_distances),
            default=None,
        )
        accepted_fluid_near_fov_exit = bool(trigger_components)
        fov_exit_triggered = bool(
            first_exit_row is None and geometry_available and accepted_fluid_near_fov_exit
        )
        if fov_exit_triggered:
            first_exit_row = labeled
            first_trigger_components = [dict(component) for component in trigger_components]

        if first_exit_row is None:
            if geometry_available:
                volume_trust_label = TRUST_LABEL_TRUSTED
                volume_is_trusted = True
                fov_exit_reason = None
            else:
                volume_trust_label = TRUST_LABEL_UNAVAILABLE_GEOMETRY
                volume_is_trusted = False
                fov_exit_reason = FOV_EXIT_REASON_GEOMETRY_UNAVAILABLE
        else:
            if fov_exit_triggered:
                fov_exit_reason = FOV_EXIT_REASON_TRIGGER
            else:
                fov_exit_reason = FOV_EXIT_REASON_LATCHED
            volume_trust_label = TRUST_LABEL_UNTRUSTED_FOV_EXIT
            volume_is_trusted = False

        labeled["accepted_fluid_near_fov_exit"] = bool(accepted_fluid_near_fov_exit)
        labeled["fov_near_component_count"] = int(len(trigger_components))
        labeled["min_accepted_fluid_distance_from_bottom_px"] = (
            None
            if min_distance_from_bottom_px is None
            else int(min_distance_from_bottom_px)
        )
        labeled["fov_exit_triggered"] = bool(fov_exit_triggered)
        labeled["fov_exit_reason"] = fov_exit_reason
        labeled["volume_is_trusted"] = bool(volume_is_trusted)
        labeled["volume_trust_label"] = volume_trust_label
        labeled_rows.append(labeled)

    return labeled_rows, build_fov_exit_report(
        labeled_rows,
        trigger_components=first_trigger_components,
        near_bottom_px=int(near_bottom_px),
    )


def build_fov_exit_report(frame_rows: list[dict], *, trigger_components: list[dict], near_bottom_px: int):
    first_trigger = next((row for row in frame_rows if bool(row.get("fov_exit_triggered"))), None)
    first_untrusted = next(
        (
            row
            for row in frame_rows
            if _clean_text(row.get("volume_trust_label")) == TRUST_LABEL_UNTRUSTED_FOV_EXIT
        ),
        None,
    )
    return {
        "schema_version": 1,
        "fov_exit_detected": bool(first_trigger is not None),
        "fov_near_bottom_px": int(near_bottom_px),
        "first_fov_exit_capture_id": None if first_trigger is None else first_trigger.get("capture_id"),
        "first_fov_exit_capture_index": None if first_trigger is None else _int_or_none(first_trigger.get("capture_index")),
        "first_fov_exit_delay_from_emergence_us": None if first_trigger is None else _int_or_none(first_trigger.get("delay_from_emergence_us")),
        "first_fov_exit_flash_delay_us": None if first_trigger is None else _int_or_none(first_trigger.get("flash_delay_us")),
        "first_fov_exit_reason": None if first_trigger is None else first_trigger.get("fov_exit_reason"),
        "first_untrusted_capture_id": None if first_untrusted is None else first_untrusted.get("capture_id"),
        "first_untrusted_capture_index": None if first_untrusted is None else _int_or_none(first_untrusted.get("capture_index")),
        "trigger_geometry": None
        if first_trigger is None
        else {
            "accepted_fluid_near_fov_exit": bool(first_trigger.get("accepted_fluid_near_fov_exit")),
            "fov_near_component_count": _int_or_none(first_trigger.get("fov_near_component_count")),
            "min_accepted_fluid_distance_from_bottom_px": _int_or_none(
                first_trigger.get("min_accepted_fluid_distance_from_bottom_px")
            ),
            "last_valid_y_px": _int_or_none(first_trigger.get("last_valid_y_px")),
            "roi_y1": _int_or_none(first_trigger.get("roi_y1")),
            "selected_component_bottom_y_px": _int_or_none(first_trigger.get("selected_component_bottom_y_px")),
            "selected_component_bbox_h_px": _int_or_none(first_trigger.get("selected_component_bbox_h_px")),
            "selected_anchor_center_x_px": first_trigger.get("selected_anchor_center_x_px"),
            "tracked_nozzle_x_px": first_trigger.get("tracked_nozzle_x_px"),
            "tracked_nozzle_y_px": first_trigger.get("tracked_nozzle_y_px"),
            "tracked_confidence": first_trigger.get("tracked_confidence"),
        },
        "trigger_components": list(trigger_components),
    }
