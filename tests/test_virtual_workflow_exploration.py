from __future__ import annotations

import hashlib
import json

import pytest

from tools.run_virtual_workflow import main

from tools.virtual_workflows.exploration import (
    CAMPAIGN_ID,
    EXPLORATION_PLAN_SCHEMA_NAME,
    FIXED_SEEDS,
    MAX_ACTIONS,
    SEQUENCES,
    ExplorationValidationError,
    build_sequence_fixture,
    catalog_sha256,
    exploration_catalog,
    generate_sequence,
    get_sequence,
    resolve_exploration_plan,
    sequence_ids,
)


EXPECTED_SHAPES = [
    (1, False, 1),
    (7, True, 1),
    (19, False, 1),
    (42, False, 1),
    (101, False, 2),
]


def test_generator_freezes_seed_shapes_classes_and_order():
    assert FIXED_SEEDS == (1, 7, 19, 42, 101)
    assert [
        (seed, get_sequence(CAMPAIGN_ID, f"seed_{seed}_legal").rename_first,
         get_sequence(CAMPAIGN_ID, f"seed_{seed}_legal").edit_cycles)
        for seed in FIXED_SEEDS
    ] == EXPECTED_SHAPES
    assert sequence_ids() == tuple(
        f"seed_{seed}_{kind}"
        for seed in FIXED_SEEDS
        for kind in ("legal", "illegal")
    )
    assert len(SEQUENCES) == 10


def test_illegal_sequences_insert_one_rejection_and_recover():
    for seed in FIXED_SEEDS:
        legal = generate_sequence(seed, "legal")
        illegal = generate_sequence(seed, "illegal")
        rejected = [
            row for row in illegal.normalized()["steps"]
            if row["expected_outcome"] == "rejected_invalid"
        ]
        assert len(rejected) == 1
        assert rejected[0]["action_id"] == "editor.refinalize_prepared_via_ui"
        assert "dirty" in rejected[0]["from_state"]
        assert rejected[0]["from_state"] == rejected[0]["to_state"]
        recovery = illegal.normalized()["steps"][
            rejected[0]["ordinal"]
        ]
        assert recovery["action_id"] == "editor.edit_prepared_design_via_ui"
        assert recovery["edit_variant"] in {"intermediate_recovery", "final"}
        assert legal.steps[-1].to_state == "prepared_reloaded_inactive"
        assert illegal.steps[-1].to_state == "prepared_reloaded_inactive"
        assert len(illegal.steps) <= MAX_ACTIONS


def test_catalog_and_plan_are_canonical_and_hash_identified():
    catalog = exploration_catalog()
    assert catalog["campaigns"][0]["sequence_count"] == 10
    assert catalog["campaigns"][0]["catalog_sha256"] == catalog_sha256()
    plan = resolve_exploration_plan(
        CAMPAIGN_ID,
        sequence_id="seed_101_illegal",
        timeout_seconds=17,
        execution_authorized=False,
    )
    assert plan["schema_name"] == EXPLORATION_PLAN_SCHEMA_NAME
    assert plan["execution_authorized"] is False
    assert plan["sequence_count"] == 1
    row = plan["sequences"][0]
    expected = hashlib.sha256(
        json.dumps(
            row["sequence"], sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert row["sequence_sha256"] == expected
    assert row["sequence"]["edit_cycles"] == 2


def test_sequence_fixture_is_derived_in_memory_from_tracked_reference():
    fixture, source = build_sequence_fixture(CAMPAIGN_ID, "seed_7_legal")
    assert source.name == "experiment_editor_prestart_rename_refinalize_v1.json"
    assert fixture["experiment"]["initial_name"] == "sil-editor-prestart-rename-v1"
    assert fixture["exploration"]["sequence"]["rename_first"] is True
    assert fixture["exploration"]["intermediate_printed_volume_tolerance_nL"] == 1.0
    assert fixture["workload"]["completion_count"] == 2


def test_unknown_campaign_and_sequence_fail_closed():
    with pytest.raises(ExplorationValidationError, match="unsupported campaign"):
        resolve_exploration_plan("unknown")
    with pytest.raises(ExplorationValidationError, match="unsupported sequence"):
        build_sequence_fixture(CAMPAIGN_ID, "unknown")


def test_cli_dry_run_derives_selected_seed_and_rejects_campaign_override(capsys):
    assert main([
        "--exploration", CAMPAIGN_ID,
        "--sequence", "seed_7_legal",
        "--dry-run",
    ]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["sequences"][0]["sequence"]["seed"] == 7

    with pytest.raises(SystemExit) as exc_info:
        main(["--exploration", CAMPAIGN_ID, "--seed", "7", "--dry-run"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        main([
            "--exploration", CAMPAIGN_ID,
            "--sequence", "seed_7_legal",
            "--seed", "1",
            "--dry-run",
        ])
    assert exc_info.value.code == 2
