"""Exercise headless build metadata preservation without the real toolchain."""
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mode", ["cache", "semantic", "failure"])
def test_headless_build_preserves_only_cache_changes(tmp_path, mode):
    project = tmp_path / "project with spaces"
    settings = project / ".settings/language.settings.xml"
    settings.parent.mkdir(parents=True)
    before = b'<project env-hash="old"><language id="original"/></project>\n'
    settings.write_bytes(before)
    artifact = project / "artifacts/LabCraft_firmware.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"previous artifact")
    cube = tmp_path / "fake cube"
    cube.mkdir()
    helper = cube / "build.py"
    helper.write_text(
        "import pathlib,sys\n"
        "p=pathlib.Path(sys.argv[sys.argv.index('-import')+1])\n"
        "s=p/'.settings/language.settings.xml'\n"
        "text=s.read_text().replace('old','generated').rstrip()\n"
        + ("text=text.replace('original','edited')\n" if mode == "semantic" else "")
        + "s.write_text(text)\n"
        + ("raise SystemExit(17)\n" if mode == "failure" else
           "(p/'Debug').mkdir()\n(p/'Debug/LabCraft_firmware.bin').write_bytes(b'new artifact')\n")
    )
    (cube / "headless-build.bat").write_text(f'@echo off\n"{sys.executable}" "{helper}" %*\nexit /b %errorlevel%\n')
    script = Path(__file__).resolve().parents[1] / "firmware/scripts/build_firmware_headless.ps1"
    result = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script),
                             "-CubeIde", str(cube), "-ProjectDir", str(project)],
                            capture_output=True, text=True, timeout=60)
    if mode == "failure":
        assert result.returncode != 0
        assert artifact.read_bytes() == b"previous artifact"
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert artifact.read_bytes() == b"new artifact"
    if mode == "semantic":
        assert 'id="edited"' in settings.read_text()
    else:
        assert settings.read_bytes() == before
