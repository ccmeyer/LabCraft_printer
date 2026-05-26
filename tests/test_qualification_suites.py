from pathlib import Path

from QualificationSuites import build_test_plan_rows, discover_suite_entries, required_fixture_ids


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = REPO_ROOT / "tools" / "qualification" / "manifests"


def test_discover_suite_entries_lists_current_manifests():
    entries = discover_suite_entries(MANIFEST_ROOT)
    manifest_ids = {entry.manifest_id for entry in entries}

    assert {
        "factory_acceptance_v0",
        "factory_acceptance_v1",
        "factory_acceptance_v2",
        "factory_acceptance_v3",
        "gripper_seal_v1",
        "gripper_seal_stress_v1",
        "xy_motion_v1",
        "motion_envelope_v1",
        "pressure_regulator_v1",
        "refuel_vacuum_v1",
        "valve_characterization_v1",
        "valve_gap_sweep_v1",
    }.issubset(manifest_ids)
    assert entries[0].manifest_id == "factory_acceptance_v3"
    assert [entry.manifest_id for entry in entries[:8]] == [
        "factory_acceptance_v3",
        "gripper_seal_v1",
        "gripper_seal_stress_v1",
        "xy_motion_v1",
        "motion_envelope_v1",
        "pressure_regulator_v1",
        "refuel_vacuum_v1",
        "valve_characterization_v1",
    ]


def test_suite_rows_include_catalog_metadata_metrics_and_fixtures():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    rows = {row.test_id: row for row in build_test_plan_rows(entries["factory_acceptance_v3"].manifest)}

    assert rows[2007].name == "Motion home repeatability"
    assert rows[2007].subsystem == "Motion"
    assert "x_span" in rows[2007].metrics
    assert "motion_clear_envelope" in rows[2007].fixture_summary
    assert "Repeated homing" in rows[2007].evaluates


def test_gripper_suite_exposes_operator_fixture_requirement():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    gripper = entries["gripper_seal_v1"].manifest

    assert gripper.requires_operator_prompts is True
    assert required_fixture_ids(gripper) == ("dummy_blocked_head_v1",)
    rows = build_test_plan_rows(gripper)
    assert [row.test_id for row in rows] == [2501, 2502, 2503]
    assert all(row.subsystem == "Gripper" for row in rows)


def test_gripper_stress_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    gripper = entries["gripper_seal_stress_v1"].manifest

    assert gripper.requires_operator_prompts is True
    assert required_fixture_ids(gripper) == ("dummy_blocked_head_motion_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(gripper)}
    assert list(rows) == [2510, 2511, 2512, 2513]
    assert rows[2510].name == "Gripper static pressure matrix"
    assert "conditioning pulse" in rows[2510].evaluates
    assert rows[2511].name == "Gripper refreshed 3 psi hold"
    assert rows[2512].name == "Gripper raster motion stress"
    assert rows[2513].name == "Gripper post-motion seal compare"
    assert all(row.subsystem == "Gripper" for row in rows.values())
    assert "xy_home_to" in rows[2512].metrics
    assert "park_to" in rows[2512].metrics
    assert "384-well XY raster" in rows[2512].evaluates
    assert "X=500, Y=500" in rows[2512].evaluates
    assert "pre/post raster" in rows[2513].evaluates


def test_xy_motion_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    xy_motion = entries["xy_motion_v1"].manifest

    assert xy_motion.requires_operator_prompts is True
    assert required_fixture_ids(xy_motion) == ("motion_clear_envelope_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(xy_motion)}
    assert list(rows) == [2010, 2011]
    assert rows[2010].name == "XY long travel"
    assert rows[2010].subsystem == "Motion"
    assert "x_span" in rows[2010].metrics
    assert "safe gantry envelope" in rows[2010].evaluates
    assert rows[2011].name == "XY raster repeatability"
    assert "well-plate" in rows[2011].evaluates


def test_motion_envelope_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    motion = entries["motion_envelope_v1"].manifest

    assert motion.requires_operator_prompts is True
    assert required_fixture_ids(motion) == ("motion_full_envelope_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(motion)}
    assert list(rows) == [2012, 2013, 2014, 2015, 2016]
    assert rows[2012].name == "XY long reverse travel"
    assert rows[2013].name == "XY diagonal travel"
    assert rows[2014].name == "384-well plate raster"
    assert rows[2015].name == "Z long travel"
    assert rows[2016].name == "Triggered-limit homing"
    assert all(row.subsystem == "Motion" for row in rows.values())
    assert "z_span" in rows[2015].metrics
    assert "limit_start" in rows[2016].metrics


def test_pressure_regulator_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    pressure = entries["pressure_regulator_v1"].manifest

    assert pressure.requires_operator_prompts is True
    assert required_fixture_ids(pressure) == ("pressure_closed_loop_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(pressure)}
    assert list(rows) == [2210, 2211, 2212, 2213, 2214, 2215, 2216, 2217, 2218, 2219]
    assert rows[2210].name == "Pressure idle stability"
    assert rows[2211].name == "Pressure regulator homing"
    assert rows[2218].name == "Print pressure step ladder"
    assert rows[2219].name == "Refuel pressure step ladder"
    assert all(row.subsystem == "Pressure" for row in rows.values())
    assert "p_fault" in rows[2210].metrics
    assert "guard" in rows[2214].metrics
    assert "home_to" in rows[2214].metrics
    assert "low_dn_span" in rows[2214].metrics
    assert "high_up_span" in rows[2214].metrics
    assert "over" in rows[2214].metrics
    assert "under" in rows[2214].metrics
    assert "max_jump" in rows[2215].metrics
    assert "cap_hz" in rows[2215].metrics
    assert "below_span" in rows[2216].metrics
    assert "above_span" in rows[2216].metrics
    assert "hyst_span" in rows[2216].metrics
    assert "adjacent 1 psi target steps" in rows[2214].evaluates
    assert "production setpoint slew" in rows[2214].evaluates
    assert "same-direction" in rows[2216].evaluates
    assert "informational approach-direction hysteresis" in rows[2216].evaluates
    assert "settle_max_ms" in rows[2218].metrics
    assert "over" in rows[2218].metrics
    assert "under" in rows[2218].metrics
    assert "1, 2, 3, 2, 1 psi" in rows[2218].evaluates


def test_refuel_vacuum_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    vacuum = entries["refuel_vacuum_v1"].manifest

    assert vacuum.requires_operator_prompts is True
    assert required_fixture_ids(vacuum) == ("refuel_vacuum_dry_back_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(vacuum)}
    assert list(rows) == [2220, 2221]
    assert rows[2220].name == "Refuel vacuum sensor shift"
    assert rows[2221].name == "Refuel vacuum cycle repeatability"
    assert all(row.subsystem == "Pressure" for row in rows.values())
    assert "shift" in rows[2220].metrics
    assert "fault" in rows[2220].metrics
    assert "cyc" in rows[2221].metrics
    assert "ma" in rows[2221].metrics
    assert "-1 psi" in rows[2221].evaluates


def test_valve_characterization_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    valves = entries["valve_characterization_v1"].manifest

    assert valves.requires_operator_prompts is True
    assert required_fixture_ids(valves) == ("valve_closed_loop_pulse_matrix_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(valves)}
    assert list(rows) == [2473, 2474, 2475]
    assert rows[2473].name == "Print valve 2 psi repeatability"
    assert rows[2474].name == "Refuel valve 2 psi repeatability"
    assert rows[2475].name == "Valve channel balance at 2 psi"
    assert all(row.subsystem == "Valves/Pulses" for row in rows.values())
    assert "m15" in rows[2473].metrics
    assert "cv15" in rows[2473].metrics
    assert "home_to" in rows[2473].metrics
    assert "fresh_to" in rows[2473].metrics
    assert "rg15" in rows[2473].metrics
    assert "lt15" in rows[2473].metrics
    assert "r15" in rows[2475].metrics
    assert "home_to" in rows[2475].metrics
    assert "1500, 3000, and 4500 us" in rows[2473].evaluates
    assert "grouped" in rows[2473].evaluates
    assert "regulator-position context" in rows[2473].evaluates
    assert "settled pressure-drop" in rows[2473].evaluates
    assert "actuation latency" in rows[2473].evaluates
    assert "without additional valve actuation" in rows[2475].evaluates


def test_valve_gap_sweep_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    gap = entries["valve_gap_sweep_v1"].manifest

    assert gap.requires_operator_prompts is True
    assert required_fixture_ids(gap) == ("valve_closed_loop_pulse_matrix_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(gap)}
    assert list(rows) == [2476, 2477, 2478, 2479]
    assert rows[2476].name == "Print valve 1500 us gap sweep"
    assert rows[2477].name == "Refuel valve 1500 us gap sweep"
    assert rows[2478].name == "Print valve gap controls"
    assert rows[2479].name == "Refuel valve gap controls"
    assert all(row.subsystem == "Valves/Pulses" for row in rows.values())
    assert "g250" in rows[2476].metrics
    assert "g5000" in rows[2476].metrics
    assert "m30g500" in rows[2478].metrics
    assert "m45g2000" in rows[2479].metrics
    assert "post-ready settle gap" in rows[2476].evaluates
