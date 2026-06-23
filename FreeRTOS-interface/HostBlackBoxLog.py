import json
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "host_black_box_v1"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _filename_timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_filename_part(value):
    text = str(value or "unknown").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text or "unknown"


def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, deque)):
            return [_json_safe(v) for v in value]
        return str(value)


class HostBlackBoxRecorder:
    def __init__(self, log_dir=None, *, event_limit=512, snapshot_limit=64):
        self.session_id = f"{_filename_timestamp()}-{uuid.uuid4().hex[:8]}"
        if log_dir is None:
            log_dir = Path(__file__).resolve().parents[1] / "logs" / "machine_black_box"
        self.log_dir = Path(log_dir)
        self.events = deque(maxlen=int(event_limit))
        self.snapshots = deque(maxlen=int(snapshot_limit))
        self.last_write_error = None

    def record(self, kind, payload=None, *, monotonic_ns=None):
        entry = {
            "host_time_utc": utc_now_iso(),
            "monotonic_ns": int(monotonic_ns if monotonic_ns is not None else time.monotonic_ns()),
            "kind": str(kind or "event"),
            "payload": _json_safe(dict(payload or {})),
        }
        self.events.append(entry)
        return dict(entry)

    def recent_events(self):
        return [dict(event) for event in self.events]

    def recent_snapshots(self):
        return [dict(snapshot) for snapshot in self.snapshots]

    def write_snapshot(self, snapshot):
        snapshot = dict(snapshot or {})
        reason = str(snapshot.get("reason") or "snapshot")
        snapshot.setdefault("schema_version", SCHEMA_VERSION)
        snapshot.setdefault("host_time_utc", utc_now_iso())
        snapshot.setdefault("session_id", self.session_id)
        snapshot = _json_safe(snapshot)

        filename = (
            f"{_filename_timestamp()}_{_safe_filename_part(self.session_id)}_"
            f"{_safe_filename_part(reason)}.json"
        )
        path = self.log_dir / filename
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2, sort_keys=True)
                fh.write("\n")
            tmp_path.replace(path)
            self.last_write_error = None
            self.snapshots.append(
                {
                    "path": str(path),
                    "reason": reason,
                    "session_id": self.session_id,
                    "host_time_utc": snapshot.get("host_time_utc"),
                }
            )
            return {"path": str(path), "error": None}
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            self.last_write_error = detail
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            return {"path": None, "error": detail}
