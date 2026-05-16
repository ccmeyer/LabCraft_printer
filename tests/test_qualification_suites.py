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
        "xy_motion_v1",
        "motion_envelope_v1",
        "pressure_regulator_v1",
    }.issubset(manifest_ids)
    assert entries[0].manifest_id == "factory_acceptance_v3"
    assert [entry.manifest_id for entry in entries[:5]] == [
        "factory_acceptance_v3",
        "gripper_seal_v1",
        "xy_motion_v1",
        "motion_envelope_v1",
        "pressure_regulator_v1",
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
    assert "max_jump" in rows[2215].metrics
    assert "cap_hz" in rows[2215].metrics
    assert "adjacent 1 psi target steps" in rows[2214].evaluates
    assert "production setpoint slew" in rows[2214].evaluates
    assert "settle_max_ms" in rows[2218].metrics
    assert "1, 2, 3, 2, 1 psi" in rows[2218].evaluates
