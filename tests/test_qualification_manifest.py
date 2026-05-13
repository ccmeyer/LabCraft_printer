import json

import pytest

from tools.qualification.manifest import ManifestError, load_manifest, parse_manifest


def test_load_builtin_factory_acceptance_manifest():
    manifest = load_manifest("factory_acceptance_v0")

    assert manifest.manifest_id == "factory_acceptance_v0"
    assert manifest.profile == "FULL"
    assert 1001 in manifest.expected_test_ids
    assert 2006 in manifest.expected_test_ids
    assert manifest.fixtures
    assert manifest.to_report_dict()["schema_version"] == "qualification_manifest_v0"


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
