"""Launch App.py against a marked development store, never by implicit fallback."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from MachineData import MACHINE_DATA_ROOT_ENV  # noqa: E402
from MachineDataDevelopment import (  # noqa: E402
    DEVELOPMENT_HARDWARE_CONFIRMATION,
    DEVELOPMENT_HARDWARE_CONFIRMATION_ENV,
    DEVELOPMENT_HARDWARE_ENV,
    DEVELOPMENT_MODE,
    DEVELOPMENT_MODE_ENV,
    DEVELOPMENT_OPERATOR_ENV,
    DevelopmentStoreError,
    load_development_store,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the main UI against an isolated development machine-data "
            "store. Hardware is blocked unless explicitly attended."
        )
    )
    parser.add_argument("--machine-data-root", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--enable-hardware", action="store_true")
    parser.add_argument(
        "--hardware-confirmation",
        help="required exact confirmation when --enable-hardware is selected",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = load_development_store(args.machine_data_root)
    except DevelopmentStoreError as exc:
        print(f"Development launch rejected: {exc}", file=sys.stderr)
        return 2
    if args.enable_hardware and args.hardware_confirmation != DEVELOPMENT_HARDWARE_CONFIRMATION:
        print(
            "Development hardware launch rejected: supply the exact attended "
            f"confirmation: {DEVELOPMENT_HARDWARE_CONFIRMATION}",
            file=sys.stderr,
        )
        return 2

    environment = dict(os.environ)
    environment[MACHINE_DATA_ROOT_ENV] = str(store.root)
    environment[DEVELOPMENT_MODE_ENV] = DEVELOPMENT_MODE
    environment[DEVELOPMENT_OPERATOR_ENV] = str(args.operator).strip()
    environment[DEVELOPMENT_HARDWARE_ENV] = "1" if args.enable_hardware else "0"
    if args.enable_hardware:
        environment[DEVELOPMENT_HARDWARE_CONFIRMATION_ENV] = (
            DEVELOPMENT_HARDWARE_CONFIRMATION
        )
    else:
        environment.pop(DEVELOPMENT_HARDWARE_CONFIRMATION_ENV, None)

    mode = "ATTENDED HARDWARE" if args.enable_hardware else "NO HARDWARE"
    print(f"Development root: {store.root}", flush=True)
    print(f"Development mode: {mode}", flush=True)
    completed = subprocess.run(
        [sys.executable, "-u", str(UI_ROOT / "App.py")],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
