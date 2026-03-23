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
    HELP_TEXT = (
        "[g] draw geometry  [m] draw meniscus  [1-6] set status  [c] confidence  "
        "[r] review  [t] quality tags  [n] next  [p] prev  [s] save+next  [q] quit"
    )

    def __init__(self, session: RefuelDatasetAnnotationSession):
        self.session = session
        self.frame_ids = session.get_frame_order()
        self.index = 0
        self.show_seed = True

    def _load_image(self, frame_id):
        import matplotlib.image as mpimg

        return mpimg.imread(self.session.get_image_path(frame_id))

    def _draw_line(self, ax, line, *, color, linestyle="-", linewidth=1.5, label=None):
        if not line:
            return
        pts = normalize_line(line)
        xs = [pts[0][0], pts[1][0]]
        ys = [pts[0][1], pts[1][1]]
        ax.plot(xs, ys, color=color, linestyle=linestyle, linewidth=linewidth, label=label)

    def _render(self, frame_id, proposed):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.imshow(self._load_image(frame_id))
        ax.set_title(f"{frame_id} | {self.HELP_TEXT}")
        ax.axis("off")

        seed = self.session.get_seed(frame_id) if self.show_seed else None
        if seed:
            geometry = seed.get("predicted_channel_geometry") or {}
            for key in ("left_wall", "right_wall", "top_line", "bottom_line"):
                self._draw_line(ax, geometry.get(key), color="#f4d35e", linestyle="--", linewidth=1.0)
            self._draw_line(ax, seed.get("predicted_meniscus_line"), color="#f4d35e", linestyle="--", linewidth=1.0)

        geometry = (proposed or {}).get("channel_geometry") or {}
        for key in ("left_wall", "right_wall", "top_line", "bottom_line"):
            self._draw_line(ax, geometry.get(key), color="#5bc0eb", linewidth=1.4)
        self._draw_line(ax, (proposed or {}).get("meniscus_line"), color="#e55934", linewidth=1.6)
        fig.tight_layout()
        return fig, ax

    @staticmethod
    def _collect_lines(plt_module, count):
        pts = plt_module.ginput(count, timeout=-1)
        if len(pts) != count:
            return None
        lines = []
        for idx in range(0, count, 2):
            lines.append(normalize_line([pts[idx], pts[idx + 1]]))
        return lines

    def run(self):
        if not self.frame_ids:
            print("No frames found in the selected run.")
            return 1

        import matplotlib.pyplot as plt

        while 0 <= self.index < len(self.frame_ids):
            frame_id = self.frame_ids[self.index]
            proposed = self.session.propose_label(frame_id)
            while True:
                fig, _ax = self._render(frame_id, proposed)
                plt.show(block=False)
                print(f"\nFrame {self.index + 1}/{len(self.frame_ids)}: {frame_id}")
                print(self.HELP_TEXT)

                command = input("Command: ").strip().lower()
                if command == "q":
                    plt.close(fig)
                    return 0
                if command == "g":
                    print("Click left wall, right wall, top line, and bottom line (2 points each).")
                    lines = self._collect_lines(plt, 8)
                    if lines:
                        proposed["channel_geometry"] = {
                            "left_wall": lines[0],
                            "right_wall": lines[1],
                            "top_line": lines[2],
                            "bottom_line": lines[3],
                        }
                        proposed["geometry_source"] = "adjusted"
                    plt.close(fig)
                    continue
                if command == "m":
                    print("Click the meniscus line endpoints.")
                    lines = self._collect_lines(plt, 2)
                    if lines:
                        proposed["meniscus_line"] = lines[0]
                        proposed["status"] = "visible"
                    plt.close(fig)
                    continue
                if command in {"1", "2", "3", "4", "5", "6"}:
                    proposed["status"] = {
                        "1": "visible",
                        "2": "full",
                        "3": "empty",
                        "4": "occluded",
                        "5": "bad_frame",
                        "6": "skip",
                    }[command]
                    if proposed["status"] != "visible":
                        proposed["meniscus_line"] = None
                    plt.close(fig)
                    continue
                if command == "c":
                    next_conf = {"high": "medium", "medium": "low", "low": "high"}
                    proposed["confidence"] = next_conf.get(str(proposed.get("confidence") or "medium"), "high")
                    print(f"Confidence -> {proposed['confidence']}")
                    plt.close(fig)
                    continue
                if command == "r":
                    next_state = {"draft": "reviewed", "reviewed": "final", "final": "draft"}
                    proposed["review_state"] = next_state.get(str(proposed.get("review_state") or "draft"), "draft")
                    print(f"Review state -> {proposed['review_state']}")
                    plt.close(fig)
                    continue
                if command == "t":
                    raw = input("Quality tags (comma-separated): ").strip()
                    proposed["quality_tags"] = dedupe_tags(raw.split(","))
                    plt.close(fig)
                    continue
                if command == "p":
                    self.index = max(0, self.index - 1)
                    plt.close(fig)
                    break
                if command == "n":
                    self.index = min(len(self.frame_ids) - 1, self.index + 1)
                    plt.close(fig)
                    break
                if command == "s":
                    try:
                        saved = self.session.save_label(proposed)
                        print(
                            f"Saved {saved['frame_id']} as {saved['status']} "
                            f"(review={saved['review_state']}, confidence={saved['confidence']})."
                        )
                        self.index = min(len(self.frame_ids), self.index + 1)
                        plt.close(fig)
                        break
                    except Exception as exc:
                        print(f"Save failed: {exc}")
                        plt.close(fig)
                        continue

                print("Unknown command.")
                plt.close(fig)
        return 0


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
