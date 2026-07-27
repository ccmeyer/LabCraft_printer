"""Fail-closed font setup for headless SIL screenshots."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any, MutableMapping


WINDOWS_APPLICATION_FONT_FAMILY = "Segoe UI"
WINDOWS_APPLICATION_FONT_POINT_SIZE = 9.0
FONT_RENDER_SAMPLE = "SIL Editor Aa09"
_FONT_SUFFIXES = {".otf", ".ttc", ".ttf"}


class SilQtFontEnvironmentError(RuntimeError):
    """Raised when Qt cannot render trustworthy SIL screenshot text."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = dict(evidence)


def _base_qt_platform(value: str | None) -> str:
    return str(value or "").split(":", 1)[0].strip().lower()


def _resolved_font_directory(
    value: str | os.PathLike[str],
    *,
    label: str,
) -> Path:
    directory = Path(value).expanduser().resolve()
    if not directory.is_dir():
        raise SilQtFontEnvironmentError(
            f"{label} is not an existing directory: {directory}",
            evidence={
                "status": "fail",
                "configured_directory": str(directory),
                "failure_reason": "font_directory_missing",
            },
        )
    if not any(
        child.is_file() and child.suffix.lower() in _FONT_SUFFIXES
        for child in directory.iterdir()
    ):
        raise SilQtFontEnvironmentError(
            f"{label} contains no supported font files: {directory}",
            evidence={
                "status": "fail",
                "configured_directory": str(directory),
                "failure_reason": "font_directory_empty",
            },
        )
    return directory


def _windows_font_directory(
    environ: MutableMapping[str, str],
    *,
    windows_directory: str | os.PathLike[str] | None,
) -> Path:
    root = windows_directory or environ.get("WINDIR")
    if not root:
        raise SilQtFontEnvironmentError(
            "WINDIR is unavailable; the Windows SIL font directory cannot be resolved",
            evidence={
                "status": "fail",
                "configured_directory": None,
                "failure_reason": "windows_directory_unavailable",
            },
        )
    directory = _resolved_font_directory(
        Path(root) / "Fonts",
        label="Windows font directory",
    )
    expected_file = directory / "segoeui.ttf"
    if not expected_file.is_file():
        raise SilQtFontEnvironmentError(
            f"the normal LabCraft Windows font is missing: {expected_file}",
            evidence={
                "status": "fail",
                "configured_directory": str(directory),
                "failure_reason": "segoe_ui_missing",
                "requested_family": WINDOWS_APPLICATION_FONT_FAMILY,
            },
        )
    return directory


def configure_sil_qt_font_environment(
    *,
    qt_platform: str | None = None,
    system_name: str | None = None,
    environ: MutableMapping[str, str] | None = None,
    windows_directory: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Configure font discovery before QApplication is constructed.

    The function intentionally imports no Qt modules so registry and CLI
    inspection remain application-import free.
    """

    target = environ if environ is not None else os.environ
    selected_platform = qt_platform or target.get("QT_QPA_PLATFORM")
    operating_system = system_name or platform.system()
    base_platform = _base_qt_platform(selected_platform)
    configured = target.get("QT_QPA_FONTDIR")

    if configured:
        directory = _resolved_font_directory(
            configured,
            label="QT_QPA_FONTDIR",
        )
        return {
            "directory_source": "caller",
            "configured_directory": str(directory),
            "qt_platform": selected_platform,
        }

    if operating_system == "Windows" and base_platform == "offscreen":
        directory = _windows_font_directory(
            target,
            windows_directory=windows_directory,
        )
        target["QT_QPA_FONTDIR"] = str(directory)
        return {
            "directory_source": "windows_system",
            "configured_directory": str(directory),
            "qt_platform": selected_platform,
        }

    return {
        "directory_source": "native",
        "configured_directory": None,
        "qt_platform": selected_platform,
    }


def _directory_evidence(
    environ: MutableMapping[str, str],
    *,
    operating_system: str,
) -> tuple[str, str | None]:
    configured = environ.get("QT_QPA_FONTDIR")
    if not configured:
        return "native", None

    directory = Path(configured).expanduser().resolve()
    if operating_system == "Windows":
        windows_root = environ.get("WINDIR")
        if windows_root:
            expected = (Path(windows_root) / "Fonts").resolve()
            if directory == expected:
                return "windows_system", str(directory)
    return "caller", str(directory)


def apply_and_validate_sil_application_font(
    app: Any,
    *,
    system_name: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """Apply the normal Windows font when headless and validate real glyphs."""

    if app is None:
        raise SilQtFontEnvironmentError(
            "a QApplication instance is required for SIL font validation",
            evidence={
                "status": "fail",
                "failure_reason": "application_missing",
            },
        )

    from PySide6 import QtGui

    target = environ if environ is not None else os.environ
    operating_system = system_name or platform.system()
    effective_platform = str(app.platformName() or "")
    base_platform = _base_qt_platform(effective_platform)
    directory_source, configured_directory = _directory_evidence(
        target,
        operating_system=operating_system,
    )
    families = [str(value) for value in QtGui.QFontDatabase.families()]
    evidence: dict[str, Any] = {
        "status": "fail",
        "directory_source": directory_source,
        "configured_directory": configured_directory,
        "requested_family": (
            WINDOWS_APPLICATION_FONT_FAMILY
            if operating_system == "Windows" and base_platform == "offscreen"
            else None
        ),
        "resolved_family": None,
        "point_size": None,
        "available_family_count": len(families),
        "raw_font_valid": False,
        "sample": FONT_RENDER_SAMPLE,
        "sample_glyphs_renderable": False,
        "matches_native_windows_app": False,
        "effective_qt_platform": effective_platform,
    }

    if not families:
        evidence["failure_reason"] = "no_font_families"
        raise SilQtFontEnvironmentError(
            "Qt exposes no font families; headless SIL screenshots would be unreadable",
            evidence=evidence,
        )

    if operating_system == "Windows" and base_platform == "offscreen":
        matching_family = next(
            (
                family
                for family in families
                if family.casefold()
                == WINDOWS_APPLICATION_FONT_FAMILY.casefold()
            ),
            None,
        )
        if matching_family is None:
            evidence["failure_reason"] = "segoe_ui_unavailable"
            raise SilQtFontEnvironmentError(
                "Segoe UI is unavailable to offscreen Qt; "
                "check QT_QPA_FONTDIR and the Windows font installation",
                evidence=evidence,
            )
        font = QtGui.QFont(matching_family)
        font.setPointSizeF(WINDOWS_APPLICATION_FONT_POINT_SIZE)
        app.setFont(font)

    application_font = app.font()
    font_info = QtGui.QFontInfo(application_font)
    resolved_family = str(font_info.family() or "")
    point_size = float(application_font.pointSizeF())
    raw_font = QtGui.QRawFont.fromFont(application_font)
    raw_valid = bool(raw_font.isValid())
    glyph_indexes = (
        [int(value) for value in raw_font.glyphIndexesForString(FONT_RENDER_SAMPLE)]
        if raw_valid
        else []
    )
    glyphs_renderable = (
        len(glyph_indexes) == len(FONT_RENDER_SAMPLE)
        and all(
            character.isspace() or glyph_index > 0
            for character, glyph_index in zip(
                FONT_RENDER_SAMPLE,
                glyph_indexes,
            )
        )
    )
    matches_windows_app = (
        operating_system == "Windows"
        and resolved_family.casefold()
        == WINDOWS_APPLICATION_FONT_FAMILY.casefold()
        and abs(point_size - WINDOWS_APPLICATION_FONT_POINT_SIZE) < 0.01
    )
    evidence.update(
        {
            "resolved_family": resolved_family,
            "point_size": point_size,
            "raw_font_valid": raw_valid,
            "sample_glyph_indexes": glyph_indexes,
            "sample_glyphs_renderable": glyphs_renderable,
            "matches_native_windows_app": matches_windows_app,
        }
    )

    if not resolved_family:
        evidence["failure_reason"] = "font_family_unresolved"
        raise SilQtFontEnvironmentError(
            "Qt could not resolve the application font family",
            evidence=evidence,
        )
    if not raw_valid:
        evidence["failure_reason"] = "raw_font_invalid"
        raise SilQtFontEnvironmentError(
            f"Qt could not construct a raw font for {resolved_family}",
            evidence=evidence,
        )
    if not glyphs_renderable:
        evidence["failure_reason"] = "sample_glyphs_missing"
        raise SilQtFontEnvironmentError(
            f"{resolved_family} cannot render the required SIL text sample",
            evidence=evidence,
        )

    evidence["status"] = "pass"
    evidence["failure_reason"] = None
    return evidence


__all__ = [
    "FONT_RENDER_SAMPLE",
    "SilQtFontEnvironmentError",
    "WINDOWS_APPLICATION_FONT_FAMILY",
    "WINDOWS_APPLICATION_FONT_POINT_SIZE",
    "apply_and_validate_sil_application_font",
    "configure_sil_qt_font_environment",
]
