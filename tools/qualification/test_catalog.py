from __future__ import annotations

from dataclasses import dataclass


__test__ = False


@dataclass(frozen=True)
class TestCatalogEntry:
    test_id: int
    display_name: str
    evaluates: str


TEST_CATALOG: dict[int, TestCatalogEntry] = {
    1001: TestCatalogEntry(1001, "Protocol CRC known vector", "Frame CRC/TLV decode baseline."),
    1002: TestCatalogEntry(1002, "Protocol frame round trip", "Self-test transport framing and command echo path."),
    1003: TestCatalogEntry(1003, "Status heartbeat", "MCU status stream availability and basic timing."),
    1004: TestCatalogEntry(1004, "Status pause/resume", "Status traffic control while diagnostic commands run."),
    1005: TestCatalogEntry(1005, "Flash configuration", "Firmware flash metadata exposed through diagnostics."),
    1006: TestCatalogEntry(1006, "Build identity", "Firmware build identity and version metadata."),
    1007: TestCatalogEntry(1007, "Flash CRC", "Stored firmware image integrity metadata."),
    1010: TestCatalogEntry(1010, "HELLO handshake", "Host-to-MCU session open handshake."),
    1011: TestCatalogEntry(1011, "GOODBYE handshake", "Host-to-MCU session close handshake."),
    1012: TestCatalogEntry(1012, "Duplicate command handling", "Command sequence duplicate detection behavior."),
    1013: TestCatalogEntry(1013, "Queue ACK details", "Command queue ACK metadata and sequence tracking."),
    1020: TestCatalogEntry(1020, "Status payload fields", "Core status payload field presence and parseability."),
    1021: TestCatalogEntry(1021, "Status timing", "Status frame period and jitter."),
    1030: TestCatalogEntry(1030, "Protocol parser resilience", "Parser handling for malformed or boundary frames."),
    1040: TestCatalogEntry(1040, "Runtime memory margins", "Heap and task stack margin telemetry."),
    1041: TestCatalogEntry(1041, "Reset/crash report path", "Reset report availability and crash-report plumbing."),
    1042: TestCatalogEntry(1042, "Watchdog diagnostic path", "Watchdog diagnostic reporting path."),
    2001: TestCatalogEntry(2001, "Motion homing", "Axis homing success, duration, and limit switch behavior."),
    2002: TestCatalogEntry(2002, "Motion move/return", "Bounded gantry move accuracy and return error."),
    2003: TestCatalogEntry(2003, "Pressure response", "Regulator settle time, overshoot, and steady-state error."),
    2004: TestCatalogEntry(2004, "Valve open/close sequence", "Valve command sequencing and observed open/close counts."),
    2005: TestCatalogEntry(2005, "Valve pulse timing", "Pulse count and pulse-width timing behavior."),
    2006: TestCatalogEntry(2006, "Safety abort", "Abort latency and safe state of motion, pressure, and valves."),
    2007: TestCatalogEntry(2007, "Motion home repeatability", "Repeated homing span and return error for gantry axes."),
    2008: TestCatalogEntry(2008, "Motion pattern return", "Pattern move return accuracy and envelope bounds."),
    2201: TestCatalogEntry(2201, "Pressure hold leak", "Closed-loop pressure decay and correction effort."),
    2202: TestCatalogEntry(2202, "Pressure target cycling", "Repeated low/high target settling and pressure span."),
    2203: TestCatalogEntry(2203, "Pressure hysteresis", "Regulator motor repeatability and hysteresis span."),
    2401: TestCatalogEntry(2401, "Print valve pulse drop", "Print valve pulse pressure-drop repeatability."),
    2402: TestCatalogEntry(2402, "Refuel valve pulse drop", "Refuel valve pulse pressure-drop repeatability."),
    2403: TestCatalogEntry(2403, "Dual valve interaction", "Print/refuel pulse interaction and pressure-drop balance."),
    2501: TestCatalogEntry(2501, "Gripper closed seal decay", "Short dummy-head seal decay after valve burst."),
    2502: TestCatalogEntry(2502, "Gripper seal hold duration", "Longer dummy-head seal hold and decay behavior."),
    2503: TestCatalogEntry(2503, "Gripper seal repeatability", "Repeated dummy-head seal retention and span."),
}


def test_catalog_entry(test_id: int) -> TestCatalogEntry:
    parsed = int(test_id)
    return TEST_CATALOG.get(
        parsed,
        TestCatalogEntry(parsed, f"Diagnostic {parsed}", "Diagnostic behavior defined by the manifest."),
    )


__all__ = ["TEST_CATALOG", "TestCatalogEntry", "test_catalog_entry"]
