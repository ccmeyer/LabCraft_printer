from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_MACHINE_ID = "LC-UNASSIGNED"
DEFAULT_IDENTITY_PATH = Path("local") / "machine_identity.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".machine_identity_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _validate_identity(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"Machine identity at {path} must be a JSON object.")
    for key in ("machine_id", "machine_uuid", "assigned_at"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Machine identity at {path} is missing '{key}'.")
    payload.setdefault("notes", "")
    return dict(payload)


def load_or_create_identity(
    path: str | Path = DEFAULT_IDENTITY_PATH,
    *,
    machine_id: str | None = None,
    notes: str = "",
    now_fn: Callable[[], str] = now_iso,
    uuid_fn: Callable[[], Any] = uuid.uuid4,
) -> dict[str, Any]:
    identity_path = Path(path)
    if identity_path.exists():
        return _validate_identity(json.loads(identity_path.read_text(encoding="utf-8")), identity_path)

    generated_uuid = str(uuid_fn())
    payload = {
        "machine_id": str(machine_id or DEFAULT_MACHINE_ID).strip() or DEFAULT_MACHINE_ID,
        "machine_uuid": generated_uuid,
        "assigned_at": now_fn(),
        "notes": str(notes or ""),
    }
    _write_json_atomic(identity_path, payload)
    return dict(payload)
