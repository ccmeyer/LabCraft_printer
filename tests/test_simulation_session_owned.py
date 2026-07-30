import os
from pathlib import Path
import subprocess
import sys


def test_owned_qapplication_identity_event_loop_and_teardown(tmp_path):
    root = (tmp_path / "owned-session").resolve()
    script = f"""
from pathlib import Path
from PySide6 import QtCore
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)

session = SimulationSession.create(
    SimulationSessionConfigV1(
        visible=True,
        qt_ownership="owned",
        root_policy=SessionRootPolicy.RETAINED,
        session_root=Path({str(root)!r}),
        artifact_retention=ArtifactRetentionPolicy.RETAIN,
        speed_multiplier=1000.0,
        source_identity="pytest-owned",
    )
)
view = session.launch()
assert session.app.applicationName() == "LabCraft Simulator"
assert view.windowTitle().startswith("[SIMULATION - NO HARDWARE]")
QtCore.QTimer.singleShot(0, view.close)
event_result = session.run()
closed = session.close()
raise SystemExit(0 if event_result == 0 and closed else 1)
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )
    assert (root / "session.json").is_file()

