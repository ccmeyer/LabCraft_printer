from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_direct_lut_is_scoped_to_ordinary_cosine_xyz_moves():
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    selection = stepper.index("const bool useNormalizedCosineProfile")
    preparation = stepper.index("DirectStepperProfile::prepare", selection)
    gpio_start = stepper.index("// ---------- GPIO DIR/EN ----------", preparation)
    assert selection < preparation < gpio_start
    assert "(_axis == X_AXIS || _axis == Y_AXIS || _axis == Z_AXIS)" in stepper[
        selection:preparation
    ]
    assert "!_homeSequenceActive" in stepper[selection:preparation]
    assert "_profile == PROFILE_SCURVE_COSINE" in stepper[selection:preparation]
    assert "P_AXIS" not in stepper[selection:preparation]
    assert "R_AXIS" not in stepper[selection:preparation]


def test_direct_lut_fails_before_motor_enable_and_preserves_legacy_fallbacks():
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    preparation = stepper.index("DirectStepperProfile::prepare")
    rejection = stepper.index("_targetPos = _pos;", preparation)
    event = stepper.index("xEventGroupSetBits", rejection)
    motor_enable = stepper.index("// ---------- GPIO DIR/EN ----------", event)
    assert preparation < rejection < event < motor_enable
    assert "DirectStepperProfile::abort(_directProfileState);" in stepper[
        stepper.index("void Stepper::_requestSoftStop"):
        stepper.index("uint32_t Stepper::recommendedWaitTimeoutMs")
    ]
    assert "StepperProfileMath::ease01" in stepper[
        stepper.index("void Stepper::_stepTick"):
        stepper.index("void Stepper::dispatch")
    ]


def test_direct_lut_selector_uses_direct_axis_ownership_and_complete_inventory():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    branch = diagnostics.index("if (runDirectXyzLutSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", branch)
    body = diagnostics[branch:end]

    assert "moveAxisToWithTimeout" in body
    assert "Gantry::instance()->moveTo" not in body
    assert all(f"{{{test_id}u," in body for test_id in range(2091, 2096))
    assert "runZClearanceHomePreflight" in body
    assert "runXyHomeDiagnosticAttempt" in body
    assert "!stepperX->getLastDirectProfileSnapshot().selected" in body
    assert "pDelta == 0 && rDelta == 0" in body


def test_direct_lut_cli_routes_generic_selector_without_protocol_change():
    runner = _read("tools/run_selftest.py")
    assert 'selector_group.add_argument("--direct-xyz-lut-suite"' in runner
    assert "2096 if direct_xyz_lut_suite" in runner
    assert '"direct_xyz_lut_envelope_clear"' in runner
