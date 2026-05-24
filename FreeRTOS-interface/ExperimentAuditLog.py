from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _json_default(obj: Any) -> Any:
    try:
        import numpy as np

        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass

    if isinstance(obj, (Path, os.PathLike)):
        return os.fspath(obj)

    try:
        return obj.__json__()
    except Exception:
        pass

    return str(obj)


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(_normalize_json_value(key)): _normalize_json_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, set):
        return [_normalize_json_value(item) for item in sorted(value, key=str)]
    return _json_default(value)


class ExperimentAuditLog:
    """Append-only JSONL writer for high-level experiment audit events."""

    SCHEMA_VERSION = 1
    FILE_NAME = "experiment_audit.jsonl"
    VALID_LEVELS = {"info", "warning", "error"}

    def __init__(
        self,
        model=None,
        audit_path=None,
        clock: Callable[[], Any] | None = None,
        uuid_factory: Callable[[], Any] | None = None,
    ):
        self.model = model
        self.audit_path = os.fspath(audit_path) if audit_path is not None else None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.uuid_factory = uuid_factory or uuid.uuid4
        self._first_event_time = None
        self._last_error = None

    def get_audit_path(self) -> str | None:
        if self.audit_path:
            return os.path.abspath(os.fspath(self.audit_path))

        exp = getattr(self.model, "experiment_model", None)
        exp_dir = getattr(exp, "experiment_dir_path", None)
        if not exp_dir:
            return None
        return os.path.abspath(os.path.join(os.fspath(exp_dir), self.FILE_NAME))

    def get_last_error(self) -> str | None:
        return self._last_error

    def record(self, event_type, summary, details=None, level="info", context=None) -> dict | None:
        try:
            now = self._coerce_clock_value(self.clock())
            path_text = self.get_audit_path()
            if not path_text:
                self._set_error("No experiment audit path is available.")
                return None

            first = self._first_event_time or now
            elapsed_s = max(0.0, (now - first).total_seconds())
            event = {
                "schema_version": int(self.SCHEMA_VERSION),
                "event_id": str(self.uuid_factory()),
                "timestamp_utc": self._format_timestamp(now),
                "elapsed_s": float(elapsed_s),
                "event_type": str(event_type or ""),
                "level": self._normalize_level(level),
                "summary": str(summary or ""),
                "details": self._normalize_object(details),
                "context": self._build_context(context),
            }
            encoded = json.dumps(event, default=_json_default, separators=(",", ":"))
            path = Path(path_text)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        except Exception as exc:
            self._set_error(f"Failed to append audit event: {exc}")
            return None

        if self._first_event_time is None:
            self._first_event_time = now
        self._last_error = None
        return event

    @classmethod
    def _normalize_level(cls, level) -> str:
        value = str(level or "info").strip().lower()
        return value if value in cls.VALID_LEVELS else "info"

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _coerce_clock_value(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_object(value) -> dict:
        if value is None:
            return {}
        if isinstance(value, dict):
            normalized = _normalize_json_value(value)
            return normalized if isinstance(normalized, dict) else {"value": normalized}
        return {"value": _normalize_json_value(value)}

    def _build_context(self, context=None) -> dict:
        payload = {}
        exp = getattr(self.model, "experiment_model", None)
        if exp is not None:
            metadata = getattr(exp, "metadata", None)
            if isinstance(metadata, dict):
                payload["experiment_name"] = str(metadata.get("name") or "")
            payload["experiment_dir"] = self._clean_path(getattr(exp, "experiment_dir_path", None))
            payload["experiment_file_path"] = self._clean_path(getattr(exp, "experiment_file_path", None))
            payload["progress_file_path"] = self._clean_path(getattr(exp, "progress_file_path", None))
            payload["calibration_file_path"] = self._clean_path(getattr(exp, "calibration_file_path", None))

        if isinstance(context, dict):
            payload.update(_normalize_json_value(context))
        elif context is not None:
            payload["value"] = _normalize_json_value(context)
        return payload

    @staticmethod
    def _clean_path(value) -> str:
        return "" if value is None else os.fspath(value)

    def _set_error(self, message: str) -> None:
        self._last_error = str(message)
        print(f"[ExperimentAudit] {self._last_error}")
