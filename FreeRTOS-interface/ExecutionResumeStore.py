from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ExecutionPlan import canonical_sha256


SCHEMA_NAME = "labcraft.execution_resume"
SCHEMA_VERSION = 1
INTENT_NAMESPACE = uuid.UUID("9cb85664-acde-4d4f-94bc-a06731340b11")
RESUME_STATES = {"clean", "printing", "paused", "uncertain"}
INTENT_STATES = {"pending", "completed"}


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _exact(payload: Mapping[str, Any], fields: set[str], path: str) -> None:
    missing = fields - set(payload)
    unknown = set(payload) - fields
    if missing:
        raise ValueError(f"{path}: missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path}: unknown field(s): {', '.join(sorted(unknown))}")


def _uuid(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{path}: must be a valid UUID") from exc
    if str(parsed) != value:
        raise ValueError(f"{path}: must use canonical UUID form")
    return value


def _text(value: Any, path: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{path}: must be a nonempty trimmed string")
    return value


def _timestamp(value: Any, path: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    value = _text(value, path)
    if not value.endswith("Z"):
        raise ValueError(f"{path}: must end in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{path}: invalid UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{path}: must use UTC")
    return value


def _count(value: Any, path: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
        or int(value) < 0
    ):
        raise ValueError(f"{path}: must be a nonnegative integer")
    return int(value)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def progress_fingerprint(progress_wells: Mapping[str, Any]) -> str:
    return canonical_sha256(progress_wells)


def deterministic_intent_id(
    session_id: str,
    *,
    plan_revision: int,
    well_id: str,
    reaction_id: str,
    stock_id: str,
    baseline_added: int,
    commanded_droplets: int,
) -> str:
    identity = {
        "plan_revision": plan_revision,
        "well_id": well_id,
        "reaction_id": reaction_id,
        "stock_id": stock_id,
        "baseline_added": baseline_added,
        "commanded_droplets": commanded_droplets,
    }
    return str(uuid.uuid5(INTENT_NAMESPACE, f"{session_id}:{canonical_sha256(identity)}"))


@dataclass(frozen=True)
class ExecutionPrintIntent:
    intent_id: str
    well_id: str
    reaction_id: str
    stock_id: str
    baseline_added: int
    commanded_droplets: int
    status: str
    command_seq32: int | None
    queued_at_utc: str
    completed_at_utc: str | None

    def __post_init__(self) -> None:
        _uuid(self.intent_id, "intent.intent_id")
        for name in ("well_id", "reaction_id", "stock_id"):
            _text(getattr(self, name), f"intent.{name}")
        object.__setattr__(self, "baseline_added", _count(self.baseline_added, "intent.baseline_added"))
        commanded = _count(self.commanded_droplets, "intent.commanded_droplets")
        if commanded < 1:
            raise ValueError("intent.commanded_droplets: must be positive")
        object.__setattr__(self, "commanded_droplets", commanded)
        if self.status not in INTENT_STATES:
            raise ValueError("intent.status: unsupported state")
        if self.command_seq32 is not None:
            object.__setattr__(self, "command_seq32", _count(self.command_seq32, "intent.command_seq32"))
        _timestamp(self.queued_at_utc, "intent.queued_at_utc")
        _timestamp(self.completed_at_utc, "intent.completed_at_utc", optional=True)
        if self.status == "pending" and self.completed_at_utc is not None:
            raise ValueError("Pending intents cannot have a completion timestamp.")
        if self.status == "completed" and self.completed_at_utc is None:
            raise ValueError("Completed intents require a completion timestamp.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "well_id": self.well_id,
            "reaction_id": self.reaction_id,
            "stock_id": self.stock_id,
            "baseline_added": self.baseline_added,
            "commanded_droplets": self.commanded_droplets,
            "status": self.status,
            "command_seq32": self.command_seq32,
            "queued_at_utc": self.queued_at_utc,
            "completed_at_utc": self.completed_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ExecutionPrintIntent":
        if not isinstance(payload, Mapping):
            raise ValueError("intent must be an object")
        fields = {
            "intent_id", "well_id", "reaction_id", "stock_id", "baseline_added",
            "commanded_droplets", "status", "command_seq32", "queued_at_utc",
            "completed_at_utc",
        }
        _exact(payload, fields, "intent")
        return cls(**dict(payload))


@dataclass(frozen=True)
class ExecutionResumeDocument:
    plan_id: str
    plan_revision: int
    session_id: str
    state: str
    active_stock_id: str | None
    printer_head_id: str | None
    progress_sha256: str
    intents: tuple[ExecutionPrintIntent, ...]
    created_at_utc: str
    updated_at_utc: str

    def __post_init__(self) -> None:
        _uuid(self.plan_id, "resume.plan_id")
        _uuid(self.session_id, "resume.session_id")
        revision = _count(self.plan_revision, "resume.plan_revision")
        if revision < 1:
            raise ValueError("resume.plan_revision must be positive")
        if self.state not in RESUME_STATES:
            raise ValueError("resume.state: unsupported state")
        _text(self.active_stock_id, "resume.active_stock_id", optional=True)
        _text(self.printer_head_id, "resume.printer_head_id", optional=True)
        if not isinstance(self.progress_sha256, str) or len(self.progress_sha256) != 64:
            raise ValueError("resume.progress_sha256: must be a SHA-256 digest")
        if any(ch not in "0123456789abcdef" for ch in self.progress_sha256):
            raise ValueError("resume.progress_sha256: must be lowercase hexadecimal")
        intents = tuple(self.intents)
        if any(not isinstance(intent, ExecutionPrintIntent) for intent in intents):
            raise ValueError("resume.intents must contain intent objects")
        ids = [intent.intent_id for intent in intents]
        if len(ids) != len(set(ids)):
            raise ValueError("resume.intents contains duplicate intent IDs")
        object.__setattr__(self, "intents", intents)
        _timestamp(self.created_at_utc, "resume.created_at_utc")
        _timestamp(self.updated_at_utc, "resume.updated_at_utc")
        created = datetime.fromisoformat(self.created_at_utc[:-1] + "+00:00")
        updated = datetime.fromisoformat(self.updated_at_utc[:-1] + "+00:00")
        if updated < created:
            raise ValueError("resume.updated_at_utc precedes creation")
        if self.state in {"clean", "paused"} and any(
            intent.status == "pending" for intent in intents
        ):
            raise ValueError("Clean or paused checkpoints cannot contain pending intents.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "plan_revision": self.plan_revision,
            "session_id": self.session_id,
            "state": self.state,
            "active_stock_id": self.active_stock_id,
            "printer_head_id": self.printer_head_id,
            "progress_sha256": self.progress_sha256,
            "intents": [intent.to_dict() for intent in self.intents],
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ExecutionResumeDocument":
        if not isinstance(payload, Mapping):
            raise ValueError("execution_resume.json must contain an object")
        fields = {
            "schema_name", "schema_version", "plan_id", "plan_revision", "session_id",
            "state", "active_stock_id", "printer_head_id", "progress_sha256", "intents",
            "created_at_utc", "updated_at_utc",
        }
        _exact(payload, fields, "execution_resume")
        if payload["schema_name"] != SCHEMA_NAME or payload["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported execution-resume schema name or version.")
        if not isinstance(payload["intents"], list):
            raise ValueError("execution_resume.intents must be an array")
        values = dict(payload)
        values.pop("schema_name")
        values.pop("schema_version")
        values["intents"] = tuple(ExecutionPrintIntent.from_dict(item) for item in payload["intents"])
        return cls(**values)


def new_resume_document(
    *,
    plan_id: str,
    plan_revision: int,
    progress_wells: Mapping[str, Any],
    session_id: str | None = None,
    timestamp_utc: str | None = None,
) -> ExecutionResumeDocument:
    timestamp = timestamp_utc or utc_now_text()
    return ExecutionResumeDocument(
        plan_id=plan_id,
        plan_revision=plan_revision,
        session_id=session_id or str(uuid.uuid4()),
        state="clean",
        active_stock_id=None,
        printer_head_id=None,
        progress_sha256=progress_fingerprint(progress_wells),
        intents=(),
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
    )


def add_pending_intent(
    document: ExecutionResumeDocument,
    *,
    well_id: str,
    reaction_id: str,
    stock_id: str,
    baseline_added: int,
    commanded_droplets: int,
    printer_head_id: str,
    timestamp_utc: str | None = None,
) -> tuple[ExecutionResumeDocument, ExecutionPrintIntent]:
    timestamp = timestamp_utc or utc_now_text()
    intent_id = deterministic_intent_id(
        document.session_id,
        plan_revision=document.plan_revision,
        well_id=well_id,
        reaction_id=reaction_id,
        stock_id=stock_id,
        baseline_added=baseline_added,
        commanded_droplets=commanded_droplets,
    )
    existing = next((item for item in document.intents if item.intent_id == intent_id), None)
    if existing is not None:
        return document, existing
    intent = ExecutionPrintIntent(
        intent_id=intent_id,
        well_id=well_id,
        reaction_id=reaction_id,
        stock_id=stock_id,
        baseline_added=baseline_added,
        commanded_droplets=commanded_droplets,
        status="pending",
        command_seq32=None,
        queued_at_utc=timestamp,
        completed_at_utc=None,
    )
    return replace(
        document,
        state="printing",
        active_stock_id=stock_id,
        printer_head_id=printer_head_id,
        intents=(*document.intents, intent),
        updated_at_utc=timestamp,
    ), intent


def attach_command_sequence(
    document: ExecutionResumeDocument,
    intent_id: str,
    command_seq32: int,
    *,
    timestamp_utc: str | None = None,
) -> ExecutionResumeDocument:
    found = False
    intents = []
    for intent in document.intents:
        if intent.intent_id == intent_id:
            found = True
            intents.append(replace(intent, command_seq32=_count(command_seq32, "command_seq32")))
        else:
            intents.append(intent)
    if not found:
        raise ValueError("Unknown execution print intent.")
    return replace(
        document,
        intents=tuple(intents),
        updated_at_utc=timestamp_utc or utc_now_text(),
    )


def complete_intent(
    document: ExecutionResumeDocument,
    intent_id: str,
    *,
    progress_wells: Mapping[str, Any],
    timestamp_utc: str | None = None,
) -> ExecutionResumeDocument:
    timestamp = timestamp_utc or utc_now_text()
    found = False
    intents = []
    for intent in document.intents:
        if intent.intent_id == intent_id:
            found = True
            try:
                added = _count(
                    progress_wells[intent.well_id]["reagents"][intent.stock_id].get(
                        "added_droplets", 0
                    ),
                    "progress.added_droplets",
                )
            except (AttributeError, KeyError, TypeError) as exc:
                raise ValueError(
                    "Progress does not contain the execution print intent."
                ) from exc
            if added < intent.baseline_added + intent.commanded_droplets:
                raise ValueError(
                    "Progress does not prove the execution print intent completed."
                )
            intents.append(
                intent
                if intent.status == "completed"
                else replace(intent, status="completed", completed_at_utc=timestamp)
            )
        else:
            intents.append(intent)
    if not found:
        raise ValueError("Unknown execution print intent.")
    pending = any(intent.status == "pending" for intent in intents)
    return replace(
        document,
        state="printing" if pending else "clean",
        active_stock_id=document.active_stock_id if pending else None,
        printer_head_id=document.printer_head_id if pending else None,
        progress_sha256=progress_fingerprint(progress_wells),
        intents=tuple(intents),
        updated_at_utc=timestamp,
    )


def synchronize_checkpoint(
    document: ExecutionResumeDocument,
    *,
    plan_revision: int,
    progress_wells: Mapping[str, Any],
    state: str = "clean",
    timestamp_utc: str | None = None,
) -> ExecutionResumeDocument:
    if any(intent.status == "pending" for intent in document.intents):
        raise ValueError("A checkpoint with pending intents cannot change plan revision.")
    if state not in {"clean", "paused"}:
        raise ValueError("A synchronized checkpoint must be clean or paused.")
    return replace(
        document,
        plan_revision=_count(plan_revision, "plan_revision"),
        state=state,
        active_stock_id=None,
        printer_head_id=None,
        progress_sha256=progress_fingerprint(progress_wells),
        updated_at_utc=timestamp_utc or utc_now_text(),
    )


def mark_checkpoint_uncertain(
    document: ExecutionResumeDocument,
    *,
    plan_revision: int,
    progress_wells: Mapping[str, Any],
    timestamp_utc: str | None = None,
) -> ExecutionResumeDocument:
    """Retain all intents while marking a hard-abort command boundary uncertain."""
    return replace(
        document,
        plan_revision=_count(plan_revision, "plan_revision"),
        state="uncertain",
        progress_sha256=progress_fingerprint(progress_wells),
        updated_at_utc=timestamp_utc or utc_now_text(),
    )


def load_execution_resume(path: str | Path) -> ExecutionResumeDocument:
    with Path(path).open("r", encoding="utf-8") as handle:
        return ExecutionResumeDocument.from_dict(
            json.load(handle, object_pairs_hook=_reject_duplicates)
        )


def save_execution_resume(path: str | Path, document: ExecutionResumeDocument) -> None:
    payload = document.to_dict()
    ExecutionResumeDocument.from_dict(payload)
    output = Path(path)
    if not output.parent.is_dir():
        raise OSError(f"Execution-resume parent directory does not exist: {output.parent}")
    fd, temporary = tempfile.mkstemp(prefix="._tmp_", suffix=".json", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
