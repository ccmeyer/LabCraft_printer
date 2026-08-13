from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pure_executor_has_no_hal_rtos_float_or_dynamic_runtime_dependency():
    header = _read("firmware/Core/Inc/CoordinatedXyExecutor.h")
    source = _read("firmware/Core/Src/CoordinatedXyExecutor.cpp")
    combined = header + source

    for forbidden in (
        "stm32",
        "HAL_",
        "FreeRTOS",
        "cmsis_os",
        "taskENTER",
        "float ",
        "double ",
        "cos(",
        "malloc",
        "calloc",
        "operator new",
        "throw ",
    ):
        assert forbidden not in combined
    assert '#include "CoordinatedXyPlanner.h"' in header


def test_executor_is_fixed_at_two_edges_per_master_step():
    header = _read("firmware/Core/Inc/CoordinatedXyExecutor.h")
    source = _read("firmware/Core/Src/CoordinatedXyExecutor.cpp")

    assert "TickStatus onTimerUpdate" in header
    assert "prepareCompleteStep" not in header + source
    assert "commitCompleteStep" not in header + source
    assert "ExecutionMode" not in header + source
    assert "cursor.risingEdges" in source
    assert "cursor.fallingEdges" in source
    assert "cursor.timerInterrupts" in source
    assert "result.accountCompletePulse = true" in source


def test_target_build_optimizes_only_the_bounded_executor_and_isr_paths():
    executor = _read("firmware/Core/Src/CoordinatedXyExecutor.cpp")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    instrumentation = _read(
        "firmware/Core/Src/CoordinatedXyIsrInstrumentation.cpp"
    )

    assert '#define LC_COORDINATED_EDGE_OPTIMIZED __attribute__((optimize("O2"), hot))' in executor
    assert "LC_COORDINATED_EDGE_OPTIMIZED\nTickStatus onTimerUpdate" in executor
    assert "_handleCoordinatedTim2BodyFromIsr" in gantry
    assert '#pragma GCC optimize("O2")' in instrumentation


def test_gantry_has_no_legacy_route_or_runtime_executor_selector():
    executor_header = _read("firmware/Core/Inc/CoordinatedXyExecutor.h")
    gantry_header = _read("firmware/Core/Inc/Gantry.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    orchestrator = _read("firmware/Core/Src/Orchestrator.cpp")

    combined = executor_header + gantry_header + gantry + orchestrator
    assert "LC_COORDINATED_XY_EXECUTOR_ENABLE" not in combined
    assert "LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE" not in combined
    assert "setCoordinatedExecutionModeForDiagnostics" not in combined
    assert "ExecutionMode" not in combined
    assert "startCoordinatedXY" in gantry
    assert "executeAbsoluteXy" in orchestrator
    assert "coordinatedSnapshot" in orchestrator


def test_xy_only_move_by_and_absolute_move_use_shared_executor():
    gantry = _read("firmware/Core/Src/Gantry.cpp")

    move_to = gantry[gantry.index("CoordinatedStartStatus Gantry::moveTo"):]
    move_to = move_to[: move_to.index("CoordinatedStartStatus Gantry::moveBy")]
    move_by = gantry[gantry.index("CoordinatedStartStatus Gantry::moveBy"):]
    move_by = move_by[: move_by.index("CoordinatedStartStatus Gantry::startCoordinatedXY")]
    assert "return startCoordinatedXY(dx, dy, 0u);" in move_by
    assert "return startCoordinatedXY(" in move_to
    assert "static_cast<int64_t>(canonicalX) - current.x" in move_to
    assert "static_cast<int64_t>(canonicalY) - current.y" in move_to
    assert "stepperX()->move" not in move_to
    assert "stepperY()->move" not in move_to


def test_isr_uses_fixed_conditional_rearm_order_after_physical_edge():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    start = gantry.index("bool Gantry::_handleCoordinatedTim2BodyFromIsr")
    end = gantry.index("bool Gantry::dispatchCoordinatedTimerFromIsr", start)
    handler = gantry[start:end]

    edge = handler.index("_writeCoordinatedStep")
    arr = handler.index("__HAL_TIM_SET_AUTORELOAD", edge)
    sample = handler.index("const uint32_t timerCount", arr)
    decision = handler.index("CoordinatedXyTimerSchedulePolicy::decide", sample)
    stop = handler.index("TIM_CR1_CEN", decision)
    reset = handler.index("__HAL_TIM_SET_COUNTER", stop)
    clear = handler.index("__HAL_TIM_CLEAR_FLAG", reset)
    restart = handler.index("SET_BIT(_coordinatedMasterTimer->Instance->CR1", clear)
    account = handler.index("_accountCoordinatedPulse", restart)
    assert edge < arr < sample < decision < stop < reset < clear < restart < account
    assert "lateInjection" not in handler
    assert "intentionalWait" not in handler


def test_generated_tim2_hooks_preserve_earliest_entry_and_post_hal_deadline_capture():
    interrupts = _read("firmware/Core/Src/stm32f4xx_it.c")
    tim2 = interrupts[interrupts.index("void TIM2_IRQHandler(void)"):]
    tim2 = tim2[: tim2.index("void TIM3_IRQHandler(void)")]

    entry = tim2.index("g_lcCoordinatedTim2IrqEntryCycle = DWT->CYCCNT")
    hal = tim2.index("HAL_TIM_IRQHandler")
    exit_hook = tim2.index("MX_GANTRY_RecordTim2IrqExit")
    assert entry < hal < exit_hook
    assert "USER CODE BEGIN TIM2_IRQn 0" in tim2
    assert "USER CODE BEGIN TIM2_IRQn 1" in tim2


def test_host_executor_tests_cover_counts_pause_cancel_limits_and_faults():
    tests = _read("firmware/tests_host/tests/test_coordinated_xy_executor.cpp")
    for name in (
        "EveryMagnitudePairUsesTwoEdgesPerMasterStep",
        "PauseWhileLowStopsImmediatelyAndResumesCachedEvent",
        "PauseWhileHighFinishesPulseThenResumesNextEvent",
        "CancelHighAccountsOnlyTheInFlightPulse",
        "LimitOverridesCancelAndPause",
        "PlannerMismatchFaultsAfterAccountingTheHighPulse",
    ):
        assert name in tests
    assert "CompleteStep" not in tests
