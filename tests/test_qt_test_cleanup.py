"""Test Qt lifecycle isolation in a child so GC policy cannot leak to this suite."""
import os
from pathlib import Path
import subprocess
import sys


def test_qt_cycles_are_collected_on_gui_thread_between_tests(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "conftest.py").write_text('pytest_plugins = ["tests.conftest"]\n')
    probe = tmp_path / "test_probe.py"
    probe.write_text('''
import gc
import weakref
from PySide6.QtCore import QObject, QThread
events = []
reference = None

def test_first(qapp):
    global reference
    gc.disable()
    owner = QObject()
    owner.cycle = owner
    reference = weakref.ref(owner)
    weakref.finalize(owner, lambda: events.append(QThread.currentThread() == qapp.thread()))

def test_second(qapp):
    assert reference() is None, "Previous test retained a Qt reference cycle"
    assert events == [True], "Qt cycle was not destroyed on the GUI thread"
    gc.enable()
''')
    env = dict(os.environ, PYTHONPATH=str(root), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "pytestqt.plugin",
                             "--basetemp", str(tmp_path / "child-data"), str(probe)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
