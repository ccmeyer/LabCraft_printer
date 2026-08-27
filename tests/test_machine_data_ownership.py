import json

import pytest

import MachineDataOwnership


def _write_catalog(path, rules):
    path.write_text(
        json.dumps(
            {
                "schema_name": MachineDataOwnership.OWNERSHIP_SCHEMA_NAME,
                "schema_version": MachineDataOwnership.OWNERSHIP_SCHEMA_VERSION,
                "rules": rules,
            }
        ),
        encoding="utf-8",
    )


def test_default_policy_classifies_updater_logs_and_blocks_unknown_paths():
    policy = MachineDataOwnership.MachineDataOwnershipPolicy.load()

    updater_log = policy.classify("update_logs/latest_update_result.json")
    legacy_bundle = policy.classify("labcraftupdates/nested/v1.3.0-rc.11.bundle")
    unknown = policy.classify("mystery/camera_override.json")

    assert updater_log.classification is MachineDataOwnership.OwnershipClassification.ARCHIVE_ONLY
    assert updater_log.activation_allowed is True
    assert updater_log.rule_id == "legacy-update-logs-v1"
    assert legacy_bundle.classification is MachineDataOwnership.OwnershipClassification.ARCHIVE_ONLY
    assert legacy_bundle.activation_allowed is True
    assert legacy_bundle.rule_id == "legacy-offline-update-bundles-v1"
    assert unknown.classification is MachineDataOwnership.OwnershipClassification.UNCLASSIFIED
    assert unknown.activation_allowed is False


@pytest.mark.parametrize("path", ["../escape", "/absolute", "", "."])
def test_ownership_paths_reject_escape_or_broad_values(path):
    policy = MachineDataOwnership.MachineDataOwnershipPolicy.load()
    with pytest.raises(MachineDataOwnership.OwnershipPolicyError):
        policy.classify(path)


def test_policy_rejects_overlapping_rules(tmp_path):
    catalog = tmp_path / "ownership.json"
    _write_catalog(
        catalog,
        [
            {
                "rule_id": "prefix",
                "match_kind": "prefix",
                "pattern": "logs/",
                "classification": "archive_only",
                "reason": "reviewed logs",
            },
            {
                "rule_id": "exact",
                "match_kind": "exact",
                "pattern": "logs/machine.json",
                "classification": "prohibited",
                "reason": "would overlap",
            },
        ],
    )
    with pytest.raises(MachineDataOwnership.OwnershipPolicyError, match="overlap"):
        MachineDataOwnership.MachineDataOwnershipPolicy.load(catalog)


def test_canonical_rule_requires_destination(tmp_path):
    catalog = tmp_path / "ownership.json"
    _write_catalog(
        catalog,
        [
            {
                "rule_id": "bad",
                "match_kind": "exact",
                "pattern": "machine.json",
                "classification": "canonical",
                "reason": "missing destination",
            }
        ],
    )
    with pytest.raises(MachineDataOwnership.OwnershipPolicyError, match="destination"):
        MachineDataOwnership.MachineDataOwnershipPolicy.load(catalog)
