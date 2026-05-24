from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
VALID_REVIEW_STATES = {"draft", "reviewed", "final"}
VALID_STATUSES = {"visible", "full", "empty", "occluded", "bad_frame", "skip"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_QUALITY_TAGS = {
    "glare",
    "blur",
    "bubble",
    "reflection",
    "cropped",
    "motion",
    "double_edge",
    "low_contrast",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def dedupe_tags(tags) -> list[str]:
    out = []
    seen = set()
    for raw in tags or []:
        value = str(raw or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(value)
    return out


def normalize_line(line) -> list[list[int]] | None:
    if not line:
        return None
    if len(line) != 2:
        raise ValueError("Line must contain exactly two points.")
    points = []
    for point in line:
        if point is None or len(point) != 2:
            raise ValueError("Each line point must contain exactly two coordinates.")
        points.append([int(round(float(point[0]))), int(round(float(point[1])))])
    return points


def _raw_dimensions(raw_shape) -> tuple[int, int]:
    if raw_shape is None or len(raw_shape) < 2:
        raise ValueError("raw_shape must contain image height and width.")
    return int(raw_shape[0]), int(raw_shape[1])


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def rotate_image_for_annotation(image):
    if image is None:
        return None
    import numpy as np

    return np.rot90(image, k=1)


def raw_point_to_display(point, raw_shape) -> list[int]:
    raw_h, raw_w = _raw_dimensions(raw_shape)
    x_raw = _clamp(int(round(float(point[0]))), 0, raw_w - 1)
    y_raw = _clamp(int(round(float(point[1]))), 0, raw_h - 1)
    return [y_raw, raw_w - 1 - x_raw]


def display_point_to_raw(point, raw_shape) -> list[int]:
    raw_h, raw_w = _raw_dimensions(raw_shape)
    x_disp = _clamp(int(round(float(point[0]))), 0, raw_h - 1)
    y_disp = _clamp(int(round(float(point[1]))), 0, raw_w - 1)
    return [raw_w - 1 - y_disp, x_disp]


def raw_line_to_display(line, raw_shape) -> list[list[int]] | None:
    line = normalize_line(line)
    if line is None:
        return None
    return [raw_point_to_display(point, raw_shape) for point in line]


def display_line_to_raw(line, raw_shape) -> list[list[int]] | None:
    line = normalize_line(line)
    if line is None:
        return None
    return [display_point_to_raw(point, raw_shape) for point in line]


def _mean_y(line) -> float | None:
    line = normalize_line(line)
    if line is None:
        return None
    return float(line[0][1] + line[1][1]) / 2.0


def _mean_x(line) -> float | None:
    line = normalize_line(line)
    if line is None:
        return None
    return float(line[0][0] + line[1][0]) / 2.0


def compute_derived(channel_geometry, meniscus_line) -> dict:
    geometry = dict(channel_geometry or {})
    left_wall = normalize_line(geometry.get("left_wall"))
    right_wall = normalize_line(geometry.get("right_wall"))
    bottom_line = normalize_line(geometry.get("bottom_line"))
    meniscus_line = normalize_line(meniscus_line)

    center_x = None
    if left_wall is not None and right_wall is not None:
        center_x = float((_mean_x(left_wall) + _mean_x(right_wall)) / 2.0)

    meniscus_y = _mean_y(meniscus_line)
    bottom_y = _mean_y(bottom_line)
    level_from_bottom = None
    if meniscus_y is not None and bottom_y is not None:
        level_from_bottom = float(bottom_y - meniscus_y)

    return {
        "channel_center_x_px": center_x,
        "meniscus_y_px": meniscus_y,
        "channel_bottom_y_px": bottom_y,
        "level_from_bottom_px": level_from_bottom,
    }


def validate_label_record(record: dict):
    if int(record.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError("schema_version must be 1.")
    if str(record.get("frame_id") or "").strip() == "":
        raise ValueError("frame_id is required.")
    if str(record.get("scene_id") or "").strip() == "":
        raise ValueError("scene_id is required.")

    review_state = str(record.get("review_state") or "draft")
    if review_state not in VALID_REVIEW_STATES:
        raise ValueError(f"Unsupported review_state: {review_state}")

    status = str(record.get("status") or "")
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {status}")

    confidence = str(record.get("confidence") or "medium")
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(f"Unsupported confidence: {confidence}")

    geometry_source = str(record.get("geometry_source") or "manual")
    if geometry_source not in {"manual", "copied_scene", "adjusted"}:
        raise ValueError(f"Unsupported geometry_source: {geometry_source}")

    quality_tags = dedupe_tags(record.get("quality_tags") or [])
    unknown_tags = [tag for tag in quality_tags if tag not in VALID_QUALITY_TAGS]
    if unknown_tags:
        raise ValueError(f"Unsupported quality_tags: {unknown_tags}")

    channel_geometry = record.get("channel_geometry")
    meniscus_line = record.get("meniscus_line")

    if status == "visible":
        if not isinstance(channel_geometry, dict):
            raise ValueError("visible labels require channel_geometry.")
        for key in ("left_wall", "right_wall", "top_line", "bottom_line"):
            if normalize_line(channel_geometry.get(key)) is None:
                raise ValueError(f"visible labels require channel_geometry.{key}.")
        if normalize_line(meniscus_line) is None:
            raise ValueError("visible labels require meniscus_line.")
    elif status in {"full", "empty", "occluded"}:
        if not isinstance(channel_geometry, dict):
            raise ValueError(f"{status} labels require channel_geometry.")
        for key in ("left_wall", "right_wall", "top_line", "bottom_line"):
            if normalize_line(channel_geometry.get(key)) is None:
                raise ValueError(f"{status} labels require channel_geometry.{key}.")
        if meniscus_line is not None:
            raise ValueError(f"{status} labels must not include meniscus_line.")

    derived = record.get("derived") or {}
    if status == "visible" and derived.get("level_from_bottom_px") is None:
        raise ValueError("visible labels must include derived.level_from_bottom_px.")


def build_label_record(
    *,
    frame_id,
    scene_id,
    annotator_id,
    status,
    review_state="draft",
    confidence="medium",
    geometry_source="manual",
    quality_tags=None,
    notes="",
    channel_geometry=None,
    meniscus_line=None,
):
    geometry = None if channel_geometry is None else {
        key: normalize_line(value)
        for key, value in dict(channel_geometry).items()
        if value is not None
    }
    meniscus = normalize_line(meniscus_line) if meniscus_line is not None else None
    record = {
        "schema_version": int(SCHEMA_VERSION),
        "frame_id": str(frame_id),
        "scene_id": str(scene_id),
        "annotator_id": str(annotator_id or "unknown"),
        "annotated_at_utc": now_utc(),
        "review_state": str(review_state or "draft"),
        "status": str(status),
        "confidence": str(confidence or "medium"),
        "geometry_source": str(geometry_source or "manual"),
        "quality_tags": dedupe_tags(quality_tags),
        "notes": str(notes or ""),
        "channel_geometry": geometry,
        "meniscus_line": meniscus,
        "derived": compute_derived(geometry, meniscus),
    }
    validate_label_record(record)
    return record


class RefuelDatasetAnnotationSession:
    def __init__(self, run_dir, *, annotator_id="unknown"):
        self.run_dir = Path(run_dir).resolve()
        self.annotator_id = str(annotator_id or "unknown")
        self.run_meta = load_json(self.run_dir / "run_meta.json")
        self.events_path = self.run_dir / "events.jsonl"
        self.scenes_path = self.run_dir / "scenes.jsonl"
        self.frames_path = self.run_dir / "frames.jsonl"
        self.analysis_path = self.run_dir / "analysis.jsonl"
        self.labels_path = self.run_dir / "labels.jsonl"

        self.scenes = load_jsonl(self.scenes_path)
        self.frames = load_jsonl(self.frames_path)
        self.analysis_rows = load_jsonl(self.analysis_path)
        self.labels = load_jsonl(self.labels_path)

        self.scenes_by_id = {row["scene_id"]: row for row in self.scenes if row.get("scene_id")}
        self.frames_by_id = {row["frame_id"]: row for row in self.frames if row.get("frame_id")}
        self.analysis_by_frame = {
            row["frame_id"]: row for row in self.analysis_rows if row.get("frame_id")
        }
        self.labels_by_frame = {
            row["frame_id"]: row for row in self.labels if row.get("frame_id")
        }
        self._frame_order = [
            row["frame_id"]
            for row in sorted(
                self.frames,
                key=lambda row: (
                    int(self.scenes_by_id.get(row.get("scene_id"), {}).get("scene_index", 0)),
                    int(row.get("capture_index", 0)),
                ),
            )
            if row.get("frame_id")
        ]

    def get_frame_order(self) -> list[str]:
        return list(self._frame_order)

    def get_frame(self, frame_id: str) -> dict:
        return dict(self.frames_by_id[frame_id])

    def get_scene(self, scene_id: str) -> dict | None:
        scene = self.scenes_by_id.get(scene_id)
        return None if scene is None else dict(scene)

    def get_seed(self, frame_id: str) -> dict | None:
        seed = self.analysis_by_frame.get(frame_id)
        return None if seed is None else dict(seed)

    def get_label(self, frame_id: str) -> dict | None:
        label = self.labels_by_frame.get(frame_id)
        return None if label is None else deepcopy(label)

    def get_image_path(self, frame_id: str) -> Path:
        frame = self.frames_by_id[frame_id]
        return self.run_dir / frame["image_relpath"]

    def get_scene_geometry(self, scene_id: str) -> dict | None:
        for frame_id in self._frame_order:
            frame = self.frames_by_id[frame_id]
            if frame.get("scene_id") != scene_id:
                continue
            label = self.labels_by_frame.get(frame_id)
            if not label:
                continue
            geometry = label.get("channel_geometry")
            if isinstance(geometry, dict):
                return deepcopy(geometry)
        return None

    def propose_label(self, frame_id: str) -> dict:
        existing = self.get_label(frame_id)
        if existing is not None:
            return existing

        frame = self.get_frame(frame_id)
        scene_id = frame["scene_id"]
        scene_geometry = self.get_scene_geometry(scene_id)
        seed = self.get_seed(frame_id) or {}
        status = str(seed.get("predicted_status") or "skip")
        if status == "not_found":
            status = "skip"
        geometry = scene_geometry or seed.get("predicted_channel_geometry")
        meniscus = seed.get("predicted_meniscus_line") if status == "visible" else None
        geometry_source = "copied_scene" if scene_geometry else "manual"
        confidence = "medium" if seed else "low"
        if status in {"bad_frame", "skip"}:
            geometry = None
            meniscus = None
        return {
            "schema_version": int(SCHEMA_VERSION),
            "frame_id": frame_id,
            "scene_id": scene_id,
            "annotator_id": self.annotator_id,
            "annotated_at_utc": now_utc(),
            "review_state": "draft",
            "status": status,
            "confidence": confidence,
            "geometry_source": geometry_source,
            "quality_tags": [],
            "notes": "",
            "channel_geometry": deepcopy(geometry),
            "meniscus_line": deepcopy(meniscus),
            "derived": compute_derived(geometry, meniscus),
        }

    def propose_interactive_label(self, frame_id: str) -> dict:
        existing = self.get_label(frame_id)
        if existing is not None:
            return existing

        frame = self.get_frame(frame_id)
        scene_id = frame["scene_id"]
        scene_geometry = self.get_scene_geometry(scene_id)
        geometry_source = "copied_scene" if scene_geometry else "manual"
        return {
            "schema_version": int(SCHEMA_VERSION),
            "frame_id": frame_id,
            "scene_id": scene_id,
            "annotator_id": self.annotator_id,
            "annotated_at_utc": now_utc(),
            "review_state": "draft",
            "status": "visible",
            "confidence": "medium",
            "geometry_source": geometry_source,
            "quality_tags": [],
            "notes": "",
            "channel_geometry": deepcopy(scene_geometry),
            "meniscus_line": None,
            "derived": compute_derived(scene_geometry, None),
        }

    def save_label(self, record: dict):
        payload = deepcopy(record)
        payload["annotator_id"] = str(payload.get("annotator_id") or self.annotator_id)
        payload["annotated_at_utc"] = now_utc()
        payload["quality_tags"] = dedupe_tags(payload.get("quality_tags") or [])
        payload["derived"] = compute_derived(payload.get("channel_geometry"), payload.get("meniscus_line"))
        validate_label_record(payload)

        self.labels_by_frame[payload["frame_id"]] = payload
        ordered = [self.labels_by_frame[frame_id] for frame_id in self._frame_order if frame_id in self.labels_by_frame]
        write_jsonl(self.labels_path, ordered)
        self._append_annotation_event(payload)
        return payload

    def _append_annotation_event(self, label: dict):
        existing = load_jsonl(self.events_path)
        event_index = len(existing) + 1
        row = {
            "schema_version": int(SCHEMA_VERSION),
            "event_id": str(uuid.uuid4()),
            "event_index": int(event_index),
            "ts_utc": now_utc(),
            "run_id": str(self.run_meta.get("run_id") or self.run_dir.name),
            "process_name": str(self.run_meta.get("process_name") or ""),
            "phase_name": str(self.run_meta.get("phase_name") or ""),
            "event_type": "annotation_completed",
            "state_name": "",
            "level": "info",
            "payload": {
                "frame_id": label["frame_id"],
                "scene_id": label["scene_id"],
                "review_state": label.get("review_state"),
                "status": label.get("status"),
                "annotator_id": label.get("annotator_id"),
            },
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


class InteractiveRefuelAnnotator:
    GEOMETRY_KEYS = ("left_wall", "right_wall", "top_line", "bottom_line")
    FIGURE_LAYOUT = {"left": 0.03, "right": 0.98, "bottom": 0.03, "top": 0.80}
    GEOMETRY_CLICK_LABELS = (
        "top-left corner",
        "top-right corner",
        "bottom-right corner",
        "bottom-left corner",
    )
    STATUS_BY_KEY = {
        "1": "visible",
        "2": "full",
        "3": "empty",
        "4": "occluded",
        "5": "bad_frame",
        "6": "skip",
    }
    HELP_TEXT = (
        "g geometry | m meniscus | 1 visible | 2 full | 3 empty | 4 occluded | "
        "5 bad | 6 skip | x clear meniscus | u undo | esc cancel | o seeds | s save | n/p nav | q quit"
    )

    def __init__(self, session: RefuelDatasetAnnotationSession):
        self.session = session
        self.frame_ids = session.get_frame_order()
        self.index = 0
        self.show_seed = False
        self.mode = None
        self.pending_points = []
        self.proposed = None
        self.raw_image = None
        self.display_image = None
        self.raw_shape = None
        self.fig = None
        self.ax = None
        self.plt = None
        self.status_message = ""

    def _load_image(self, frame_id):
        import matplotlib.image as mpimg

        return mpimg.imread(self.session.get_image_path(frame_id))

    def _draw_display_line(self, ax, line, *, color, linestyle="-", linewidth=1.5, marker=None):
        if not line:
            return
        pts = normalize_line(line)
        xs = [pts[0][0], pts[1][0]]
        ys = [pts[0][1], pts[1][1]]
        ax.plot(xs, ys, color=color, linestyle=linestyle, linewidth=linewidth, marker=marker)

    def _draw_raw_line(self, ax, line, *, color, linestyle="-", linewidth=1.5, marker=None):
        if line is None or self.raw_shape is None:
            return
        self._draw_display_line(
            ax,
            raw_line_to_display(line, self.raw_shape),
            color=color,
            linestyle=linestyle,
            linewidth=linewidth,
            marker=marker,
        )

    def _ensure_figure(self):
        if self.fig is not None and self.ax is not None:
            return
        import matplotlib.pyplot as plt

        self.plt = plt
        self.fig, self.ax = plt.subplots(figsize=(9, 7))
        try:
            self.fig.canvas.manager.set_window_title("Refuel Dataset Annotator")
        except Exception:
            pass
        self.fig.subplots_adjust(**self.FIGURE_LAYOUT)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

    def _current_frame_id(self):
        if not (0 <= self.index < len(self.frame_ids)):
            return None
        return self.frame_ids[self.index]

    def _load_current_frame(self, message="", start_mode=None):
        frame_id = self._current_frame_id()
        if frame_id is None:
            self.status_message = "All frames annotated."
            self._close_figure()
            return
        self.proposed = self.session.propose_interactive_label(frame_id)
        self.raw_image = self._load_image(frame_id)
        self.raw_shape = self.raw_image.shape
        self.display_image = rotate_image_for_annotation(self.raw_image)
        self.mode = None
        self.pending_points = []
        self.status_message = message
        if start_mode == "meniscus":
            if self._has_complete_geometry():
                self.mode = "meniscus"
            else:
                extra = "Geometry is not set; press g to draw corners."
                self.status_message = f"{message} {extra}".strip()
        self._render()

    def _render(self):
        self._ensure_figure()
        if self.ax is None or self.display_image is None or self.proposed is None:
            return

        frame_id = self._current_frame_id()
        frame = self.session.get_frame(frame_id)
        scene_id = frame.get("scene_id") or self.proposed.get("scene_id") or "-"
        ax = self.ax
        ax.clear()
        ax.imshow(self.display_image)
        ax.set_title(self._build_title(frame_id, scene_id), fontsize=9)
        ax.axis("off")

        seed = self.session.get_seed(frame_id) if self.show_seed else None
        if seed:
            geometry = seed.get("predicted_channel_geometry") or {}
            for key in self.GEOMETRY_KEYS:
                self._draw_raw_line(ax, geometry.get(key), color="#f4d35e", linestyle="--", linewidth=1.0)
            self._draw_raw_line(
                ax,
                seed.get("predicted_meniscus_line"),
                color="#f4d35e",
                linestyle="--",
                linewidth=1.0,
            )

        geometry = (self.proposed or {}).get("channel_geometry") or {}
        for key in self.GEOMETRY_KEYS:
            self._draw_raw_line(ax, geometry.get(key), color="#1f9acb", linewidth=1.8, marker="o")
        self._draw_raw_line(
            ax,
            (self.proposed or {}).get("meniscus_line"),
            color="#e55934",
            linewidth=2.0,
            marker="x",
        )
        self._draw_pending_points(ax)

        height, width = int(self.display_image.shape[0]), int(self.display_image.shape[1])
        ax.set_xlim(-0.5, width - 0.5)
        ax.set_ylim(height - 0.5, -0.5)
        self.fig.canvas.draw_idle()

    def _draw_pending_points(self, ax):
        if not self.pending_points or self.raw_shape is None:
            return
        display_points = [raw_point_to_display(point, self.raw_shape) for point in self.pending_points]
        xs = [point[0] for point in display_points]
        ys = [point[1] for point in display_points]
        color = "#1f9acb" if self.mode == "geometry" else "#e55934"
        marker = "o" if self.mode == "geometry" else "x"
        ax.scatter(xs, ys, color=color, marker=marker, s=42, zorder=5)
        if self.mode == "geometry":
            line_ranges = range(0, len(display_points) - 1)
        else:
            line_ranges = range(0, len(display_points) - 1, 2)
        for idx in line_ranges:
            self._draw_display_line(
                ax,
                [display_points[idx], display_points[idx + 1]],
                color=color,
                linestyle=":",
                linewidth=1.4,
            )

    def _build_title(self, frame_id, scene_id):
        mode_text = self.mode or "idle"
        status = (self.proposed or {}).get("status") or "-"
        overlay = "on" if self.show_seed else "off"
        title = (
            f"{self.index + 1}/{len(self.frame_ids)} {frame_id} | scene {scene_id} | "
            f"status {status} | mode {mode_text} | seed overlay {overlay}"
        )
        lines = [title, self._mode_instruction(), self.HELP_TEXT]
        lines.append(self.status_message or " ")
        return "\n".join(lines)

    def _mode_instruction(self):
        if self.mode == "geometry":
            count = len(self.pending_points)
            if count < len(self.GEOMETRY_CLICK_LABELS):
                return f"Click {self.GEOMETRY_CLICK_LABELS[count]}."
            return "Geometry points complete."
        if self.mode == "meniscus":
            count = len(self.pending_points)
            if count == 0:
                return "Click meniscus point 1."
            if count == 1:
                return "Click meniscus point 2."
            return "Meniscus points complete."
        return "Choose a mode or status."

    def run(self):
        if not self.frame_ids:
            print("No frames found in the selected run.")
            return 1

        import matplotlib.pyplot as plt

        self.plt = plt
        self._ensure_figure()
        self._load_current_frame()
        print("Refuel dataset annotator controls:")
        print(self.HELP_TEXT)
        plt.show()
        return 0

    def _on_key(self, event):
        key = str(getattr(event, "key", "") or "").lower()
        if not key:
            return
        if key == "q":
            self._close_figure()
            return
        if key == "g":
            self._start_mode("geometry")
            return
        if key == "m":
            self._start_mode("meniscus")
            return
        if key in {"escape", "esc"}:
            self._cancel_mode()
            return
        if key == "u":
            self._undo_pending_point()
            return
        if key == "x":
            self._clear_meniscus()
            return
        if key == "o":
            self.show_seed = not self.show_seed
            self.status_message = "Seed overlay enabled." if self.show_seed else "Seed overlay hidden."
            self._render()
            return
        if key in self.STATUS_BY_KEY:
            self._set_status(self.STATUS_BY_KEY[key])
            return
        if key == "c":
            self._cycle_confidence()
            return
        if key == "r":
            self._cycle_review_state()
            return
        if key == "s":
            self._save_and_advance()
            return
        if key == "n":
            self._move(1)
            return
        if key == "p":
            self._move(-1)
            return
        self.status_message = f"Unknown key: {key}"
        self._render()

    def _on_click(self, event):
        if self.mode not in {"geometry", "meniscus"}:
            return
        if self.ax is not None and getattr(event, "inaxes", None) is not self.ax:
            return
        if self.raw_shape is None or getattr(event, "xdata", None) is None or getattr(event, "ydata", None) is None:
            return

        point = display_point_to_raw([event.xdata, event.ydata], self.raw_shape)
        self.pending_points.append(point)
        if self.mode == "geometry" and len(self.pending_points) >= 4:
            self._complete_geometry()
            return
        if self.mode == "meniscus" and len(self.pending_points) >= 2:
            self._complete_meniscus()
            return
        self.status_message = ""
        self._render()

    def _start_mode(self, mode):
        self.mode = mode
        self.pending_points = []
        self.status_message = ""
        self._render()

    def _cancel_mode(self):
        self.mode = None
        self.pending_points = []
        self.status_message = "Drawing mode cancelled."
        self._render()

    def _undo_pending_point(self):
        if not self.pending_points:
            self.status_message = "No pending point to undo."
        else:
            self.pending_points.pop()
            self.status_message = "Undid last pending point."
        self._render()

    def _complete_geometry(self):
        top_left, top_right, bottom_right, bottom_left = [
            list(point) for point in self.pending_points[:4]
        ]
        self.proposed["channel_geometry"] = {
            "left_wall": normalize_line([top_left, bottom_left]),
            "right_wall": normalize_line([top_right, bottom_right]),
            "top_line": normalize_line([top_left, top_right]),
            "bottom_line": normalize_line([bottom_left, bottom_right]),
        }
        self.proposed["geometry_source"] = "adjusted"
        self.mode = None
        self.pending_points = []
        self.status_message = "Geometry set."
        if str(self.proposed.get("status") or "") == "visible":
            self.proposed["meniscus_line"] = None
            self.mode = "meniscus"
            self.status_message = "Geometry set. Click two meniscus endpoints."
            self._render()
            return
        self._save_if_complete_for_current_status()

    def _complete_meniscus(self):
        self.proposed["meniscus_line"] = normalize_line([self.pending_points[0], self.pending_points[1]])
        self.proposed["status"] = "visible"
        self.mode = None
        self.pending_points = []
        self.status_message = "Meniscus set."
        self._save_if_complete_for_current_status()

    def _set_status(self, status):
        self.proposed["status"] = status
        self.mode = None
        self.pending_points = []
        if status != "visible":
            self.proposed["meniscus_line"] = None
        if status in {"bad_frame", "skip"}:
            self.proposed["channel_geometry"] = None
            self.proposed["geometry_source"] = "manual"
        self.status_message = f"Status set to {status}."
        self._save_if_complete_for_current_status()

    def _save_if_complete_for_current_status(self):
        status = str((self.proposed or {}).get("status") or "")
        if status in {"bad_frame", "skip"}:
            self._save_and_advance()
            return
        if status in {"full", "empty", "occluded"}:
            if self._has_complete_geometry():
                self._save_and_advance()
            else:
                self.status_message = f"{status} labels require geometry. Press g to draw it."
                self._render()
            return
        if status == "visible":
            if self._has_complete_geometry() and self._has_meniscus():
                self._save_and_advance()
            else:
                self._render()
            return
        self._render()

    def _has_complete_geometry(self):
        geometry = (self.proposed or {}).get("channel_geometry")
        if not isinstance(geometry, dict):
            return False
        try:
            return all(normalize_line(geometry.get(key)) is not None for key in self.GEOMETRY_KEYS)
        except Exception:
            return False

    def _has_meniscus(self):
        try:
            return normalize_line((self.proposed or {}).get("meniscus_line")) is not None
        except Exception:
            return False

    def _clear_meniscus(self):
        if self.proposed is not None:
            self.proposed["meniscus_line"] = None
        self.mode = None
        self.pending_points = []
        self.status_message = "Meniscus cleared. Press m to redraw it."
        self._render()

    def _cycle_confidence(self):
        next_conf = {"high": "medium", "medium": "low", "low": "high"}
        current = str((self.proposed or {}).get("confidence") or "medium")
        self.proposed["confidence"] = next_conf.get(current, "high")
        self.status_message = f"Confidence set to {self.proposed['confidence']}."
        self._render()

    def _cycle_review_state(self):
        next_state = {"draft": "reviewed", "reviewed": "final", "final": "draft"}
        current = str((self.proposed or {}).get("review_state") or "draft")
        self.proposed["review_state"] = next_state.get(current, "draft")
        self.status_message = f"Review state set to {self.proposed['review_state']}."
        self._render()

    def _save_and_advance(self):
        try:
            saved = self.session.save_label(self.proposed)
        except Exception as exc:
            self.status_message = f"Save failed: {exc}"
            self._render()
            return False

        self.index += 1
        if self.index >= len(self.frame_ids):
            print("All frames annotated.")
            self._close_figure()
            return True
        start_mode = "meniscus" if saved.get("status") == "visible" else None
        self._load_current_frame(f"Saved {saved['frame_id']} as {saved['status']}.", start_mode=start_mode)
        return True

    def _move(self, delta):
        new_index = _clamp(self.index + int(delta), 0, len(self.frame_ids) - 1)
        if new_index == self.index:
            self.status_message = "Already at dataset boundary."
            self._render()
            return
        self.index = new_index
        self._load_current_frame()

    def _close_figure(self):
        fig = self.fig
        self.fig = None
        self.ax = None
        if fig is None:
            return
        if self.plt is None:
            import matplotlib.pyplot as plt

            self.plt = plt
        self.plt.close(fig)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Annotate a refuel dataset run.")
    parser.add_argument("run_dir", help="Path to a RefuelLevelDatasetCaptureProcess run directory.")
    parser.add_argument("--annotator", default=os.getenv("USERNAME") or "unknown", help="Annotator id.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a summary of scenes/frames/labels without opening the interactive annotator.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    session = RefuelDatasetAnnotationSession(args.run_dir, annotator_id=args.annotator)
    if args.summary:
        print(json.dumps(
            {
                "run_dir": str(session.run_dir),
                "frame_count": len(session.frames),
                "scene_count": len(session.scenes),
                "label_count": len(session.labels_by_frame),
            },
            indent=2,
        ))
        return 0

    annotator = InteractiveRefuelAnnotator(session)
    return annotator.run()


if __name__ == "__main__":
    raise SystemExit(main())
