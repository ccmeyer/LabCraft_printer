import importlib
import sys
import types

import pytest


@pytest.mark.parametrize("module_name", ["Machine_FreeRTOS", "dfu_update"])
def test_gpiofind_prefers_cli_when_available(monkeypatch, module_name):
    mod = importlib.import_module(module_name)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gpiofind")
    monkeypatch.setattr(
        mod.subprocess,
        "check_output",
        lambda args, text=True: "/dev/gpiochip4 17",
    )

    assert mod._gpiofind("GPIO17") == ("/dev/gpiochip4", 17)


@pytest.mark.parametrize("module_name", ["Machine_FreeRTOS", "dfu_update"])
def test_gpiofind_falls_back_to_python_gpiod_scan(monkeypatch, module_name):
    mod = importlib.import_module(module_name)

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod.glob, "glob", lambda pattern: ["/dev/gpiochip0", "/dev/gpiochip4"])

    class FakeChip:
        def __init__(self, path):
            self.path = path

        def line_offset_from_id(self, line_name):
            if self.path.endswith("4") and line_name == "GPIO17":
                return 17
            raise OSError("line not on this chip")

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "gpiod", types.SimpleNamespace(Chip=FakeChip))

    assert mod._gpiofind("GPIO17") == ("/dev/gpiochip4", 17)


@pytest.mark.parametrize("module_name", ["Machine_FreeRTOS", "dfu_update"])
def test_gpiofind_raises_file_not_found_when_line_name_is_missing(monkeypatch, module_name):
    mod = importlib.import_module(module_name)

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod.glob, "glob", lambda pattern: ["/dev/gpiochip0"])

    class FakeChip:
        def __init__(self, path):
            self.path = path

        def line_offset_from_id(self, line_name):
            raise OSError("line not found")

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "gpiod", types.SimpleNamespace(Chip=FakeChip))

    with pytest.raises(FileNotFoundError, match="GPIO17"):
        mod._gpiofind("GPIO17")
