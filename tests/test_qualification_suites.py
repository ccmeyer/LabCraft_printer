from pathlib import Path

from QualificationSuites import build_test_plan_rows, discover_suite_entries, required_fixture_ids
from tools.qualification.manifest import load_manifest


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
        "gripper_seal_stress_v2",
        "xy_motion_v1",
        "motion_timing_v1",
        "profile_lut_benchmark_v1",
        "coordinated_xy_camera_transition_v2",
        "coordinated_xy_production_mres3_v3",
        "direct_xyz_lut_v1",
        "motion_envelope_v1",
        "pressure_regulator_v1",
        "refuel_vacuum_v1",
        "valve_characterization_v1",
        "valve_gap_sweep_v1",
    }.issubset(manifest_ids)
    assert entries[0].manifest_id == "factory_acceptance_v3"
    assert [entry.manifest_id for entry in entries[:9]] == [
        "factory_acceptance_v3",
        "gripper_seal_v1",
        "gripper_seal_stress_v2",
        "xy_motion_v1",
        "motion_timing_v1",
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
    gripper = entries["gripper_seal_stress_v2"].manifest

    assert gripper.requires_operator_prompts is True
    assert required_fixture_ids(gripper) == ("dummy_blocked_head_motion_v1",)
    assert "Firmware homes Z" in gripper.fixtures[0]["operator_note"]
    assert "evaporation-plate confirmation" in gripper.fixtures[0]["operator_note"]
    rows = {row.test_id: row for row in build_test_plan_rows(gripper)}
    assert list(rows) == [2510, 2511, 2512, 2513]
    assert rows[2510].name == "Gripper static pressure matrix"
    assert "conditioning pulse" in rows[2510].evaluates
    assert rows[2511].name == "Gripper deferred-refresh boundary"
    assert rows[2512].name == "Gripper raster motion stress"
    assert rows[2513].name == "Gripper post-motion seal compare"
    assert all(row.subsystem == "Gripper" for row in rows.values())
    assert "mode" in rows[2512].metrics
    assert "pending" in rows[2512].metrics
    assert "refresh_delta" in rows[2512].metrics
    assert "motion_only" in rows[2512].metrics
    assert "384-well" in rows[2512].evaluates
    assert "384-well XY raster" in rows[2512].evaluates
    assert "pre/post raster" in rows[2513].evaluates


def test_xy_motion_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    xy_motion = entries["xy_motion_v1"].manifest

    assert xy_motion.requires_operator_prompts is True
    assert required_fixture_ids(xy_motion) == ("motion_clear_envelope_v1",)
    assert "Firmware homes Z" in xy_motion.fixtures[0]["operator_note"]
    rows = {row.test_id: row for row in build_test_plan_rows(xy_motion)}
    assert list(rows) == [2010, 2011]
    assert rows[2010].name == "XY long travel"
    assert rows[2010].subsystem == "Motion"
    assert "x_span" in rows[2010].metrics
    assert "safe gantry envelope" in rows[2010].evaluates
    assert rows[2011].name == "XY raster repeatability"
    assert "well-plate" in rows[2011].evaluates


def test_motion_timing_suite_exposes_safety_gate_vectors_and_cycle_metrics():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    timing = entries["motion_timing_v1"].manifest

    assert timing.requires_operator_prompts is True
    assert required_fixture_ids(timing) == ("motion_clear_envelope_v1",)
    assert "6 kHz" in timing.fixtures[0]["operator_note"]
    assert "40 kHz" in timing.fixtures[0]["operator_note"]
    rows = {row.test_id: row for row in build_test_plan_rows(timing)}
    assert list(rows) == [2020, 2021, 2022, 2023, 2024, 2025]
    assert rows[2020].name == "Legacy XY low-rate timing"
    assert rows[2024].name == "Legacy camera/home-ratio timing"
    assert rows[2025].name == "Legacy short-triangular timing"
    assert all(row.subsystem == "Motion" for row in rows.values())
    assert all("am" in row.metrics for row in rows.values())
    assert all("cm" in row.metrics for row in rows.values())
    assert all("dm" in row.metrics for row in rows.values())
    assert "incident camera-to-home" in rows[2024].evaluates


def test_profile_lut_benchmark_suite_is_safe_non_motion_and_exposes_cycle_gates():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    benchmark = entries["profile_lut_benchmark_v1"].manifest

    assert benchmark.profile == "SAFE"
    assert benchmark.requires_operator_prompts is False
    assert required_fixture_ids(benchmark) == ()
    rows = build_test_plan_rows(benchmark)
    assert [row.test_id for row in rows] == [2030]
    assert rows[0].name == "Normalized cosine LUT timing"
    assert rows[0].subsystem == "System"
    assert "lut_max" in rows[0].metrics
    assert "speedup_x100" in rows[0].metrics
    assert "Non-motion" in rows[0].evaluates


def test_production_mres3_suite_requires_fixed_conditional_contract():
    entries = {
        entry.manifest_id: entry
        for entry in discover_suite_entries(MANIFEST_ROOT)
    }
    manifest = entries["coordinated_xy_production_mres3_v3"].manifest

    assert manifest.lifecycle == "active"
    assert manifest.profile == "FULL"
    assert manifest.selftest_args == ("--coordinated-xy-production-mres3-suite",)
    assert required_fixture_ids(manifest) == (
        "coordinated_xy_production_mres3_envelope_clear",
    )
    assert [row.test_id for row in build_test_plan_rows(manifest)] == [
        2087, 2088, 2089, 2090, 2098
    ]
    motion = manifest.analysis_rules["2087"]["metrics"]
    assert motion["n"]["equals"] == 10
    assert motion["i2"]["equals"] == 220000
    assert motion["tm"]["max"] == 2700
    schedule = manifest.analysis_rules["2089"]["metrics"]
    assert schedule["dc"]["equals"] == 219990
    assert schedule["ci"]["equals"] == 0
    assert schedule["ns"]["min"] == 1126
    assert schedule["rp"]["equals"] == 0
    assert manifest.analysis_rules["2090"]["metrics"]["lu"]["equals"] == 2
    debounce = manifest.analysis_rules["2098"]["metrics"]
    assert debounce["db"]["equals"] == 15
    assert debounce["tv"]["equals"] == 1
    assert debounce["xf"]["equals"] == 0
    assert debounce["yf"]["equals"] == 0


def test_archived_coordinated_suites_are_not_discoverable():
    entries = {entry.manifest_id for entry in discover_suite_entries(MANIFEST_ROOT)}
    for manifest_id in (
        "coordinated_xy_executor_v1",
        "normal_xy_route_v1",
        "coordinated_xy_performance_v1",
        "coordinated_xy_40khz_v1",
        "coordinated_xy_status_sync_v1",
        "coordinated_xy_single_irq_v1",
        "coordinated_xy_mres3_20khz_v2",
        "coordinated_xy_mres3_rearm_v1",
        "coordinated_xy_mres3_conditional_rearm_v3",
        "coordinated_xy_production_mres3_v1",
        "coordinated_xy_production_mres3_v2",
        "coordinated_xy_camera_transition_v1",
    ):
        assert manifest_id not in entries


def test_direct_xyz_lut_suite_requires_profile_coverage_and_isolation():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    manifest = entries["direct_xyz_lut_v1"].manifest

    assert manifest.profile == "FULL"
    assert manifest.selftest_args == ("--direct-xyz-lut-suite",)
    assert required_fixture_ids(manifest) == ("direct_xyz_lut_envelope_clear",)
    assert [row.test_id for row in build_test_plan_rows(manifest)] == [
        2091, 2092, 2093, 2094, 2095
    ]
    assert manifest.analysis_rules["2091"]["metrics"]["np"]["equals"] == 7000
    assert manifest.analysis_rules["2091"]["metrics"]["dc"]["equals"] == 5715
    assert manifest.analysis_rules["2093"]["metrics"]["en"]["equals"] == 0
    assert manifest.analysis_rules["2094"]["metrics"]["ai"]["equals"] == 1000
    assert manifest.analysis_rules["2095"]["metrics"]["pre"]["equals"] == 1
    assert manifest.analysis_rules["2095"]["metrics"]["post"]["equals"] == 1
    assert manifest.analysis_rules["2095"]["metrics"]["pd"]["equals"] == 0
    assert manifest.analysis_rules["2095"]["metrics"]["sn"]["min"] == 2
    assert manifest.analysis_rules["2095"]["metrics"]["sg"]["max"] == 125
    assert manifest.analysis_rules["2095"]["metrics"]["wd"]["max"] == 100
    assert manifest.analysis_rules["2095"]["metrics"]["sv"]["equals"] == 1
    assert "sn" not in manifest.analysis_rules["2091"]["metrics"]


def test_z_speed_ladder_suite_is_archived_and_not_launchable():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    assert "z_speed_ladder_v3" not in entries

    manifest = load_manifest("z_speed_ladder_v3")
    assert manifest.lifecycle == "archived"
    assert manifest.expected_test_ids == (2195, 2196, 2197, 2194)


def test_camera_transition_v2_is_single_production_scaled_gate():
    entries = {
        entry.manifest_id: entry
        for entry in discover_suite_entries(MANIFEST_ROOT)
    }
    focused = entries["coordinated_xy_camera_transition_v2"].manifest

    assert focused.lifecycle == "active"
    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == (
        "coordinated_xy_camera_transition_envelope_clear",
    )
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2071]
    assert rows[0].name == "Coordinated XY camera/home transition"
    rules = focused.analysis_rules["2071"]["metrics"]
    assert rules["xe"]["equals"] == 8416
    assert rules["ye"]["equals"] == 30000
    assert rules["i2"]["equals"] == 60000
    assert rules["hi"]["equals"] == 101
    assert rules["hpc"]["equals"] == 50


def test_motion_envelope_suite_exposes_operator_fixture_and_catalog_rows():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    motion = entries["motion_envelope_v1"].manifest

    assert motion.requires_operator_prompts is True
    assert required_fixture_ids(motion) == ("motion_full_envelope_v1",)
    assert "Firmware homes Z" in motion.fixtures[0]["operator_note"]
    assert "evaporation-plate confirmation" in motion.fixtures[0]["operator_note"]
    assert "Z=91500" in motion.fixtures[0]["operator_note"]
    assert "raster-start XY anchor" in motion.fixtures[0]["operator_note"]
    assert "80000 steps" in motion.fixtures[0]["operator_note"]
    rows = {row.test_id: row for row in build_test_plan_rows(motion)}
    assert list(rows) == [2012, 2013, 2014, 2015, 2016]
    assert rows[2012].name == "XY long reverse travel"
    assert rows[2013].name == "XY diagonal travel"
    assert rows[2014].name == "384-well plate raster"
    assert rows[2015].name == "Z long travel"
    assert rows[2016].name == "Triggered-limit homing"
    assert all(row.subsystem == "Motion" for row in rows.values())
    assert "pc" in rows[2014].metrics
    assert "pz" in rows[2014].metrics
    assert "z_to" in rows[2014].metrics
    assert "z_home_to" in rows[2014].metrics
    assert "evaporation-plate setup" in rows[2014].evaluates
    assert "Z lower to 91500" in rows[2014].evaluates
    assert "xy_to" in rows[2015].metrics
    assert "guard" in rows[2015].metrics
    assert "z_span" in rows[2015].metrics
    assert "80000 steps" in rows[2015].evaluates
    assert "raster-start XY anchor" in rows[2015].evaluates
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
