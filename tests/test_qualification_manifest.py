import json

import pytest

from tools.qualification.manifest import ManifestError, load_manifest, parse_manifest


def test_load_builtin_factory_acceptance_manifest():
    manifest = load_manifest("factory_acceptance_v3")

    assert manifest.manifest_id == "factory_acceptance_v3"
    assert manifest.profile == "FULL"
    assert 1001 in manifest.expected_test_ids
    assert 2006 in manifest.expected_test_ids
    assert 2007 in manifest.expected_test_ids
    assert 2008 in manifest.expected_test_ids
    assert 2201 in manifest.expected_test_ids
    assert 2202 in manifest.expected_test_ids
    assert 2203 in manifest.expected_test_ids
    assert 2401 not in manifest.expected_test_ids
    assert 2402 not in manifest.expected_test_ids
    assert 2403 not in manifest.expected_test_ids
    assert manifest.fixtures
    assert manifest.enforce_expected_test_ids is True
    assert manifest.analysis_rules["2003"]["category"] == "pressure"
    assert manifest.analysis_rules["2201"]["metrics"]["slope_raw_min"]["maturity"] == "candidate"
    assert "2401" not in manifest.analysis_rules
    assert "2402" not in manifest.analysis_rules
    assert "2403" not in manifest.analysis_rules
    assert manifest.analysis_rules["2007"]["metrics"]["x_span"]["maturity"] == "candidate"
    assert manifest.to_report_dict()["schema_version"] == "qualification_manifest_v0"


def test_load_legacy_factory_acceptance_v2_manifest():
    manifest = load_manifest("factory_acceptance_v2")

    assert manifest.manifest_id == "factory_acceptance_v2"
    assert 2203 in manifest.expected_test_ids
    assert 2401 not in manifest.expected_test_ids


def test_load_legacy_factory_acceptance_v1_manifest():
    manifest = load_manifest("factory_acceptance_v1")

    assert manifest.manifest_id == "factory_acceptance_v1"
    assert 2008 in manifest.expected_test_ids
    assert 2201 not in manifest.expected_test_ids


def test_load_legacy_factory_acceptance_v0_manifest():
    manifest = load_manifest("factory_acceptance_v0")

    assert manifest.manifest_id == "factory_acceptance_v0"
    assert 2006 in manifest.expected_test_ids
    assert 2007 not in manifest.expected_test_ids


def test_load_gripper_seal_manifest_requires_local_operator_fixture():
    manifest = load_manifest("gripper_seal_v1")

    assert manifest.manifest_id == "gripper_seal_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2501, 2502, 2503)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--gripper-seal-suite",)
    assert {item["fixture_id"] for item in manifest.fixtures} == {"dummy_blocked_head_v1"}
    assert "slope_raw_min" not in manifest.analysis_rules["2501"]["metrics"]
    assert manifest.analysis_rules["2501"]["metrics"]["pulse_ms"]["equals"] == 2000
    assert manifest.analysis_rules["2501"]["metrics"]["tick_us"]["equals"] == 100
    assert manifest.analysis_rules["2501"]["metrics"]["reg_pause"]["equals"] == 1
    assert manifest.analysis_rules["2502"]["metrics"]["seal_ms"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2502"]["metrics"]["seal_ms"]["min"] == 60000
    assert manifest.analysis_rules["2503"]["metrics"]["repeat_span_raw"]["maturity"] == "acceptance"
    assert manifest.analysis_rules["2503"]["metrics"]["seal_ms_min"]["maturity"] == "acceptance"


def test_load_gripper_seal_stress_manifest_requires_motion_dummy_head_fixture():
    manifest = load_manifest("gripper_seal_stress_v1")

    assert manifest.manifest_id == "gripper_seal_stress_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2510, 2511, 2512, 2513)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--gripper-seal-stress-suite", "--pressure-trace")
    assert {item["fixture_id"] for item in manifest.fixtures} == {"dummy_blocked_head_motion_v1"}
    assert "Firmware homes Z" in manifest.fixtures[0]["operator_note"]
    assert "evaporation-plate confirmation" in manifest.fixtures[0]["operator_note"]
    assert "Z=91500" in manifest.fixtures[0]["operator_note"]
    assert manifest.analysis_rules["2510"]["metrics"]["pulse_ms"]["equals"] == 2000
    assert manifest.analysis_rules["2510"]["metrics"]["pulses"]["min"] == 30
    assert manifest.analysis_rules["2510"]["metrics"]["cond"]["equals"] == 3
    assert manifest.analysis_rules["2510"]["metrics"]["reps"]["equals"] == 5
    assert manifest.analysis_rules["2511"]["metrics"]["refresh_ms"]["equals"] == 30000
    assert manifest.analysis_rules["2512"]["metrics"]["pc"]["equals"] == 1
    assert manifest.analysis_rules["2512"]["metrics"]["pz"]["equals"] == 91500
    assert manifest.analysis_rules["2512"]["metrics"]["z_to"]["equals"] == 0
    assert manifest.analysis_rules["2512"]["metrics"]["z_home_to"]["equals"] == 0
    assert manifest.analysis_rules["2512"]["metrics"]["xy_home_to"]["equals"] == 0
    assert manifest.analysis_rules["2512"]["metrics"]["guard"]["equals"] == 0
    assert "park_x" not in manifest.analysis_rules["2512"]["metrics"]
    assert "park_y" not in manifest.analysis_rules["2512"]["metrics"]
    assert manifest.analysis_rules["2512"]["metrics"]["park_to"]["equals"] == 0
    assert manifest.analysis_rules["2510"]["metrics"]["stride"]["equals"] == 5
    assert manifest.analysis_rules["2510"]["metrics"]["sample_ms"]["equals"] == 25
    assert manifest.analysis_rules["2512"]["metrics"]["stride"]["equals"] == 5
    assert manifest.analysis_rules["2512"]["metrics"]["sample_ms"]["equals"] == 25
    assert manifest.analysis_rules["2512"]["metrics"]["sc"]["min"] == 1
    assert manifest.analysis_rules["2513"]["metrics"]["p_delta"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2513"]["metrics"]["rej_py"]["equals"] == 0


def test_load_xy_motion_manifest_requires_operator_clear_envelope_fixture():
    manifest = load_manifest("xy_motion_v1")

    assert manifest.manifest_id == "xy_motion_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2010, 2011)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--xy-motion-suite",)
    assert {item["fixture_id"] for item in manifest.fixtures} == {"motion_clear_envelope_v1"}
    assert "Firmware homes Z" in manifest.fixtures[0]["operator_note"]
    assert manifest.analysis_rules["2010"]["metrics"]["move_to"]["equals"] == 0
    assert manifest.analysis_rules["2010"]["metrics"]["guard"]["equals"] == 0
    assert manifest.analysis_rules["2010"]["metrics"]["bound"]["equals"] == 0
    assert manifest.analysis_rules["2011"]["metrics"]["ret_err"]["maturity"] == "candidate"


def test_load_motion_envelope_manifest_requires_operator_full_envelope_fixture():
    manifest = load_manifest("motion_envelope_v1")

    assert manifest.manifest_id == "motion_envelope_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2012, 2013, 2014, 2015, 2016)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--motion-envelope-suite",)
    assert {item["fixture_id"] for item in manifest.fixtures} == {"motion_full_envelope_v1"}
    assert "Firmware homes Z" in manifest.fixtures[0]["operator_note"]
    assert "evaporation-plate confirmation" in manifest.fixtures[0]["operator_note"]
    assert "Z=91500" in manifest.fixtures[0]["operator_note"]
    assert manifest.analysis_rules["2012"]["metrics"]["move_to"]["equals"] == 0
    assert manifest.analysis_rules["2012"]["metrics"]["guard"]["equals"] == 0
    assert manifest.analysis_rules["2014"]["metrics"]["pc"]["equals"] == 1
    assert manifest.analysis_rules["2014"]["metrics"]["pz"]["equals"] == 91500
    assert manifest.analysis_rules["2014"]["metrics"]["z_to"]["equals"] == 0
    assert manifest.analysis_rules["2014"]["metrics"]["z_home_to"]["equals"] == 0
    assert manifest.analysis_rules["2014"]["metrics"]["ret_err"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2015"]["metrics"]["zmax"]["equals"] == 80000
    assert manifest.analysis_rules["2015"]["metrics"]["xy_to"]["equals"] == 0
    assert manifest.analysis_rules["2015"]["metrics"]["z_span"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2015"]["metrics"]["guard"]["equals"] == 0
    assert manifest.analysis_rules["2016"]["metrics"]["limit_start"]["equals"] == 0


def test_load_pressure_regulator_manifest_requires_operator_closed_loop_fixture():
    manifest = load_manifest("pressure_regulator_v1")

    assert manifest.manifest_id == "pressure_regulator_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2210, 2211, 2212, 2213, 2214, 2215, 2216, 2217, 2218, 2219)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--pressure-regulator-suite",)
    assert {item["fixture_id"] for item in manifest.fixtures} == {"pressure_closed_loop_v1"}
    assert manifest.analysis_rules["2210"]["metrics"]["p_fault"]["equals"] == 0
    assert manifest.analysis_rules["2211"]["metrics"]["p_n"]["equals"] == 3
    assert manifest.analysis_rules["2211"]["metrics"]["r_home_to"]["equals"] == 0
    assert manifest.analysis_rules["2212"]["metrics"]["slope_raw_min"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2212"]["metrics"]["guard"]["equals"] == 0
    assert manifest.analysis_rules["2212"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2212"]["metrics"]["slew"]["equals"] == 1
    assert manifest.analysis_rules["2212"]["metrics"]["cap_hz"]["equals"] == 16000
    assert manifest.analysis_rules["2214"]["metrics"]["max_jump"]["max"] == 874
    assert manifest.analysis_rules["2214"]["metrics"]["err_max"]["max"] == 4
    assert manifest.analysis_rules["2214"]["metrics"]["low_dn_span"]["max"] == 2000
    assert manifest.analysis_rules["2214"]["metrics"]["high_up_span"]["max"] == 2000
    assert manifest.analysis_rules["2214"]["metrics"]["over"]["maturity"] == "informational"
    assert manifest.analysis_rules["2214"]["metrics"]["under"]["maturity"] == "informational"
    assert manifest.analysis_rules["2215"]["metrics"]["motor_abs_max"]["max"] == 80000
    assert manifest.analysis_rules["2215"]["metrics"]["err_max"]["max"] == 8
    assert manifest.analysis_rules["2216"]["metrics"]["below_span"]["max"] == 2000
    assert manifest.analysis_rules["2216"]["metrics"]["above_span"]["max"] == 2000
    assert manifest.analysis_rules["2216"]["metrics"]["hyst_span"]["maturity"] == "informational"
    assert "max" not in manifest.analysis_rules["2216"]["metrics"]["hyst_span"]
    assert manifest.analysis_rules["2217"]["metrics"]["motor_delta_max"]["max"] == 50000
    assert manifest.analysis_rules["2217"]["metrics"]["err_max"]["max"] == 8
    assert manifest.analysis_rules["2218"]["metrics"]["settle_max_ms"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2218"]["metrics"]["over"]["maturity"] == "informational"
    assert manifest.analysis_rules["2218"]["metrics"]["under"]["maturity"] == "informational"
    assert manifest.analysis_rules["2218"]["metrics"]["err_max"]["max"] == 4
    assert manifest.analysis_rules["2219"]["metrics"]["err_max"]["max"] == 8


def test_load_refuel_vacuum_manifest_requires_operator_dry_fixture():
    manifest = load_manifest("refuel_vacuum_v1")

    assert manifest.manifest_id == "refuel_vacuum_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2220, 2221)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--refuel-vacuum-suite", "--pressure-trace")
    assert {item["fixture_id"] for item in manifest.fixtures} == {"refuel_vacuum_dry_back_v1"}
    assert manifest.analysis_rules["2220"]["metrics"]["shift"]["max"] == 120
    assert manifest.analysis_rules["2220"]["metrics"]["fault"]["equals"] == 0
    assert manifest.analysis_rules["2220"]["metrics"]["trace"]["equals"] == 1
    assert manifest.analysis_rules["2221"]["metrics"]["cyc"]["equals"] == 20
    assert manifest.analysis_rules["2221"]["metrics"]["err"]["max"] == 120
    assert manifest.analysis_rules["2221"]["metrics"]["ma"]["max"] == 80000
    assert manifest.analysis_rules["2221"]["metrics"]["md"]["max"] == 50000


def test_load_valve_characterization_manifest_requires_operator_closed_loop_fixture():
    manifest = load_manifest("valve_characterization_v1")

    assert manifest.manifest_id == "valve_characterization_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2473, 2474, 2475)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--valve-characterization-suite", "--pressure-trace")
    assert {item["fixture_id"] for item in manifest.fixtures} == {"valve_closed_loop_pulse_matrix_v1"}
    assert manifest.analysis_rules["2473"]["metrics"]["timeout"]["equals"] == 0
    assert manifest.analysis_rules["2473"]["metrics"]["ready"]["equals"] == 0
    assert manifest.analysis_rules["2473"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2473"]["metrics"]["rej"]["equals"] == 0
    assert manifest.analysis_rules["2473"]["metrics"]["fresh_to"]["equals"] == 0
    assert manifest.analysis_rules["2473"]["metrics"]["focus"]["equals"] == 1
    assert manifest.analysis_rules["2473"]["metrics"]["mono"]["equals"] == 1
    assert manifest.analysis_rules["2473"]["metrics"]["lat_miss"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["ring_miss"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["excl"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["m15"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["rg15"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["lt15"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["rw"]["maturity"] == "informational"
    assert manifest.analysis_rules["2473"]["metrics"]["sw"]["maturity"] == "informational"
    assert "pk15" not in manifest.analysis_rules["2473"]["metrics"]
    assert "sp15" not in manifest.analysis_rules["2473"]["metrics"]
    assert "slip_w" not in manifest.analysis_rules["2473"]["metrics"]
    assert "gain" not in manifest.analysis_rules["2473"]["metrics"]
    assert manifest.analysis_rules["2475"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2475"]["metrics"]["lat_miss"]["maturity"] == "informational"
    assert manifest.analysis_rules["2475"]["metrics"]["r15"]["maturity"] == "informational"


def test_load_valve_gap_sweep_manifest_requires_operator_closed_loop_fixture():
    manifest = load_manifest("valve_gap_sweep_v1")

    assert manifest.manifest_id == "valve_gap_sweep_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2476, 2477, 2478, 2479)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--valve-gap-sweep-suite", "--pressure-trace")
    assert {item["fixture_id"] for item in manifest.fixtures} == {"valve_closed_loop_pulse_matrix_v1"}
    assert manifest.analysis_rules["2476"]["metrics"]["timeout"]["equals"] == 0
    assert manifest.analysis_rules["2476"]["metrics"]["ready"]["equals"] == 0
    assert manifest.analysis_rules["2476"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2476"]["metrics"]["rej"]["equals"] == 0
    assert manifest.analysis_rules["2476"]["metrics"]["fresh_to"]["equals"] == 0
    assert manifest.analysis_rules["2476"]["metrics"]["focus"]["equals"] == 1
    assert manifest.analysis_rules["2476"]["metrics"]["lat_miss"]["maturity"] == "informational"
    assert manifest.analysis_rules["2476"]["metrics"]["ring_miss"]["maturity"] == "informational"
    assert manifest.analysis_rules["2476"]["metrics"]["g250"]["maturity"] == "informational"
    assert manifest.analysis_rules["2476"]["metrics"]["g5000"]["maturity"] == "informational"
    assert manifest.analysis_rules["2478"]["metrics"]["m30g500"]["maturity"] == "informational"
    assert manifest.analysis_rules["2479"]["metrics"]["m45g2000"]["maturity"] == "informational"


def test_load_manifest_from_path(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "qualification_manifest_v0",
                "manifest_id": "safe_custom",
                "name": "Safe Custom",
                "profile": "SAFE",
                "expected_test_ids": [1001],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(path)

    assert manifest.manifest_id == "safe_custom"
    assert manifest.expected_test_ids == (1001,)


def test_manifest_rejects_missing_required_fields():
    with pytest.raises(ManifestError, match="expected_test_ids"):
        parse_manifest(
            {
                "schema_version": "qualification_manifest_v0",
                "manifest_id": "bad",
                "name": "Bad",
                "profile": "FULL",
            }
        )


def test_manifest_rejects_invalid_profile():
    with pytest.raises(ManifestError, match="SAFE or FULL"):
        parse_manifest(
            {
                "schema_version": "qualification_manifest_v0",
                "manifest_id": "bad",
                "name": "Bad",
                "profile": "HARDWARE",
                "expected_test_ids": [1001],
            }
        )


def test_manifest_rejects_invalid_analysis_rule_maturity():
    with pytest.raises(ManifestError, match="maturity"):
        parse_manifest(
            {
                "schema_version": "qualification_manifest_v0",
                "manifest_id": "bad",
                "name": "Bad",
                "profile": "FULL",
                "expected_test_ids": [1001],
                "analysis_rules": {
                    "1001": {
                        "metrics": {
                            "crc": {"maturity": "strict"},
                        }
                    }
                },
            }
        )
