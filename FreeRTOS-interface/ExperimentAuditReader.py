from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_FILE_NAME = "experiment_audit.jsonl"
MALFORMED_EVENT_TYPE = "audit_parse_error"
MALFORMED_SUMMARY = "Malformed audit line"
RAW_LINE_PREVIEW_LIMIT = 500


@dataclass
class AuditTimelineRow:
    line_number: int
    event: dict
    is_valid: bool
    level: str
    event_type: str
    summary: str
    timestamp_utc: str
    elapsed_s: float | None
    time_display: str
    elapsed_display: str
    detail_json: str
    parse_error: str | None = None


def _truncate_text(value: str, limit: int = RAW_LINE_PREVIEW_LIMIT) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _json_pretty(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _coerce_float_or_none(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def format_audit_elapsed(elapsed_s) -> str:
    value = _coerce_float_or_none(elapsed_s)
    if value is None:
        return ""
    value = max(0.0, value)
    whole_seconds = int(value)
    milliseconds = int(round((value - whole_seconds) * 1000.0))
    if milliseconds >= 1000:
        whole_seconds += 1
        milliseconds -= 1000
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def format_audit_timestamp(timestamp_utc) -> str:
    text = str(timestamp_utc or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return text


def event_detail_json(event) -> str:
    if not isinstance(event, dict):
        return _json_pretty({})
    return _json_pretty(
        {
            "details": event.get("details") if isinstance(event.get("details"), dict) else {},
            "context": event.get("context") if isinstance(event.get("context"), dict) else {},
        }
    )


class ExperimentAuditReader:
    """Read-only parser for experiment audit JSONL timeline rows."""

    FILE_NAME = AUDIT_FILE_NAME

    def __init__(self, audit_path=None, model=None):
        self.audit_path = os.fspath(audit_path) if audit_path is not None else None
        self.model = model

    def get_audit_path(self) -> str | None:
        if self.audit_path:
            return os.path.abspath(os.fspath(self.audit_path))

        exp = getattr(self.model, "experiment_model", None)
        exp_dir = getattr(exp, "experiment_dir_path", None)
        if not exp_dir:
            return None
        return os.path.abspath(os.path.join(os.fspath(exp_dir), self.FILE_NAME))

    def read_rows(self) -> list[AuditTimelineRow]:
        path_text = self.get_audit_path()
        if not path_text:
            return []

        path = Path(path_text)
        if not path.exists():
            return []

        rows: list[AuditTimelineRow] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    raw_text = raw_line.rstrip("\r\n")
                    if not raw_text.strip():
                        continue
                    rows.append(self._parse_line(line_number, raw_text))
        except OSError as exc:
            return [self._build_warning_row(0, "", f"Could not read audit file: {exc}")]
        return rows

    def read_table(self) -> list[dict]:
        return [
            {
                "time": row.time_display,
                "elapsed": row.elapsed_display,
                "level": row.level,
                "event_type": row.event_type,
                "summary": row.summary,
                "line_number": row.line_number,
                "detail_json": row.detail_json,
                "is_valid": row.is_valid,
            }
            for row in self.read_rows()
        ]

    def _parse_line(self, line_number: int, raw_text: str) -> AuditTimelineRow:
        try:
            event = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return self._build_warning_row(line_number, raw_text, str(exc))

        if not isinstance(event, dict):
            return self._build_warning_row(line_number, raw_text, "Audit line is not a JSON object.")

        timestamp_utc = str(event.get("timestamp_utc") or "")
        elapsed_s = _coerce_float_or_none(event.get("elapsed_s"))
        return AuditTimelineRow(
            line_number=line_number,
            event=event,
            is_valid=True,
            level=str(event.get("level") or "info"),
            event_type=str(event.get("event_type") or ""),
            summary=str(event.get("summary") or ""),
            timestamp_utc=timestamp_utc,
            elapsed_s=elapsed_s,
            time_display=format_audit_timestamp(timestamp_utc),
            elapsed_display=format_audit_elapsed(elapsed_s),
            detail_json=event_detail_json(event),
            parse_error=None,
        )

    def _build_warning_row(self, line_number: int, raw_text: str, parse_error: str) -> AuditTimelineRow:
        raw_preview = _truncate_text(raw_text)
        detail = {
            "parse_error": str(parse_error or "Unknown parse error"),
            "raw_line": raw_preview,
        }
        event = {
            "level": "warning",
            "event_type": MALFORMED_EVENT_TYPE,
            "summary": MALFORMED_SUMMARY,
            "details": detail,
            "context": {},
        }
        return AuditTimelineRow(
            line_number=line_number,
            event=event,
            is_valid=False,
            level="warning",
            event_type=MALFORMED_EVENT_TYPE,
            summary=MALFORMED_SUMMARY,
            timestamp_utc="",
            elapsed_s=None,
            time_display="",
            elapsed_display="",
            detail_json=_json_pretty(detail),
            parse_error=str(parse_error or "Unknown parse error"),
        )
