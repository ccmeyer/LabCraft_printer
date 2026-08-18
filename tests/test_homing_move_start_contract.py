from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _function_body(source, signature, next_signature):
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def test_homing_start_policy_is_bounded_and_direction_aware():
    policy = _read("firmware/Core/Inc/StepperLimitPolicy.h")
    host_tests = _read("firmware/tests_host/tests/test_stepper_limit_policy.cpp")

    assert "enum class HomeMoveStartKind" in policy
    assert "enum class HomeMoveStartAction" in policy
    assert "classifyHomeMoveStart(" in policy
    assert "movingTowardLimit &&" in policy
    assert "!retryAlreadyUsed" in policy
    assert "HomingTowardBlockedLimitGetsOneReleaseRetry" in host_tests
    assert "HomingDoesNotRetryAwayOrNonLimitStartFailures" in host_tests


def test_every_internal_home_move_consumes_start_status_before_waiting():
    source = _read("firmware/Core/Src/Stepper.cpp")
    home = _function_body(
        source,
        "HomeInterruptionPolicy::Outcome Stepper::home(",
        "bool Stepper::waitUntilDone(",
    )
    release = _function_body(
        source,
        "bool Stepper::_backOffLimitUntilReleased(",
        "void Stepper::_resetMoveLimitState()",
    )

    start_assignment = "result.startStatus = move(direction, steps, freqHz, 0u);"
    assert start_assignment in home
    assert home.index(start_assignment) < home.index("waitUntilDone(timeoutMs, cancelToken)")
    assert "classifyHomeMoveStart(" in home
    assert "HomeMoveStartAction::WaitForMotion" in home
    assert "xEventGroupClearBits(Orchestrator::getDoneEvents(), _doneBit);" in home

    release_assignment = "const DirectMoveStartStatus startStatus =\n        move("
    assert release_assignment in release
    assert release.index(release_assignment) < release.index(
        "waitUntilDone(timeoutMs, cancelToken)"
    )
    assert "startAction != StepperLimitPolicy::HomeMoveStartAction::WaitForMotion" in release


def test_homing_retries_only_toward_phases_and_validates_terminal_state():
    source = _read("firmware/Core/Src/Stepper.cpp")
    home = _function_body(
        source,
        "HomeInterruptionPolicy::Outcome Stepper::home(",
        "bool Stepper::waitUntilDone(",
    )

    assert "HomeMoveStartAction::ReleaseAndRetry" in home
    assert "blockedStartRecoveryCount++" in home
    assert "retryAlreadyUsed = true;" in home
    assert "_backOffLimitUntilReleased(" in home
    assert '"coarse seek"' in home
    assert '"probe"' in home
    assert '"fine seek"' in home
    assert '"final backoff"' in home

    assert "(terminalCompleted && endpointMatches) || terminalLimitAborted" in home
    assert "terminalCompleted && endpointMatches" in home
    assert "canceledWithRestore()" in home


def test_release_moves_require_a_completed_exact_endpoint():
    source = _read("firmware/Core/Src/Stepper.cpp")
    release = _function_body(
        source,
        "bool Stepper::_backOffLimitUntilReleased(",
        "void Stepper::_resetMoveLimitState()",
    )

    assert "terminal.state == DirectMoveState::Completed" in release
    assert "terminal.terminalReason == DirectMoveTerminalReason::Completed" in release
    assert "terminal.endPosition == terminal.targetPosition" in release
    assert "_pos == terminal.targetPosition" in release
    assert "HomeInterruptionPolicy::cancellationRequested(cancelToken)" in release


def test_homing_waits_for_a_terminal_move_not_only_zero_remaining_toggles():
    source = _read("firmware/Core/Src/Stepper.cpp")
    wait = _function_body(
        source,
        "bool Stepper::waitUntilDone(",
        "Stepper::LimitStableSample Stepper::_sampleLimitStable(",
    )

    assert "if ((result & _doneBit) != 0u)" in wait
    assert "const DirectMoveSnapshot snapshot = getLastDirectMoveSnapshot();" in wait
    assert "snapshot.state == DirectMoveState::Completed" in wait
    assert "terminal && _togglesRemaining == 0u" in wait
    assert "if (_togglesRemaining == 0u)" not in wait
    assert "while (_togglesRemaining != 0u)" not in wait


def test_full_hil_home_gate_reports_start_and_terminal_diagnostics():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    home_gate_start = diagnostics.index('"motion_home_cycle_full"', 1000)
    home_gate = diagnostics[home_gate_start:]

    assert "getLastHomeDiagnosticSnapshot()" in home_gate
    assert '"x_pos=%ld;x_phase=%u;x_out=%u;x_start=%u;x_rec=%lu;x_fail=%lu;x_to=%lu;"' in home_gate
    assert '"y_pos=%ld;y_phase=%u;y_out=%u;y_start=%u;y_rec=%lu;y_fail=%lu;y_to=%lu"' in home_gate


def test_x_motion_timer_is_not_started_during_peripheral_initialization():
    main = _read("firmware/Core/Src/main.c")
    tim2_init = _function_body(
        main,
        "static void MX_TIM2_Init(void)\n{",
        "static void MX_TIM3_Init(void)",
    )

    assert "HAL_TIM_Base_Init(&htim2)" in tim2_init
    assert "HAL_TIM_Base_Start_IT(&htim2)" not in tim2_init
    assert "__HAL_TIM_ENABLE_IT(&htim2" not in tim2_init


def test_rejected_start_restores_live_target_but_keeps_forensic_target():
    source = _read("firmware/Core/Src/Stepper.cpp")
    reject_start = source.index(
        "StepperLimitPolicy::DirectStartDecision::RejectAssertedTowardLimit"
    )
    reject_end = source.index(
        "return DirectMoveStartStatus::LimitBlocked;", reject_start
    )
    reject = source[reject_start:reject_end]

    snapshot_target = source.rfind(
        "_directMoveSnapshot.targetPosition = _targetPos;", 0, reject_start
    )
    assert snapshot_target >= 0
    assert "_targetPos = _pos;" in reject
