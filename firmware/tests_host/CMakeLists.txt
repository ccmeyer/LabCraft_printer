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

    # Add *selected* firmware sources here (NOT the whole firmware):
    # ../Src/protocol/ProtocolParser.cpp
    # ../Src/utils/RingBuffer.c
)

target_include_directories(fw_tests PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/stubs

    # Include firmware headers as needed:
    ${CMAKE_CURRENT_LIST_DIR}/../Inc
    ${CMAKE_CURRENT_LIST_DIR}/../Src
)

target_compile_definitions(fw_tests PRIVATE
    UNIT_TEST=1
)

target_link_libraries(fw_tests PRIVATE
    CppUTest
    CppUTestExt
)