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
    2010: TestCatalogEntry(2010, "XY long travel", "Long X/Y travel repeatability across the safe gantry envelope."),
    2011: TestCatalogEntry(2011, "XY raster repeatability", "Small serpentine moves that mimic well-plate printing motion."),
    2012: TestCatalogEntry(2012, "XY long reverse travel", "Reverse-order long X/Y travel repeatability across the safe gantry envelope."),
    2013: TestCatalogEntry(2013, "XY diagonal travel", "Coordinated diagonal X/Y moves between safe envelope corners."),
    2014: TestCatalogEntry(2014, "384-well plate raster", "Serpentine 16 x 24 plate raster from the far plate corner across the print envelope."),
    2015: TestCatalogEntry(2015, "Z long travel", "Repeated Z-axis long travel to near the safe upper envelope and back to home."),
    2016: TestCatalogEntry(2016, "Triggered-limit homing", "Homing recovery when X, Y, and Z begin with limit switches already triggered."),
    2201: TestCatalogEntry(2201, "Pressure hold leak", "Closed-loop pressure decay and correction effort."),
    2202: TestCatalogEntry(2202, "Pressure target cycling", "Repeated low/high target settling and pressure span."),
    2203: TestCatalogEntry(2203, "Pressure hysteresis", "Regulator motor repeatability and hysteresis span."),
    2210: TestCatalogEntry(2210, "Pressure idle stability", "Print/refuel sensor noise, drift, rejects, and safety faults while regulators are idle."),
    2211: TestCatalogEntry(2211, "Pressure regulator homing", "Print/refuel regulator homing repeatability after a fresh setup home."),
    2212: TestCatalogEntry(2212, "Print pressure hold", "Print regulator fresh-home 2 psi hold stability using production setpoint slew."),
    2213: TestCatalogEntry(2213, "Refuel pressure hold", "Refuel regulator fresh-home 2 psi hold stability using production setpoint slew."),
    2214: TestCatalogEntry(2214, "Print pressure cycling", "Print regulator same-direction low/high repeatability and transient over/under through adjacent 1 psi target steps using production setpoint slew."),
    2215: TestCatalogEntry(2215, "Refuel pressure cycling", "Refuel regulator same-direction low/high repeatability and transient over/under through adjacent 1 psi target steps using production setpoint slew."),
    2216: TestCatalogEntry(2216, "Print pressure hysteresis", "Print regulator fresh-home same-direction repeatability and informational approach-direction hysteresis at 2 psi."),
    2217: TestCatalogEntry(2217, "Refuel pressure hysteresis", "Refuel regulator fresh-home same-direction repeatability and informational approach-direction hysteresis at 2 psi."),
    2218: TestCatalogEntry(2218, "Print pressure step ladder", "Print regulator fresh-home settling and transient over/under through a 1, 2, 3, 2, 1 psi target ladder."),
    2219: TestCatalogEntry(2219, "Refuel pressure step ladder", "Refuel regulator fresh-home settling and transient over/under through a 1, 2, 3, 2, 1 psi target ladder."),
    2401: TestCatalogEntry(2401, "Print valve pulse drop", "Print valve pulse pressure-drop repeatability."),
    2402: TestCatalogEntry(2402, "Refuel valve pulse drop", "Refuel valve pulse pressure-drop repeatability."),
    2403: TestCatalogEntry(2403, "Dual valve interaction", "Print/refuel pulse interaction and pressure-drop balance."),
    2473: TestCatalogEntry(2473, "Print valve 2 psi repeatability", "Print valve isolated 2 psi grouped 1500, 3000, and 4500 us pulses with Python-derived steady settled pressure-drop repeatability, pulse-width linearity, ringing, actuation latency, and regulator-position context."),
    2474: TestCatalogEntry(2474, "Refuel valve 2 psi repeatability", "Refuel valve isolated 2 psi grouped 1500, 3000, and 4500 us pulses with Python-derived steady settled pressure-drop repeatability, pulse-width linearity, ringing, actuation latency, and regulator-position context."),
    2475: TestCatalogEntry(2475, "Valve channel balance at 2 psi", "Python-derived print/refuel channel balance at 2 psi using the isolated grouped steady settled-drop trace analysis without additional valve actuation."),
    2476: TestCatalogEntry(2476, "Print valve 1500 us gap sweep", "Exploratory print valve 2 psi 1500 us pulse traces with Python-derived settled pressure-drop response versus post-ready settle gap."),
    2477: TestCatalogEntry(2477, "Refuel valve 1500 us gap sweep", "Exploratory refuel valve 2 psi 1500 us pulse traces with Python-derived settled pressure-drop response versus post-ready settle gap."),
    2478: TestCatalogEntry(2478, "Print valve gap controls", "Exploratory print valve 2 psi 3000 and 4500 us control traces at short and long post-ready settle gaps."),
    2479: TestCatalogEntry(2479, "Refuel valve gap controls", "Exploratory refuel valve 2 psi 3000 and 4500 us control traces at short and long post-ready settle gaps."),
    2501: TestCatalogEntry(2501, "Gripper closed seal decay", "Short dummy-head seal decay after valve burst."),
    2502: TestCatalogEntry(2502, "Gripper seal hold duration", "Longer dummy-head seal hold and decay behavior."),
    2503: TestCatalogEntry(2503, "Gripper seal repeatability", "Repeated dummy-head seal retention and span."),
    2510: TestCatalogEntry(2510, "Gripper static pressure matrix", "Python-derived dummy-head seal pressure-drop response for 1, 2, and 3 psi long regulator-quiet pressure challenges with refresh disabled, using one unmeasured conditioning pulse per pressure before five measured decimated traces per channel."),
    2511: TestCatalogEntry(2511, "Gripper refreshed 3 psi hold", "Normal gripper refresh behavior during repeated 3 psi long pressure challenges over an extended hold, captured with decimated pressure traces."),
    2512: TestCatalogEntry(2512, "Gripper raster motion stress", "Dummy-head gripper seal behavior during a homed 384-well XY raster with normal refresh and repeated 3 psi regulator-quiet pressure challenges using decimated traces, then parks near X=500, Y=500."),
    2513: TestCatalogEntry(2513, "Gripper post-motion seal compare", "Python-derived pre/post raster 3 psi static seal comparison from decimated traces to detect motion-induced seal degradation."),
}


def test_catalog_entry(test_id: int) -> TestCatalogEntry:
    parsed = int(test_id)
    return TEST_CATALOG.get(
        parsed,
        TestCatalogEntry(parsed, f"Diagnostic {parsed}", "Diagnostic behavior defined by the manifest."),
    )


__all__ = ["TEST_CATALOG", "TestCatalogEntry", "test_catalog_entry"]
