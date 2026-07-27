import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.qt_font_environment import (
    FONT_RENDER_SAMPLE,
    SilQtFontEnvironmentError,
    WINDOWS_APPLICATION_FONT_FAMILY,
    WINDOWS_APPLICATION_FONT_POINT_SIZE,
    apply_and_validate_sil_application_font,
    configure_sil_qt_font_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_windows_fonts(tmp_path: Path) -> tuple[Path, Path]:
    windows_root = tmp_path / "Windows"
    fonts_dir = windows_root / "Fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "segoeui.ttf").write_bytes(b"synthetic-font-marker")
    return windows_root, fonts_dir


def test_windows_offscreen_bootstrap_selects_system_font_directory(tmp_path):
    windows_root, fonts_dir = _fake_windows_fonts(tmp_path)
    environment = {
        "QT_QPA_PLATFORM": "offscreen",
        "WINDIR": str(windows_root),
    }

    evidence = configure_sil_qt_font_environment(
        system_name="Windows",
        environ=environment,
    )

    assert environment["QT_QPA_FONTDIR"] == str(fonts_dir.resolve())
    assert evidence == {
        "directory_source": "windows_system",
        "configured_directory": str(fonts_dir.resolve()),
        "qt_platform": "offscreen",
    }


def test_explicit_font_directory_is_preserved(tmp_path):
    font_dir = tmp_path / "caller-fonts"
    font_dir.mkdir()
    (font_dir / "custom.ttf").write_bytes(b"synthetic-font-marker")
    environment = {
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QPA_FONTDIR": str(font_dir),
    }

    evidence = configure_sil_qt_font_environment(
        system_name="Windows",
        environ=environment,
        windows_directory=tmp_path / "unused",
    )

    assert environment["QT_QPA_FONTDIR"] == str(font_dir)
    assert evidence["directory_source"] == "caller"
    assert evidence["configured_directory"] == str(font_dir.resolve())


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_invalid_explicit_font_directory_fails_closed(tmp_path, kind):
    font_dir = tmp_path / "fonts"
    if kind == "empty":
        font_dir.mkdir()
    environment = {
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QPA_FONTDIR": str(font_dir),
    }

    with pytest.raises(SilQtFontEnvironmentError) as caught:
        configure_sil_qt_font_environment(
            system_name="Windows",
            environ=environment,
        )

    assert caught.value.evidence["status"] == "fail"
    assert caught.value.evidence["failure_reason"] == (
        "font_directory_missing" if kind == "missing" else "font_directory_empty"
    )


def test_non_windows_and_native_paths_are_not_reconfigured(tmp_path):
    environment = {"QT_QPA_PLATFORM": "offscreen"}
    assert configure_sil_qt_font_environment(
        system_name="Linux",
        environ=environment,
    ) == {
        "directory_source": "native",
        "configured_directory": None,
        "qt_platform": "offscreen",
    }
    assert "QT_QPA_FONTDIR" not in environment

    windows_root, _ = _fake_windows_fonts(tmp_path)
    environment = {
        "QT_QPA_PLATFORM": "windows",
        "WINDIR": str(windows_root),
    }
    assert configure_sil_qt_font_environment(
        system_name="Windows",
        environ=environment,
    )["directory_source"] == "native"
    assert "QT_QPA_FONTDIR" not in environment


def test_application_font_validation_requires_an_application():
    with pytest.raises(SilQtFontEnvironmentError) as caught:
        apply_and_validate_sil_application_font(None)

    assert caught.value.evidence["failure_reason"] == "application_missing"


def test_unusable_font_cannot_satisfy_editor_ui_gate(
    qapp,
    tmp_path,
    monkeypatch,
):
    import tools.virtual_workflows.editor_scenarios as editor_scenarios
    from tools.virtual_workflows.editor_scenarios import (
        EditorLifecycleScenarioConfig,
        run_editor_create_finalize_scenario,
    )

    failure_evidence = {
        "status": "fail",
        "available_family_count": 0,
        "raw_font_valid": False,
        "sample_glyphs_renderable": False,
        "failure_reason": "no_font_families",
    }

    def reject_font(_app):
        raise SilQtFontEnvironmentError(
            "synthetic unreadable font environment",
            evidence=failure_evidence,
        )

    monkeypatch.setattr(
        editor_scenarios,
        "apply_and_validate_sil_application_font",
        reject_font,
    )
    report = run_editor_create_finalize_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            timeout_seconds=60,
            run_id="font-gate-failure",
        )
    )

    assert report["classification"]["status"] == "fail"
    assert report["environment"]["qt"]["font"] == failure_evidence
    workflow = report["metrics"]["workflow"]["values"]
    launch = next(
        item
        for item in workflow["action_results"]
        if item["action_id"] == "app.launch_simulated"
    )
    assert launch["status"] == "fail"
    assert launch["failure_stage"] == "precondition"
    assert launch["evidence"]["font_rendering"] == failure_evidence
    ui_assertion = next(
        item
        for item in workflow["assertion_results"]
        if item["assertion_id"] == "ui.real_app_constructed"
    )
    assert ui_assertion == {
        "assertion_id": "ui.real_app_constructed",
        "decision": "fail",
        "evidence": {"font_rendering": failure_evidence},
    }


def test_session_qapp_uses_readable_native_windows_font(qapp):
    evidence = apply_and_validate_sil_application_font(qapp)

    assert evidence["status"] == "pass"
    assert evidence["raw_font_valid"] is True
    assert evidence["sample"] == FONT_RENDER_SAMPLE
    assert evidence["sample_glyphs_renderable"] is True
    assert evidence["available_family_count"] > 0
    if platform.system() == "Windows":
        assert evidence["resolved_family"] == WINDOWS_APPLICATION_FONT_FAMILY
        assert evidence["point_size"] == WINDOWS_APPLICATION_FONT_POINT_SIZE
        assert evidence["matches_native_windows_app"] is True


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="the native Segoe UI contract is Windows-specific",
)
def test_fresh_offscreen_process_resolves_segoe_ui_and_real_glyphs():
    script = """
import json
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from tools.virtual_workflows.qt_font_environment import (
    apply_and_validate_sil_application_font,
    configure_sil_qt_font_environment,
)
configure_sil_qt_font_environment()
from PySide6.QtWidgets import QApplication
app = QApplication([])
print(json.dumps(apply_and_validate_sil_application_font(app), sort_keys=True))
"""
    environment = os.environ.copy()
    environment.pop("QT_QPA_FONTDIR", None)
    environment["QT_QPA_PLATFORM"] = "offscreen"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["status"] == "pass"
    assert evidence["directory_source"] == "windows_system"
    assert evidence["resolved_family"] == "Segoe UI"
    assert evidence["point_size"] == 9.0
    assert evidence["raw_font_valid"] is True
    assert evidence["sample_glyphs_renderable"] is True
    assert evidence["matches_native_windows_app"] is True


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="the installed Windows minimal plugin behavior is platform-specific",
)
def test_minimal_platform_without_fonts_fails_closed():
    script = """
import json
import os
os.environ["QT_QPA_PLATFORM"] = "minimal"
from PySide6.QtWidgets import QApplication
from tools.virtual_workflows.qt_font_environment import (
    SilQtFontEnvironmentError,
    apply_and_validate_sil_application_font,
)
app = QApplication([])
try:
    apply_and_validate_sil_application_font(app)
except SilQtFontEnvironmentError as exc:
    print(json.dumps(exc.evidence, sort_keys=True))
else:
    raise SystemExit("minimal unexpectedly exposed a usable font")
"""
    environment = os.environ.copy()
    environment.pop("QT_QPA_FONTDIR", None)
    environment["QT_QPA_PLATFORM"] = "minimal"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["status"] == "fail"
    assert evidence["effective_qt_platform"] == "minimal"
    assert evidence["failure_reason"] == "no_font_families"
    assert evidence["available_family_count"] == 0
