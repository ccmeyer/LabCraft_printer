from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_normal_xy_route_is_unconditional_and_legacy_override_is_removed():
    header = _read("firmware/Core/Inc/CoordinatedXyExecutor.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    cmake = _read("firmware/tests_host/CMakeLists.txt")

    assert "LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE" not in header + gantry + cmake
    assert "coordinated_xy_legacy_gate_compile" not in cmake
    assert "return startCoordinatedXY(dx, dy, 0u);" in gantry


def test_direct_stepper_path_remains_for_homing_and_non_xy_axes():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    assert "Stepper* sz = Stepper::stepperZ();" in gantry
    assert "MX_STEPPERZ_Move" in gantry
    assert "Stepper::home" in stepper
    assert "DirectStepperProfile::prepare" in stepper


def test_orchestrator_always_validates_coordinated_completion():
    orchestrator = _read("firmware/Core/Src/Orchestrator.cpp")
    assert "coordinatedSnapshot" in orchestrator
    assert "endpointMatches" in orchestrator
    assert "targetsMatch" in orchestrator
    assert "LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE" not in orchestrator


def test_obsolete_firmware_selectors_and_cli_flags_are_absent():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    runner = _read("tools/run_selftest.py")
    for selector in (2049, 2059, 2069, 2075, 2076, 2077, 2079, 2084, 2085, 2086):
        assert f"selectedDiagnosticId == {selector}u" not in diagnostics
    for flag in (
        "--coordinated-xy-executor-suite",
        "--normal-xy-route-suite",
        "--coordinated-xy-performance-suite",
        "--coordinated-xy-40khz-suite",
        "--coordinated-xy-status-sync-suite",
        "--coordinated-xy-single-irq-suite",
        "--coordinated-xy-mres3-20khz-suite",
        "--coordinated-xy-mres3-rearm-suite",
        "--coordinated-xy-mres3-conditional-rearm-suite",
        "--coordinated-xy-x-direction-suite",
    ):
        assert flag not in runner


def test_unrelated_debug_legacy_board_configuration_remains():
    project = _read("firmware/.cproject")
    assert "Debug_Legacy" in project
    assert "MRES3_Diagnostic" not in project
