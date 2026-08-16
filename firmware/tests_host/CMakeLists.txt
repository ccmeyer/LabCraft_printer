cmake_minimum_required(VERSION 3.20)
project(LabCraftFirmwareHostTests C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# ---- CppUTest (as submodule) ----
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../third_party/cpputest
                 ${CMAKE_BINARY_DIR}/cpputest_build)

add_executable(fw_tests
    main.cpp
    tests/test_smoke.cpp
    tests/test_comm_codec.cpp
    tests/test_orchestrator_completion_policy.cpp
    tests/test_home_interruption_policy.cpp
    tests/test_orchestrator_decode.cpp
    tests/test_selftest_command_policy.cpp
    tests/test_nvm_codec.cpp
    tests/test_pressure_regulator_math.cpp
    tests/test_regulator_profile_command_policy.cpp
    tests/test_pressure_qualification_math.cpp
    tests/test_gripper_seal_qualification_math.cpp
    tests/test_valve_pulse_qualification_math.cpp
    tests/test_pressure_target_policy.cpp
    tests/test_regulator_pause_policy.cpp
    tests/test_pressure_regulator_watchdog_policy.cpp
    tests/test_regulator_telemetry.cpp
    tests/test_pressure_trace_math.cpp
    tests/test_pressure_sensor_focus_policy.cpp
    tests/test_pressure_sensor_watchdog_telemetry.cpp
    tests/test_selftest_scheduling_policy.cpp
    tests/test_motion_qualification_math.cpp
    tests/test_stepper_profile_math.cpp
    tests/test_direct_stepper_profile.cpp
    tests/test_direct_stepper_profile_report.cpp
    tests/test_normalized_cosine_profile.cpp
    tests/test_coordinated_xy_planner.cpp
    tests/test_coordinated_xy_executor.cpp
    tests/test_coordinated_xy_timer_schedule_policy.cpp
    tests/test_coordinated_xy_isr_instrumentation.cpp
    tests/test_coordinated_xy_performance_report.cpp
    tests/test_stepper_isr_instrumentation.cpp
    tests/test_stepper_instrumentation_report.cpp
    tests/test_stepper_limit_policy.cpp
    tests/test_motion_limit_debounce_policy.cpp
    tests/test_exti_debounce.cpp
    tests/test_crash_log_codec.cpp
    tests/test_crash_fault_context.cpp
    tests/test_reset_report_policy.cpp
    tests/test_crash_watchdog_selftest_policy.cpp
    tests/test_watchdog_participation_policy.cpp
    tests/test_flash_safety.cpp
    tests/test_flash_cycle_policy.cpp
    tests/test_flash_output_state.cpp
    tests/test_printer_completion_bits.cpp
    tests/test_printer_control_policy.cpp
    tests/test_gripper_refresh_policy.cpp
    tests/test_diagnostic_result_emitter.cpp
    tests/test_tmc2208_configuration.cpp
    tests/test_motion_unit_scale.cpp

    # Add *selected* firmware sources here (NOT the whole firmware):
    # ../Src/protocol/ProtocolParser.cpp
    # ../Src/utils/RingBuffer.c
    ../Core/Src/CommCodec.cpp
    ../Core/Src/DiagnosticResultEmitter.cpp
    ../Core/Src/OrchestratorCompletionPolicy.cpp
    ../Core/Src/HomeInterruptionPolicy.cpp
    ../Core/Src/OrchestratorDecode.cpp
    ../Core/Src/nvm_codec.c
    ../Core/Src/RegulatorTelemetry.c
    ../Core/Src/PressureRegulatorMath.cpp
    ../Core/Src/RegulatorProfileCommandPolicy.cpp
    ../Core/Src/RegulatorPausePolicy.cpp
    ../Core/Src/PressureTraceRecorder.cpp
    ../Core/Src/PressureSensorFocusPolicy.cpp
    ../Core/Src/PressureSensorWatchdogTelemetry.c
    ../Core/Src/SelfTestSchedulingPolicy.cpp
    ../Core/Src/PressureQualificationMath.cpp
    ../Core/Src/GripperSealQualificationMath.cpp
    ../Core/Src/ValvePulseQualificationMath.cpp
    ../Core/Src/MotionQualificationMath.cpp
    ../Core/Src/StepperProfileMath.cpp
    ../Core/Src/DirectStepperProfile.cpp
    ../Core/Src/DirectStepperProfileReport.cpp
    ../Core/Src/NormalizedCosineProfile.cpp
    ../Core/Src/CoordinatedXyPlanner.cpp
    ../Core/Src/CoordinatedXyExecutor.cpp
    ../Core/Src/CoordinatedXyIsrInstrumentation.cpp
    ../Core/Src/CoordinatedXyPerformanceReport.cpp
    ../Core/Src/StepperIsrInstrumentation.cpp
    ../Core/Src/StepperInstrumentationReport.cpp
    ../Core/Src/CrashLogCodec.c
    ../Core/Src/CrashFaultContext.c
    ../Core/Src/ResetReportPolicy.cpp
    ../Core/Src/CrashWatchdogSelfTestPolicy.cpp
    ../Core/Src/FlashSafety.cpp
    ../Core/Src/FlashCyclePolicy.cpp
    ../Core/Src/PrinterControlPolicy.cpp
    ../Core/Src/GripperRefreshPolicy.cpp
)

target_include_directories(fw_tests PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/stubs

    # Include firmware headers as needed:
    ${CMAKE_CURRENT_LIST_DIR}/../Core/Inc
    ${CMAKE_CURRENT_LIST_DIR}/../Core/Src
)

target_compile_definitions(fw_tests PRIVATE
    UNIT_TEST=1
)

target_link_libraries(fw_tests PRIVATE
    CppUTest
    CppUTestExt
)

# Verify both supported watchdog arming configurations at compile time. The
# production build uses the default target; immediate arming remains an
# explicit diagnostic/build override.
add_library(watchdog_arm_after_hello_compile OBJECT
    tests/compile_watchdog_arm_mode.cpp
)
target_include_directories(watchdog_arm_after_hello_compile PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/../Core/Inc
)
target_compile_definitions(watchdog_arm_after_hello_compile PRIVATE
    EXPECTED_WATCHDOG_ARM_MODE=1
)
set_target_properties(watchdog_arm_after_hello_compile PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED YES
)

add_library(watchdog_arm_immediate_compile OBJECT
    tests/compile_watchdog_arm_mode.cpp
)
target_include_directories(watchdog_arm_immediate_compile PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/../Core/Inc
)
target_compile_definitions(watchdog_arm_immediate_compile PRIVATE
    LC_WATCHDOG_ARM_MODE=0
    EXPECTED_WATCHDOG_ARM_MODE=0
)
set_target_properties(watchdog_arm_immediate_compile PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED YES
)

include(CheckCXXSourceCompiles)
set(_watchdog_saved_required_definitions "${CMAKE_REQUIRED_DEFINITIONS}")
set(_watchdog_saved_required_includes "${CMAKE_REQUIRED_INCLUDES}")
set(CMAKE_REQUIRED_DEFINITIONS "-DLC_WATCHDOG_ARM_MODE=2")
set(CMAKE_REQUIRED_INCLUDES "${CMAKE_CURRENT_LIST_DIR}/../Core/Inc")
unset(WATCHDOG_INVALID_ARM_MODE_COMPILES CACHE)
check_cxx_source_compiles(
    "#include \"WatchdogSupervisor.h\"\nint main() { return 0; }"
    WATCHDOG_INVALID_ARM_MODE_COMPILES
)
if(WATCHDOG_INVALID_ARM_MODE_COMPILES)
    message(FATAL_ERROR "Unsupported LC_WATCHDOG_ARM_MODE unexpectedly compiled")
endif()
set(CMAKE_REQUIRED_DEFINITIONS "${_watchdog_saved_required_definitions}")
set(CMAKE_REQUIRED_INCLUDES "${_watchdog_saved_required_includes}")
unset(_watchdog_saved_required_definitions)
unset(_watchdog_saved_required_includes)
