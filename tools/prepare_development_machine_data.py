"""Create an isolated, byte-verified clone of a production machine-data store."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from MachineDataDevelopment import (  # noqa: E402
    DevelopmentStoreError,
    prepare_development_store,
)


def _commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a new isolated development machine-data root. The target "
            "must not already exist and is never overlaid."
        )
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = prepare_development_store(
            args.source_root,
            args.development_root,
            repo_root=REPO_ROOT,
            operator=args.operator,
            app_commit=_commit(),
        )
    except (DevelopmentStoreError, OSError, subprocess.SubprocessError) as exc:
        print(f"Development store was not created: {exc}", file=sys.stderr)
        return 2
    print(f"Development root: {store.root}")
    print(f"Source root:      {store.source_machine_data_root}")
    print(f"Store ID:         {store.store_id}")
    print(f"Source fingerprint: {store.source_tree_fingerprint}")
    print("PASS: the isolated copy is byte-identical and marked for development only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
