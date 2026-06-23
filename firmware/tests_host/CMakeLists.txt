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
    tests/test_orchestrator_decode.cpp
    tests/test_selftest_command_policy.cpp
    tests/test_nvm_codec.cpp
    tests/test_pressure_regulator_math.cpp
    tests/test_regulator_profile_command_policy.cpp
    tests/test_pressure_qualification_math.cpp
    tests/test_gripper_seal_qualification_math.cpp
    tests/test_valve_pulse_qualification_math.cpp
    tests/test_pressure_target_policy.cpp
    tests/test_pressure_trace_math.cpp
    tests/test_pressure_sensor_focus_policy.cpp
    tests/test_motion_qualification_math.cpp
    tests/test_stepper_profile_math.cpp
    tests/test_stepper_limit_policy.cpp
    tests/test_exti_debounce.cpp
    tests/test_crash_log_codec.cpp
    tests/test_reset_report_policy.cpp
    tests/test_flash_safety.cpp
    tests/test_flash_output_state.cpp
    tests/test_printer_completion_bits.cpp
    tests/test_diagnostic_result_emitter.cpp

    # Add *selected* firmware sources here (NOT the whole firmware):
    # ../Src/protocol/ProtocolParser.cpp
    # ../Src/utils/RingBuffer.c
    ../Core/Src/CommCodec.cpp
    ../Core/Src/DiagnosticResultEmitter.cpp
    ../Core/Src/OrchestratorCompletionPolicy.cpp
    ../Core/Src/OrchestratorDecode.cpp
    ../Core/Src/nvm_codec.c
    ../Core/Src/PressureRegulatorMath.cpp
    ../Core/Src/RegulatorProfileCommandPolicy.cpp
    ../Core/Src/PressureTraceRecorder.cpp
    ../Core/Src/PressureSensorFocusPolicy.cpp
    ../Core/Src/PressureQualificationMath.cpp
    ../Core/Src/GripperSealQualificationMath.cpp
    ../Core/Src/ValvePulseQualificationMath.cpp
    ../Core/Src/MotionQualificationMath.cpp
    ../Core/Src/StepperProfileMath.cpp
    ../Core/Src/CrashLogCodec.c
    ../Core/Src/ResetReportPolicy.cpp
    ../Core/Src/FlashSafety.cpp
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
