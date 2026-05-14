import json

import pytest

from tools.qualification.manifest import ManifestError, load_manifest, parse_manifest


def test_load_builtin_factory_acceptance_manifest():
    manifest = load_manifest("factory_acceptance_v1")

    assert manifest.manifest_id == "factory_acceptance_v1"
    assert manifest.profile == "FULL"
    assert 1001 in manifest.expected_test_ids
    assert 2006 in manifest.expected_test_ids
    assert 2007 in manifest.expected_test_ids
    assert 2008 in manifest.expected_test_ids
    assert manifest.fixtures
    assert manifest.enforce_expected_test_ids is True
    assert manifest.analysis_rules["2003"]["category"] == "pressure"
    assert manifest.analysis_rules["2007"]["metrics"]["x_span"]["maturity"] == "candidate"
    assert manifest.to_report_dict()["schema_version"] == "qualification_manifest_v0"


def test_load_legacy_factory_acceptance_v0_manifest():
    manifest = load_manifest("factory_acceptance_v0")

    assert manifest.manifest_id == "factory_acceptance_v0"
    assert 2006 in manifest.expected_test_ids
    assert 2007 not in manifest.expected_test_ids


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
