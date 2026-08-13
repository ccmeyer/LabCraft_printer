from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_z_speed_ladder_is_diagnostic_only_and_uses_tim10_user_hooks():
    diagnostics = (ROOT / "firmware/Core/Src/Diagnostics.cpp").read_text(encoding="utf-8")
    stepper = (ROOT / "firmware/Core/Src/Stepper.cpp").read_text(encoding="utf-8")
    interrupts = (ROOT / "firmware/Core/Src/stm32f4xx_it.c").read_text(encoding="utf-8")

    assert "selectedDiagnosticId == 2199u" in diagnostics
    assert "z_speed_ladder_60khz_confirm" in diagnostics
    assert "armZSpeedDiagnosticInstrumentation" in diagnostics
    assert "_zDiagnosticInstrumentationArmed" in stepper
    assert "g_lcStepperZTim10IrqTimingArmed" in interrupts
    assert "TIM1_UP_TIM10_IRQn 0" in interrupts
    assert "MX_STEPPERZ_RecordTim10IrqExit" in interrupts
    assert "setMaxSpeedHz(60000u)" in diagnostics


def test_existing_direct_z_contract_remains_uninstrumented():
    diagnostics = (ROOT / "firmware/Core/Src/Diagnostics.cpp").read_text(encoding="utf-8")
    start = diagnostics.index("if (runDirectXyzLutSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    direct = diagnostics[start:end]
    assert '"direct_lut_z_cruise"' in direct
    z_call = direct.rindex('"direct_lut_z_cruise"')
    assert "false);" in direct[z_call:z_call + 500]
