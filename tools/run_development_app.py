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


DEVELOPMENT_AUTOCLOSE_MS_ENV = "LABCRAFT_DEVELOPMENT_AUTOCLOSE_MS"
QT_ENV_VARS_TO_REMOVE = (
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QT_QPA_FONTDIR",
    "QT_PLUGIN_PATH",
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
    parser.add_argument(
        "--auto-close-seconds",
        type=float,
        help=(
            "development-only qualification timer; supported only while hardware "
            "is disabled (0.5 to 600 seconds)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = load_development_store(args.machine_data_root)
    except DevelopmentStoreError as exc:
        print(f"Development launch rejected: {exc}", file=sys.stderr)
        return 2
    operator = str(args.operator or "").strip()
    if not operator:
        print("Development launch rejected: operator is required.", file=sys.stderr)
        return 2
    if args.enable_hardware and args.hardware_confirmation != DEVELOPMENT_HARDWARE_CONFIRMATION:
        print(
            "Development hardware launch rejected: supply the exact attended "
            f"confirmation: {DEVELOPMENT_HARDWARE_CONFIRMATION}",
            file=sys.stderr,
        )
        return 2
    if args.auto_close_seconds is not None and (
        args.enable_hardware
        or not 0.5 <= args.auto_close_seconds <= 600.0
    ):
        print(
            "Development launch rejected: auto-close requires no-hardware mode "
            "and a value from 0.5 to 600 seconds.",
            file=sys.stderr,
        )
        return 2

    environment = dict(os.environ)
    environment[MACHINE_DATA_ROOT_ENV] = str(store.root)
    environment[DEVELOPMENT_MODE_ENV] = DEVELOPMENT_MODE
    environment[DEVELOPMENT_OPERATOR_ENV] = operator
    environment[DEVELOPMENT_HARDWARE_ENV] = "1" if args.enable_hardware else "0"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    for name in QT_ENV_VARS_TO_REMOVE:
        environment.pop(name, None)
    xdg_root = store.root / "development_runtime" / "xdg"
    xdg_paths = {
        "XDG_DATA_HOME": xdg_root / "data",
        "XDG_CONFIG_HOME": xdg_root / "config",
        "XDG_CACHE_HOME": xdg_root / "cache",
    }
    for name, path in xdg_paths.items():
        path.mkdir(parents=True, exist_ok=True)
        if store.root not in path.resolve().parents:
            print(
                f"Development launch rejected: {name} escaped the development store.",
                file=sys.stderr,
            )
            return 2
        environment[name] = str(path)
    if args.enable_hardware:
        environment[DEVELOPMENT_HARDWARE_CONFIRMATION_ENV] = (
            DEVELOPMENT_HARDWARE_CONFIRMATION
        )
    else:
        environment.pop(DEVELOPMENT_HARDWARE_CONFIRMATION_ENV, None)
    if args.auto_close_seconds is None:
        environment.pop(DEVELOPMENT_AUTOCLOSE_MS_ENV, None)
    else:
        environment[DEVELOPMENT_AUTOCLOSE_MS_ENV] = str(
            int(round(args.auto_close_seconds * 1000))
        )

    mode = "ATTENDED HARDWARE" if args.enable_hardware else "NO HARDWARE"
    print(f"Development root: {store.root}", flush=True)
    print(f"Development mode: {mode}", flush=True)
    process = subprocess.Popen(
        [sys.executable, "-u", str(UI_ROOT / "App.py")],
        cwd=REPO_ROOT,
        env=environment,
    )
    print(f"Development app PID: {process.pid}", flush=True)
    return int(process.wait())


if __name__ == "__main__":
    raise SystemExit(main())
