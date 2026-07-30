"""Launch the real LabCraft UI against the hardware-isolated simulator."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "FreeRTOS-interface"
for import_root in (REPO_ROOT, UI_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tools.sil.session import (  # noqa: E402
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real LabCraft application with SimulatedMachine only. "
            "No physical hardware connection is available."
        )
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="retain a newly allocated session root after a clean close",
    )
    parser.add_argument(
        "--session-root",
        type=Path,
        help=(
            "create or reopen this absolute retained session root; experiments "
            "remain available through the normal Experiment Editor"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="instance-local deterministic seed (default: 1)",
    )
    parser.add_argument(
        "--speed-multiplier",
        type=float,
        default=1.0,
        help="simulated-time acceleration multiplier (default: 1.0)",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> SimulationSessionConfigV1:
    if args.session_root is not None:
        return SimulationSessionConfigV1(
            root_policy=SessionRootPolicy.RETAINED,
            session_root=args.session_root,
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            seed=args.seed,
            speed_multiplier=args.speed_multiplier,
        )
    return SimulationSessionConfigV1(
        root_policy=SessionRootPolicy.FRESH,
        artifact_retention=(
            ArtifactRetentionPolicy.RETAIN
            if args.keep_session
            else ArtifactRetentionPolicy.DELETE_CLEAN_FRESH
        ),
        seed=args.seed,
        speed_multiplier=args.speed_multiplier,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    session = None
    event_result = 1
    try:
        config = config_from_args(args)
        session = SimulationSession.create(config)
        print(f"Simulation session root: {session.session_root}", flush=True)
        print(
            "Hardware access: BLOCKED; simulator port: SIMULATED",
            flush=True,
        )
        session.launch()
        event_result = session.run()
    except (ValueError, RuntimeError) as exc:
        root = getattr(exc, "session_root", None)
        print(f"Simulation launch failed: {exc}", file=sys.stderr, flush=True)
        if root is not None:
            print(f"Failed session retained at: {root}", file=sys.stderr, flush=True)
        if session is not None:
            session.mark_failed(str(exc))
    except KeyboardInterrupt:
        print("Simulation interrupted; session retained for diagnosis.", file=sys.stderr)
        if session is not None:
            session.mark_failed("interrupted by user")
    finally:
        if session is not None:
            closed_cleanly = session.close()
            if session.root_removed:
                print("Clean fresh simulation session removed.", flush=True)
            else:
                print(f"Simulation session retained at: {session.session_root}", flush=True)
            if not closed_cleanly:
                event_result = 1

    return 0 if event_result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

