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
TOOLTIP_LINE_LIMIT = 10


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
    stock_solution: str = ""
    tooltip_text: str = ""
    parse_error: str | None = None


def _truncate_text(value: str, limit: int = RAW_LINE_PREVIEW_LIMIT) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _json_pretty(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _markdown_cell(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "<br>")


def _format_markdown_generated_at(generated_at: Any) -> str:
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    if isinstance(generated_at, datetime):
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        generated_at = generated_at.astimezone(timezone.utc)
        return generated_at.isoformat().replace("+00:00", "Z")
    return str(generated_at)


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


def _event_sections(event) -> tuple[dict, dict]:
    if not isinstance(event, dict):
        return {}, {}
    details = event.get("details")
    context = event.get("context")
    return (
        details if isinstance(details, dict) else {},
        context if isinstance(context, dict) else {},
    )


def _clean_display_value(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null"} else text


def _nested_dict_value(payload: dict, *keys):
    cur = payload
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_display_value(*values) -> str:
    for value in values:
        text = _clean_display_value(value)
        if text:
            return text
    return ""


def _stock_identity_display(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    explicit = _first_display_value(
        payload.get("stock_solution"),
        payload.get("display_stock_name"),
        payload.get("stock_display_name"),
    )
    if explicit:
        return explicit

    reagent_name = _first_display_value(payload.get("reagent_name"), payload.get("reagent"))
    concentration = _first_display_value(
        payload.get("display_concentration"),
        payload.get("concentration"),
        payload.get("stock_concentration"),
    )
    units = _first_display_value(payload.get("units"), payload.get("stock_units"))
    if reagent_name and concentration and units and units != "--":
        return f"{reagent_name} - {concentration} {units}"
    if reagent_name:
        return reagent_name
    return _first_display_value(payload.get("stock_id"))


def derive_audit_stock_solution(event) -> str:
    details, context = _event_sections(event)
    stock_identity = details.get("stock_identity")
    if not isinstance(stock_identity, dict):
        stock_identity = {}
    loaded_head = details.get("loaded_printer_head")
    if not isinstance(loaded_head, dict):
        loaded_head = {}
    printer_head = details.get("printer_head")
    if not isinstance(printer_head, dict):
        printer_head = {}

    return _first_display_value(
        _stock_identity_display(stock_identity),
        _stock_identity_display(details),
        details.get("stock_solution"),
        loaded_head.get("stock_solution"),
        loaded_head.get("stock_id"),
        details.get("stock_id"),
        printer_head.get("stock_solution"),
        printer_head.get("stock_id"),
        context.get("stock_solution"),
        context.get("stock_id"),
    )


def _format_tooltip_value(label: str, value) -> str | None:
    text = _clean_display_value(value)
    if not text:
        return None
    return f"{label}: {text}"


def _compact_tooltip_lines(event, *, stock_solution="") -> list[str]:
    details, _context = _event_sections(event)
    lines = []

    for label, value in (
        ("Event", event.get("event_type") if isinstance(event, dict) else ""),
        ("Level", event.get("level") if isinstance(event, dict) else ""),
        ("Stock", stock_solution),
    ):
        line = _format_tooltip_value(label, value)
        if line:
            lines.append(line)

    event_type = str(event.get("event_type") or "") if isinstance(event, dict) else ""
    if event_type.startswith("calibration_"):
        result_summary = details.get("result_summary")
        if not isinstance(result_summary, dict):
            result_summary = {}
        compact = result_summary.get("latest_compact")
        if not isinstance(compact, dict):
            compact = {}
        settings = details.get("settings")
        if not isinstance(settings, dict):
            settings = {}

        candidates = [
            ("Process", details.get("process_name")),
            ("Phase", details.get("calibration_phase")),
            ("Outcome", details.get("outcome")),
            (
                "Ejection volume nL",
                _first_display_value(
                    result_summary.get("volume_nL"),
                    compact.get("mean_nL"),
                    compact.get("measured_volume_nL"),
                    compact.get("ejection_volume_nL"),
                    compact.get("volume_nL"),
                    compact.get("droplet_volume_nL"),
                ),
            ),
            (
                "CV %",
                _first_display_value(
                    result_summary.get("cv_pct"),
                    compact.get("cv_pct"),
                    compact.get("cv_percent"),
                    compact.get("coefficient_variation_pct"),
                ),
            ),
            (
                "Print pressure psi",
                _first_display_value(
                    result_summary.get("print_pressure_psi"),
                    compact.get("pressure_psi"),
                    compact.get("print_pressure_psi"),
                    settings.get("print_pressure"),
                ),
            ),
            (
                "Pulse width us",
                _first_display_value(
                    result_summary.get("pulse_width_us"),
                    compact.get("pw_us"),
                    compact.get("print_pulse_width_us"),
                    settings.get("print_width"),
                ),
            ),
            (
                "Samples",
                _first_display_value(
                    result_summary.get("replicate_count"),
                    compact.get("sample_count"),
                    compact.get("replicate_count"),
                    compact.get("droplet_volumes_count"),
                    result_summary.get("flat_measurement_count"),
                    result_summary.get("step_count"),
                ),
            ),
        ]
    else:
        settings = details.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        candidates = [
            ("Scope", details.get("reset_scope")),
            ("Array state", details.get("array_state")),
            ("Stock id", details.get("stock_id")),
            ("Remaining wells", details.get("remaining_well_count")),
            ("Queued wells", details.get("queued_well_count")),
            ("Planned wells", details.get("planned_well_count")),
            ("Affected wells", details.get("affected_well_count")),
            ("Outcome", details.get("outcome")),
            ("Print pressure psi", settings.get("print_pressure_psi")),
            ("Pulse width us", settings.get("print_pulse_width_us")),
        ]

    for label, value in candidates:
        line = _format_tooltip_value(label, value)
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= TOOLTIP_LINE_LIMIT:
            break

    summary = event.get("summary") if isinstance(event, dict) else ""
    line = _format_tooltip_value("Summary", summary)
    if line and line not in lines and len(lines) < TOOLTIP_LINE_LIMIT:
        lines.append(line)
    return lines[:TOOLTIP_LINE_LIMIT]


def build_audit_tooltip(event, *, stock_solution="") -> str:
    return "\n".join(_compact_tooltip_lines(event, stock_solution=stock_solution))


def build_audit_markdown(
    rows,
    audit_path=None,
    generated_at=None,
    title="Experiment Audit Timeline",
) -> str:
    row_list = list(rows or [])
    generated_text = _format_markdown_generated_at(generated_at)
    lines = [
        f"# {str(title or 'Experiment Audit Timeline')}",
        "",
        f"- Generated: {generated_text}",
    ]
    if audit_path:
        lines.append(f"- Audit file: `{os.fspath(audit_path)}`")
    lines.extend(
        [
            f"- Events: {len(row_list)}",
            "",
            "## Summary",
            "",
            "| Line | Time | Elapsed | Level | Stock Solution | Event Type | Summary |",
            "| ---: | --- | ---: | --- | --- | --- | --- |",
        ]
    )

    for row in row_list:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(getattr(row, "line_number", "")),
                    _markdown_cell(getattr(row, "time_display", "")),
                    _markdown_cell(getattr(row, "elapsed_display", "")),
                    _markdown_cell(getattr(row, "level", "")),
                    _markdown_cell(getattr(row, "stock_solution", "")),
                    _markdown_cell(getattr(row, "event_type", "")),
                    _markdown_cell(getattr(row, "summary", "")),
                ]
            )
            + " |"
        )

    if not row_list:
        lines.append("|  |  |  |  |  |  | No audit events found |")

    lines.extend(["", "## Details", ""])
    if not row_list:
        lines.append("No audit events found.")
    for row in row_list:
        line_number = getattr(row, "line_number", "")
        event_type = getattr(row, "event_type", "") or "audit_event"
        summary = getattr(row, "summary", "")
        lines.extend(
            [
                f"### Line {line_number}: {event_type}",
                "",
                f"- Level: {getattr(row, 'level', '')}",
                f"- Time: {getattr(row, 'time_display', '')}",
                f"- Elapsed: {getattr(row, 'elapsed_display', '')}",
                f"- Summary: {summary}",
                "",
                "```json",
                str(getattr(row, "detail_json", "") or "{}"),
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


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
                "stock_solution": row.stock_solution,
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
        stock_solution = derive_audit_stock_solution(event)
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
            stock_solution=stock_solution,
            tooltip_text=build_audit_tooltip(event, stock_solution=stock_solution),
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
            stock_solution="",
            tooltip_text=build_audit_tooltip(event, stock_solution=""),
            parse_error=str(parse_error or "Unknown parse error"),
        )
