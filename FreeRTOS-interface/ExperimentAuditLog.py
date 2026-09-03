from __future__ import annotations

import json
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CALIBRATION_VOLUME_WARNING_EVENT_TYPE = "calibration_volume_tolerance_exceeded"
CALIBRATION_VOLUME_WARNING_INTENT_SCHEMA_VERSION = 1
CALIBRATION_VOLUME_WARNING_EVENT_NAMESPACE = uuid.UUID(
    "cc915a86-041c-43c4-b6fd-ef313fbf3ea7"
)


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

def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_utc_timestamp(value: Any, path: str) -> str:
    text = str(value or "")
    if not text.endswith("Z"):
        raise ValueError(f"{path} must be an ISO-8601 UTC timestamp ending in Z.")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid ISO-8601 UTC timestamp.") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{path} must use UTC.")
    return text


def normalize_calibration_volume_warning_audit_intent(value: Any) -> dict:
    """Validate the durable, delivery-independent warning event payload."""
    if not isinstance(value, dict):
        raise ValueError("Calibration volume-warning audit intent must be an object.")
    expected = {
        "schema_version",
        "event_id",
        "timestamp_utc",
        "event_type",
        "level",
        "summary",
        "details",
    }
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise ValueError(
            "Calibration volume-warning audit intent is missing field(s): "
            + ", ".join(sorted(missing))
        )
    if unknown:
        raise ValueError(
            "Calibration volume-warning audit intent has unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    if value["schema_version"] != CALIBRATION_VOLUME_WARNING_INTENT_SCHEMA_VERSION:
        raise ValueError("Unsupported calibration volume-warning audit intent version.")
    event_id = str(value["event_id"] or "")
    try:
        parsed_event_id = uuid.UUID(event_id)
    except ValueError as exc:
        raise ValueError("Calibration volume-warning audit event_id must be a UUID.") from exc
    if str(parsed_event_id) != event_id:
        raise ValueError("Calibration volume-warning audit event_id must be canonical.")
    if value["event_type"] != CALIBRATION_VOLUME_WARNING_EVENT_TYPE:
        raise ValueError("Calibration volume-warning audit event_type is invalid.")
    if value["level"] != "warning":
        raise ValueError("Calibration volume-warning audit level must be warning.")
    summary = str(value["summary"] or "")
    if not summary:
        raise ValueError("Calibration volume-warning audit summary must not be empty.")
    if not isinstance(value["details"], dict):
        raise ValueError("Calibration volume-warning audit details must be an object.")
    details = _normalize_json_value(value["details"])
    warning = details.get("volume_warning") if isinstance(details, dict) else None
    if (
        not isinstance(warning, dict)
        or warning.get("code") != CALIBRATION_VOLUME_WARNING_EVENT_TYPE
    ):
        raise ValueError(
            "Calibration volume-warning audit details require matching warning evidence."
        )
    return {
        "schema_version": CALIBRATION_VOLUME_WARNING_INTENT_SCHEMA_VERSION,
        "event_id": event_id,
        "timestamp_utc": _require_utc_timestamp(
            value["timestamp_utc"],
            "Calibration volume-warning audit timestamp",
        ),
        "event_type": CALIBRATION_VOLUME_WARNING_EVENT_TYPE,
        "level": "warning",
        "summary": summary,
        "details": details,
    }


def build_calibration_volume_warning_audit_intent(
    *, identity: Any, timestamp_utc: str, details: dict
) -> dict:
    normalized_details = _normalize_json_value(details)
    seed = {
        "event_type": CALIBRATION_VOLUME_WARNING_EVENT_TYPE,
        "identity": _normalize_json_value(identity),
        "timestamp_utc": timestamp_utc,
        "details_sha256": hashlib.sha256(
            _canonical_json_bytes(normalized_details)
        ).hexdigest(),
    }
    event_id = str(
        uuid.uuid5(
            CALIBRATION_VOLUME_WARNING_EVENT_NAMESPACE,
            _canonical_json_bytes(seed).decode("utf-8"),
        )
    )
    return normalize_calibration_volume_warning_audit_intent(
        {
            "schema_version": CALIBRATION_VOLUME_WARNING_INTENT_SCHEMA_VERSION,
            "event_id": event_id,
            "timestamp_utc": timestamp_utc,
            "event_type": CALIBRATION_VOLUME_WARNING_EVENT_TYPE,
            "level": "warning",
            "summary": "Calibration applied with volume warning",
            "details": normalized_details,
        }
    )


def _audit_event_intent_projection(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Audit line must be a JSON object.")
    return normalize_calibration_volume_warning_audit_intent(
        {
            "schema_version": CALIBRATION_VOLUME_WARNING_INTENT_SCHEMA_VERSION,
            "event_id": value.get("event_id"),
            "timestamp_utc": value.get("timestamp_utc"),
            "event_type": value.get("event_type"),
            "level": value.get("level"),
            "summary": value.get("summary"),
            "details": value.get("details"),
        }
    )



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

    def ensure_event(self, intent: dict, *, context=None) -> dict:
        """Durably append one immutable warning event, or return its exact existing row."""
        normalized = normalize_calibration_volume_warning_audit_intent(intent)
        try:
            path_text = self.get_audit_path()
            if not path_text:
                raise OSError("No experiment audit path is available.")
            path = Path(path_text)
            path.parent.mkdir(parents=True, exist_ok=True)

            rows: list[dict] = []
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    for line_number, raw_line in enumerate(handle, start=1):
                        raw_text = raw_line.rstrip("\r\n")
                        if not raw_text.strip():
                            continue
                        try:
                            row = json.loads(raw_text)
                        except json.JSONDecodeError as exc:
                            raise ValueError(
                                f"Audit line {line_number} is malformed: {exc}"
                            ) from exc
                        if not isinstance(row, dict):
                            raise ValueError(
                                f"Audit line {line_number} is not a JSON object."
                            )
                        event_id = row.get("event_id")
                        if not isinstance(event_id, str) or not event_id:
                            raise ValueError(
                                f"Audit line {line_number} has no event_id."
                            )
                        rows.append(row)

            matches = [
                row
                for row in rows
                if row.get("event_id") == normalized["event_id"]
            ]
            if len(matches) > 1:
                raise ValueError(
                    f"Audit event_id {normalized['event_id']} appears more than once."
                )
            if matches:
                if _audit_event_intent_projection(matches[0]) != normalized:
                    raise ValueError(
                        f"Audit event_id {normalized['event_id']} conflicts with durable evidence."
                    )
                self._last_error = None
                return matches[0]

            occurred_at = datetime.fromisoformat(
                normalized["timestamp_utc"][:-1] + "+00:00"
            ).astimezone(timezone.utc)
            first_time = occurred_at
            if rows:
                try:
                    first_time = datetime.fromisoformat(
                        str(rows[0].get("timestamp_utc") or "").replace(
                            "Z", "+00:00"
                        )
                    ).astimezone(timezone.utc)
                except (TypeError, ValueError):
                    first_time = occurred_at
            event = {
                "schema_version": int(self.SCHEMA_VERSION),
                "event_id": normalized["event_id"],
                "timestamp_utc": normalized["timestamp_utc"],
                "elapsed_s": float(
                    max(0.0, (occurred_at - first_time).total_seconds())
                ),
                "event_type": normalized["event_type"],
                "level": normalized["level"],
                "summary": normalized["summary"],
                "details": normalized["details"],
                "context": self._build_context(context),
            }
            encoded = json.dumps(
                event,
                default=_json_default,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            self._set_error(f"Failed to ensure audit event: {exc}")
            raise

        if self._first_event_time is None:
            self._first_event_time = occurred_at
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
            payload["calibration_index_path"] = self._clean_path(
                getattr(exp, "calibration_index_file_path", None)
            )
            payload["calibration_recordings_root"] = self._clean_path(
                getattr(exp, "calibration_recordings_dir_path", None)
            )

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
