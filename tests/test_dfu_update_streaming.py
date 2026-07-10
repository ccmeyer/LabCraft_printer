import importlib
import subprocess

import pytest


def _dfu_update_with_available_util(monkeypatch, util_path="dfu-util"):
    mod = importlib.import_module("dfu_update")
    monkeypatch.setattr(mod, "DFU_UTIL", util_path)
    monkeypatch.setattr(
        mod.shutil,
        "which",
        lambda name: util_path if name == "dfu-util" else None,
    )
    return mod


def test_flash_with_dfu_inherits_output_streams(monkeypatch, tmp_path):
    mod = _dfu_update_with_available_util(monkeypatch)
    bin_path = tmp_path / "LabCraft_firmware.bin"
    bin_path.write_bytes(b"fake firmware")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod._flash_with_dfu(
        bin_path,
        flash_addr="0x08004000",
        cwd=tmp_path,
        leave=True,
        dfu_vidpid="1234:abcd",
        usb_path="1-2",
        alt=2,
    )

    assert calls == [
        (
            [
                "dfu-util",
                "-d",
                "1234:abcd",
                "--path",
                "1-2",
                "-a",
                "2",
                "-s",
                "0x08004000:leave",
                "-D",
                str(bin_path),
            ],
            {"cwd": str(tmp_path)},
        )
    ]
    _, kwargs = calls[0]
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs


def test_flash_with_dfu_can_flash_without_leave_suffix(monkeypatch, tmp_path):
    mod = _dfu_update_with_available_util(monkeypatch)
    bin_path = tmp_path / "LabCraft_firmware.bin"
    bin_path.write_bytes(b"fake firmware")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod._flash_with_dfu(bin_path, flash_addr="0x08000000", leave=False)

    cmd, kwargs = calls[0]
    assert "0x08000000" in cmd
    assert "0x08000000:leave" not in cmd
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs


def test_flash_with_dfu_preserves_nonzero_return_error(monkeypatch, tmp_path):
    mod = _dfu_update_with_available_util(monkeypatch)
    bin_path = tmp_path / "LabCraft_firmware.bin"
    bin_path.write_bytes(b"fake firmware")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 7)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"dfu-util failed \(rc=7\)"):
        mod._flash_with_dfu(bin_path)

    _, kwargs = calls[0]
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
