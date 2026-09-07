"""Opt-in bounded Qt optimizer memory-stability test (Windows/Pi, no hardware)."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fixture-root", required=True)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--settle-seconds", type=float, default=2.)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 20 or not 1 <= args.warmups <= 5:
        parser.error("Use 1-20 measured rounds and 1-5 warm-up rounds")
    if not 60 <= args.max_seconds <= 1800 or not 0 <= args.settle_seconds <= 10:
        parser.error("Campaign limit is 60-1800 seconds; settling is 0-10 seconds")
    from tests.optimizer_qualification_cases import require_external
    if not Path(args.output).is_absolute() or not Path(args.fixture_root).is_absolute():
        parser.error("Output and fixture root must be absolute external paths")
    args.output = str(require_external(args.output))
    args.fixture_root = str(require_external(args.fixture_root))
    from tools.optimizer_memory_qualification import supervise, run_session
    if not args.worker:
        return supervise(args, [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:], "--worker"])
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tests.conftest  # Explicit simulated dependencies and Qt font setup.
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = run_session(app, args)
    return 0 if result["status"] == "passed" else 2 if result["status"] == "inconclusive" else 1


if __name__ == "__main__":
    raise SystemExit(main())
