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
        "motion_timing_v1",
        "profile_lut_benchmark_v1",
        "coordinated_xy_executor_v1",
        "normal_xy_route_v1",
        "coordinated_xy_performance_v1",
        "coordinated_xy_x_direction_v1",
        "coordinated_xy_camera_transition_v1",
        "coordinated_xy_production_mres3_v1",
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
        "gripper_seal_stress_v1",
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
    gripper = entries["gripper_seal_stress_v1"].manifest

    assert gripper.requires_operator_prompts is True
    assert required_fixture_ids(gripper) == ("dummy_blocked_head_motion_v1",)
    assert "Firmware homes Z" in gripper.fixtures[0]["operator_note"]
    assert "evaporation-plate confirmation" in gripper.fixtures[0]["operator_note"]
    rows = {row.test_id: row for row in build_test_plan_rows(gripper)}
    assert list(rows) == [2510, 2511, 2512, 2513]
    assert rows[2510].name == "Gripper static pressure matrix"
    assert "conditioning pulse" in rows[2510].evaluates
    assert rows[2511].name == "Gripper refreshed 3 psi hold"
    assert rows[2512].name == "Gripper raster motion stress"
    assert rows[2513].name == "Gripper post-motion seal compare"
    assert all(row.subsystem == "Gripper" for row in rows.values())
    assert "z_home_to" in rows[2512].metrics
    assert "pc" in rows[2512].metrics
    assert "pz" in rows[2512].metrics
    assert "z_to" in rows[2512].metrics
    assert "xy_home_to" in rows[2512].metrics
    assert "park_to" in rows[2512].metrics
    assert "Z-clearance" in rows[2512].evaluates
    assert "operator-confirmed evaporation-plate setup" in rows[2512].evaluates
    assert "Z lower to 91500" in rows[2512].evaluates
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


def test_coordinated_xy_executor_suite_exposes_loaded_motion_safety_gates():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    executor = entries["coordinated_xy_executor_v1"].manifest

    assert executor.profile == "FULL"
    assert executor.requires_operator_prompts is True
    assert required_fixture_ids(executor) == ("motion_clear_envelope_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(executor)}
    assert list(rows) == [2040, 2041, 2042, 2043, 2044, 2045, 2046]
    assert rows[2040].name == "Coordinated XY X-only low-rate"
    assert rows[2043].name == "Coordinated XY asymmetric low-rate"
    assert rows[2046].name == "Coordinated XY limit abort"
    assert all(row.subsystem == "Motion" for row in rows.values())
    assert "i2" in rows[2042].metrics
    assert "stable" in rows[2044].metrics
    assert "lat" in rows[2045].metrics
    assert "xd" in rows[2046].metrics


def test_normal_xy_route_suite_exposes_physical_limit_and_legacy_gates():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    route = entries["normal_xy_route_v1"].manifest

    assert route.profile == "FULL"
    assert route.requires_operator_prompts is True
    assert required_fixture_ids(route) == ("coordinated_xy_physical_limit_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(route)}
    assert list(rows) == list(range(2050, 2058))
    assert rows[2050].name == "Normal XY route X-only low-rate"
    assert rows[2054].name == "Normal XY route long status"
    assert rows[2056].name == "Normal XY physical limit"
    assert rows[2057].name == "Normal XY legacy smoke"
    assert all(row.subsystem == "Motion" for row in rows.values())
    assert "route" in rows[2050].metrics
    assert "sg" in rows[2054].metrics
    assert "lat" in rows[2055].metrics
    assert "win" in rows[2056].metrics
    assert "z" in rows[2057].metrics


def test_coordinated_xy_performance_suite_exposes_speed_raster_and_pressure_gates():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    performance = entries["coordinated_xy_performance_v1"].manifest

    assert performance.profile == "FULL"
    assert required_fixture_ids(performance) == ("pressure_closed_loop_v1",)
    rows = {row.test_id: row for row in build_test_plan_rows(performance)}
    assert list(rows) == [*range(2060, 2069), 2070]
    assert rows[2060].name == "Coordinated XY 5 kHz performance"
    assert rows[2068].name == "Coordinated XY pressure coexistence"
    assert rows[2070].name == "Coordinated XY X-direction speed isolation"
    assert all(row.subsystem == "System" for row in rows.values())
    assert "am" in rows[2064].metrics
    assert "xd" in rows[2066].metrics
    assert "pm" in rows[2068].metrics
    assert "p40" in rows[2070].metrics


def test_coordinated_xy_x_direction_suite_is_a_single_focused_gate():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_x_direction_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == ("pressure_closed_loop_v1",)
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2070]
    assert "p30" in rows[0].metrics
    assert "n40" in rows[0].metrics


def test_coordinated_xy_40khz_suite_is_only_the_existing_geometry_row():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_40khz_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == ("motion_clear_envelope_v1",)
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2064, 2072, 2073]
    assert rows[0].name == "Coordinated XY 40 kHz performance"
    assert "am" in rows[0].metrics
    assert "xd" in rows[0].metrics
    assert rows[1].name == "Coordinated XY 40 kHz full IRQ timing"
    assert "fm" in rows[1].metrics
    assert "pf" in rows[1].metrics
    assert rows[2].name == "Coordinated XY 40 kHz entry lateness"
    assert "pm" in rows[2].metrics
    assert "dm" in rows[2].metrics


def test_coordinated_xy_status_sync_suite_reuses_the_geometry_rows_with_strict_lateness():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_status_sync_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == ("motion_clear_envelope_v1",)
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2064, 2072, 2073]
    assert "sm" in rows[2].metrics
    assert "lf" in rows[2].metrics
    rules = focused.analysis_rules["2073"]["metrics"]
    assert rules["sm"]["equals"] == 1
    assert rules["lf"]["equals"] == 0
    assert rules["cm"]["max"] == 127
    assert rules["lc"]["equals"] == 0
    assert rules["dm"]["max"] == 255


def test_coordinated_xy_mres3_suite_exposes_scaled_motion_and_deadline_evidence():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_mres3_20khz_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == (
        "coordinated_xy_mres3_20khz_envelope_clear",
    )
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2080, 2081, 2082, 2083]
    assert rows[0].name == "Coordinated XY MRES3 20 kHz motion"
    assert rows[3].name == "TMC2208 MRES3 configuration"
    assert focused.analysis_rules["2080"]["metrics"]["hz"]["equals"] == 20000
    assert focused.analysis_rules["2082"]["metrics"]["sl"]["min"] == 450
    assert focused.analysis_rules["2083"]["metrics"]["mf"]["equals"] == 0


def test_coordinated_xy_mres3_rearm_suite_requires_complete_rearm_coverage():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_mres3_rearm_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == (
        "coordinated_xy_mres3_rearm_envelope_clear",
    )
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2080, 2081, 2082, 2083]
    rules = focused.analysis_rules["2082"]["metrics"]
    assert rules["rm"]["equals"] == 1
    assert rules["rc"]["equals"] == 219990
    assert rules["rp"]["equals"] == 0
    assert rules["lc"]["maturity"] == "candidate"


def test_coordinated_xy_mres3_conditional_suite_requires_injected_recovery():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_mres3_conditional_rearm_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == (
        "coordinated_xy_mres3_conditional_rearm_envelope_clear",
    )
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2080, 2081, 2082, 2086, 2083]
    rules = focused.analysis_rules["2086"]["metrics"]
    assert rules["rm"]["equals"] == 2
    assert rules["rg"]["equals"] == 1125
    assert rules["dc"]["equals"] == 219990
    assert rules["ic"]["equals"] == 10
    assert rules["ix"]["equals"] == 0
    assert rules["ir"]["equals"] == 10
    assert rules["ns"]["min"] == 1126
    assert rules["wm"]["max"] == 4500


def test_coordinated_xy_mres3_revised_suites_require_strict_and_hard_masks():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}

    for manifest_id in (
        "coordinated_xy_mres3_20khz_v2",
        "coordinated_xy_mres3_conditional_rearm_v2",
        "coordinated_xy_mres3_conditional_rearm_v3",
    ):
        manifest = entries[manifest_id].manifest
        motion = manifest.analysis_rules["2080"]["metrics"]
        margin = manifest.analysis_rules["2082"]["metrics"]
        assert motion["qf"]["equals"] == 0
        assert motion["qm"]["equals"] == 0
        assert margin["fv"]["equals"] == 0
        assert margin["hm"]["equals"] == 0


def test_production_mres3_suite_requires_logical_conversion_and_conditional_rearm():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    manifest = entries["coordinated_xy_production_mres3_v1"].manifest

    assert manifest.profile == "FULL"
    assert manifest.selftest_args == ("--coordinated-xy-production-mres3-suite",)
    assert required_fixture_ids(manifest) == (
        "coordinated_xy_production_mres3_envelope_clear",
    )
    assert [row.test_id for row in build_test_plan_rows(manifest)] == [
        2087, 2088, 2089, 2090
    ]
    assert manifest.analysis_rules["2087"]["metrics"]["i2"]["equals"] == 220000
    assert manifest.analysis_rules["2089"]["metrics"]["rm"]["equals"] == 2
    assert manifest.analysis_rules["2089"]["metrics"]["dc"]["equals"] == 219990
    assert manifest.analysis_rules["2089"]["metrics"]["ci"]["equals"] == 0
    assert manifest.analysis_rules["2089"]["metrics"]["ns"]["min"] == 1126
    assert manifest.analysis_rules["2089"]["metrics"]["rp"]["equals"] == 0
    assert manifest.analysis_rules["2090"]["metrics"]["lu"]["equals"] == 2


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


def test_coordinated_xy_single_irq_suite_requires_complete_pulse_margin_evidence():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_single_irq_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == ("motion_clear_envelope_v1",)
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2064, 2072, 2073, 2074]
    assert rows[3].name == "Coordinated XY single-IRQ pulse margin"
    rules = focused.analysis_rules["2074"]["metrics"]
    assert rules["em"]["equals"] == 1
    assert rules["ip"]["equals"] == 1
    assert rules["pc"]["equals"] == 220000
    assert rules["pn"]["min"] == 360
    assert rules["ds"]["equals"] == 220000
    assert rules["sl"]["min"] == 500


def test_coordinated_xy_camera_transition_suite_is_single_motion_fixture_gate():
    entries = {entry.manifest_id: entry for entry in discover_suite_entries(MANIFEST_ROOT)}
    focused = entries["coordinated_xy_camera_transition_v1"].manifest

    assert focused.profile == "FULL"
    assert required_fixture_ids(focused) == ("motion_clear_envelope_v1",)
    rows = build_test_plan_rows(focused)
    assert [row.test_id for row in rows] == [2071]
    assert rows[0].name == "Coordinated XY camera/home transition"
    assert "en" in rows[0].metrics
    assert "hpc" in rows[0].metrics


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
