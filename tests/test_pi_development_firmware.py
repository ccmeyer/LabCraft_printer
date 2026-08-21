from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
TOOL_PATH = TOOLS_ROOT / "pi_development_firmware.py"
WRAPPER_PATH = TOOLS_ROOT / "run_pi_development_firmware.ps1"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
SPEC = importlib.util.spec_from_file_location("pi_development_firmware", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
firmware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firmware)


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_current_artifact_is_bound_to_head_and_released_tag() -> None:
    provenance = firmware.collect_local_artifact_provenance(
        REPO_ROOT, head=_head(), released_tag="v1.3.0-rc.5"
    )
    assert provenance["development"]["tracked_at_head"] is True
    assert provenance["released"]["artifact_relative_path"] == firmware.ARTIFACT_RELATIVE_PATH
    assert len(provenance["development"]["sha256"]) == 64
    assert len(provenance["released"]["sha256"]) == 64


def test_released_tag_manifest_must_bind_firmware(monkeypatch: pytest.MonkeyPatch) -> None:
    original = firmware._git_bytes

    def fake_git_bytes(repo: Path, revision_path: str) -> bytes:
        if revision_path.endswith(":releases/v1.3.0-rc.5.json"):
            return json.dumps(
                {
                    "schema_version": "labcraft_release_v1",
                    "version": "v1.3.0-rc.5",
                    "tag": "v1.3.0-rc.5",
                    "requires_firmware": None,
                }
            ).encode()
        return original(repo, revision_path)

    monkeypatch.setattr(firmware, "_git_bytes", fake_git_bytes)
    with pytest.raises(firmware.FirmwareWorkflowError, match="does not bind"):
        firmware.collect_local_artifact_provenance(
            REPO_ROOT, head=_head(), released_tag="v1.3.0-rc.5"
        )


def test_remote_supervisor_is_valid_python_and_has_mandatory_restore() -> None:
    compile(firmware.REMOTE_FIRMWARE_ROUNDTRIP, "<remote-firmware>", "exec")
    source = firmware.REMOTE_FIRMWARE_ROUNDTRIP
    assert '"--profile", "SAFE"' in source
    assert '"--mode", "full"' in source
    assert 'role="released-restore"' in source
    assert "finally:" in source
    assert "final_firmware_role" in source
    assert "development-safe" not in source


@pytest.mark.parametrize(
    "unsafe_root",
    [
        "/home/labcraft/LabCraft_printer/reports",
        "/home/labcraft/LabCraft_printer-dev/reports",
        "/home/labcraft",
    ],
)
def test_remote_evidence_root_must_be_external(unsafe_root: str) -> None:
    with pytest.raises(firmware.FirmwareWorkflowError, match="external"):
        firmware.validate_remote_session_root(
            unsafe_root,
            pi_user="labcraft",
            production_repo="/home/labcraft/LabCraft_printer",
            development_repo="/home/labcraft/LabCraft_printer-dev",
        )


def test_remote_evidence_root_accepts_declared_external_path() -> None:
    firmware.validate_remote_session_root(
        firmware.DEFAULT_REMOTE_ROOT,
        pi_user="labcraft",
        production_repo="/home/labcraft/LabCraft_printer",
        development_repo="/home/labcraft/LabCraft_printer-dev",
    )


def test_cli_dry_run_is_safe_and_nonmutating(capsys: pytest.CaptureFixture[str]) -> None:
    code = firmware.main(
        [
            "--pi-host", "192.0.2.10",
            "--operator", "Test Operator",
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "HIL profile: SAFE" in output
    assert "Mandatory final stage: released restore plus SAFE" in output
    assert "No SSH call, flash, or evidence write" in output


def test_powershell_wrapper_dry_run() -> None:
    completed = subprocess.run(
        [
            "powershell", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER_PATH),
            "-PiHost", "192.0.2.10", "-Operator", "Test Operator", "-DryRun",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "HIL profile: SAFE" in completed.stdout


def test_legacy_general_hil_wrapper_defaults_to_safe() -> None:
    source = (REPO_ROOT / "firmware/scripts/run_fw_hil_windows.ps1").read_text(
        encoding="utf-8"
    )
    assert '[string]$Profile = "SAFE"' in source
    assert '[string]$Profile = "FULL"' not in source
