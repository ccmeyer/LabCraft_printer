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
    assert 2401 in manifest.expected_test_ids
    assert 2402 in manifest.expected_test_ids
    assert 2403 in manifest.expected_test_ids
    assert manifest.fixtures
    assert manifest.enforce_expected_test_ids is True
    assert manifest.analysis_rules["2003"]["category"] == "pressure"
    assert manifest.analysis_rules["2201"]["metrics"]["slope_raw_min"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2401"]["metrics"]["cv_pct"]["maturity"] == "candidate"
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


def test_load_xy_motion_manifest_requires_operator_clear_envelope_fixture():
    manifest = load_manifest("xy_motion_v1")

    assert manifest.manifest_id == "xy_motion_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == (2010, 2011)
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--xy-motion-suite",)
    assert {item["fixture_id"] for item in manifest.fixtures} == {"motion_clear_envelope_v1"}
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
    assert manifest.analysis_rules["2012"]["metrics"]["move_to"]["equals"] == 0
    assert manifest.analysis_rules["2012"]["metrics"]["guard"]["equals"] == 0
    assert manifest.analysis_rules["2014"]["metrics"]["ret_err"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2015"]["metrics"]["z_span"]["maturity"] == "candidate"
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


def test_load_valve_characterization_manifest_requires_operator_closed_loop_fixture():
    manifest = load_manifest("valve_characterization_v1")

    assert manifest.manifest_id == "valve_characterization_v1"
    assert manifest.profile == "FULL"
    assert manifest.expected_test_ids == tuple(range(2460, 2473))
    assert manifest.enforce_expected_test_ids is True
    assert manifest.requires_operator_prompts is True
    assert manifest.selftest_args == ("--valve-characterization-suite",)
    assert {item["fixture_id"] for item in manifest.fixtures} == {"valve_closed_loop_pulse_matrix_v1"}
    assert manifest.analysis_rules["2460"]["metrics"]["timeout"]["equals"] == 0
    assert manifest.analysis_rules["2460"]["metrics"]["ready"]["equals"] == 0
    assert manifest.analysis_rules["2460"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2460"]["metrics"]["m15"]["maturity"] == "informational"
    assert manifest.analysis_rules["2466"]["metrics"]["slip_w"]["max"] == 250
    assert manifest.analysis_rules["2466"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2472"]["metrics"]["home_to"]["equals"] == 0
    assert manifest.analysis_rules["2472"]["metrics"]["ratio"]["maturity"] == "informational"


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
