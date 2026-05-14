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
    assert manifest.analysis_rules["2502"]["metrics"]["seal_ms"]["maturity"] == "candidate"
    assert manifest.analysis_rules["2502"]["metrics"]["seal_ms"]["min"] == 60000


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
