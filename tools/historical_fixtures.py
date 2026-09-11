"""Validate and stage the bounded, read-only historical replay dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/historical_replay_manifest.json"


def load_manifest(path=MANIFEST):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not payload.get("groups"):
        raise ValueError("Invalid historical fixture manifest")
    for entries in payload["groups"].values():
        if not entries:
            raise ValueError("Empty historical fixture group")
        for relative, digest in entries.items():
            p = PurePosixPath(relative)
            if (p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative
                    or p.as_posix() != relative or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)):
                raise ValueError(f"Invalid historical fixture entry: {relative}")
    return payload["groups"]


def external_root(path, *, repo=ROOT):
    requested = Path(path)
    if not requested.is_absolute():
        raise ValueError("Historical fixture root must be absolute")
    root = requested.resolve()
    inventory = subprocess.check_output(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain", "-z"]
    ).decode("utf-8")
    roots = [Path(field[9:]).resolve() for field in inventory.split("\0") if field.startswith("worktree ")]
    if not roots:
        raise ValueError("Cannot establish registered worktree boundaries")
    if any(root.is_relative_to(r) for r in roots):
        raise ValueError("Historical fixture root must be outside every registered worktree")
    return root


def verified_files(root, entries):
    root = Path(root).resolve()
    result = []
    for relative, digest in entries.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Historical fixture escapes root: {relative}")
        if not path.is_file():
            raise ValueError(f"Missing historical fixture: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Historical fixture hash mismatch: {relative}")
        result.append(path)
    return result


def stage(source, destination):
    source = Path(source).resolve(strict=True)
    destination = external_root(destination)
    if source == destination or destination.is_relative_to(source):
        raise ValueError("Staging destination must be separate from the source")
    entries = {p: h for group in load_manifest().values() for p, h in group.items()}
    verified_files(source, entries)
    destination.mkdir(parents=True, exist_ok=False)
    for relative in entries:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    verified_files(destination, entries)
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing archived Experiments directory")
    parser.add_argument("--destination", type=Path, required=True, help="New external dataset directory")
    args = parser.parse_args()
    print(f"Staged and verified {stage(args.source, args.destination)} files at {args.destination}")


if __name__ == "__main__":
    main()
