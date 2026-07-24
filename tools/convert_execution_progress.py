from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(INTERFACE_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERFACE_ROOT))

from AuthoritativeExecutionLoad import inspect_authoritative_execution
from ExecutionProgressStore import (
    decode_execution_progress,
    detect_execution_progress_schema,
    encode_execution_progress_v1,
    serialize_execution_progress,
)
from ExecutionResumeStore import progress_fingerprint


class ProgressConversionError(RuntimeError):
    """Raised when offline progress conversion cannot be proven safe."""


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgressConversionError(f"Could not read {path.name}: {exc}") from exc


def _atomic_write_text(path: Path, text: str) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix="._tmp_",
        suffix=".json",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def convert_execution_progress_to_v1(experiment_dir: str | os.PathLike[str]) -> dict:
    directory = Path(experiment_dir).expanduser().resolve()
    design_path = directory / "experiment_design.json"
    progress_path = directory / "progress.json"
    design = _read_json(design_path)
    before = inspect_authoritative_execution(directory, design)
    if not before.valid or before.plan is None:
        messages = "; ".join(issue.message for issue in before.issues)
        raise ProgressConversionError(
            f"The authoritative execution bundle is invalid: {messages}"
        )
    raw_progress = _read_json(progress_path)
    if detect_execution_progress_schema(raw_progress) != 2:
        raise ProgressConversionError("progress.json is not schema v2.")
    decoded = decode_execution_progress(before.plan, raw_progress)
    before_fingerprint = progress_fingerprint(decoded.progress_wells)
    v1_payload = encode_execution_progress_v1(
        before.plan,
        decoded.progress_wells,
    )
    candidate = decode_execution_progress(before.plan, v1_payload)
    if progress_fingerprint(candidate.progress_wells) != before_fingerprint:
        raise ProgressConversionError(
            "Generated schema-v1 progress changes the resume progress fingerprint."
        )
    serialized = serialize_execution_progress(v1_payload)
    try:
        _atomic_write_text(progress_path, serialized)
    except OSError as exc:
        raise ProgressConversionError(
            f"Could not atomically replace progress.json: {exc}"
        ) from exc

    after = inspect_authoritative_execution(directory, design)
    if not after.valid or after.plan is None:
        messages = "; ".join(issue.message for issue in after.issues)
        raise ProgressConversionError(
            "Converted progress failed authoritative validation: " + messages
        )
    after_fingerprint = progress_fingerprint(after.progress_wells)
    if after_fingerprint != before_fingerprint:
        raise ProgressConversionError(
            "Converted progress changed the resume progress fingerprint."
        )
    return {
        "experiment_dir": os.fspath(directory),
        "progress_path": os.fspath(progress_path),
        "from_schema_version": 2,
        "to_schema_version": 1,
        "encoded_size_bytes": len(serialized.encode("utf-8")),
        "progress_sha256": after_fingerprint,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a validated authoritative progress snapshot offline."
    )
    parser.add_argument("--experiment-dir", required=True)
    parser.add_argument(
        "--to-v1",
        action="store_true",
        help="Convert schema-v2 progress.json to the rollback-compatible v1 form.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.to_v1:
        print("error: --to-v1 is required", file=sys.stderr)
        return 3
    try:
        result = convert_execution_progress_to_v1(args.experiment_dir)
    except ProgressConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
