from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from tools.run_virtual_workflow import main
from tools.virtual_workflows.experiment_design_cases import (
    EXPERIMENT_DESIGN_MATRIX_ID,
)
from tools.virtual_workflows.editor_safeguards import (
    EDITOR_SAFEGUARD_MATRIX_ID,
    EXPECTED_CASE_IDS as EXPECTED_EDITOR_SAFEGUARD_CASES,
)
from tools.virtual_workflows.execution_preflight_safeguards import (
    EXECUTION_PREFLIGHT_MATRIX_ID,
    EXPECTED_CASE_IDS as EXPECTED_EXECUTION_PREFLIGHT_CASES,
)
from tools.virtual_workflows.persistence_safeguards import (
    PERSISTENCE_SAFEGUARD_MATRIX_ID,
    EXPECTED_CASE_IDS as EXPECTED_PERSISTENCE_SAFEGUARD_CASES,
)
from tools.virtual_workflows.matrices import (
    BASE_FIXTURE_PATH,
    CALIBRATION_REQUANTIZATION_MATRIX_ID,
    MATRIX_CASES,
    MATRIX_PLAN_SCHEMA_NAME,
    MIXED_MODE_DEFINITION,
    MIXED_MODE_MATRIX_ID,
    PROFILES,
    REQUANTIZATION_BASE_FIXTURE_PATH,
    REQUANTIZATION_CASES,
    REQUANTIZATION_FILL_STOCK_ID,
    REQUANTIZATION_STOCK_ID,
    TWO_REAGENT_STOCK_IDS,
    MissingFillRequantizationCase,
    TwoReagentIsolationCase,
    RequantizationCountGroup,
    RequantizationCase,
    MatrixDefinition,
    MatrixRegistry,
    MatrixValidationError,
    build_case_fixture,
    catalog_sha256,
    matrix_case_ids,
    matrix_catalog,
    normalized_catalog,
    resolve_matrix_plan,
)


EXPECTED_CATALOG_SHA256 = (
    "d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884"
)
EXPECTED_REPRESENTATIVE_PLAN_SHA256 = (
    "543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f"
)
EXPECTED_REQUANTIZATION_CATALOG_SHA256 = (
    "d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af"
)
EXPECTED_REQUANTIZATION_PLAN_SHA256 = (
    "4f86d140b330646182aed7dcda285ec5d636d6ad875131f33ae2c4b1754410e7"
)
EXPECTED_EXPERIMENT_DESIGN_PREFIX_CATALOG_SHA256 = (
    "49ea5a8bc930035ab239098c3095437acfd8b63764e4b55caeade66f06ae1f9c"
)
EXPECTED_EXPERIMENT_DESIGN_CONTROL_PLAN_SHA256 = (
    "8b700e6acf83afc220246f0cf7e0b59b8dd1f8abff108e6b665ad9de34443d7e"
)
EXPECTED_EDITOR_SAFEGUARD_CATALOG_SHA256 = (
    "18b02f4fbdec0f01ca950ad3b572a7bd99962a6dffcaeca9a9c8c4ddbf37e670"
)
EXPECTED_EXECUTION_PREFLIGHT_CATALOG_SHA256 = (
    "40402ed3ac390b4c642e2328c1ff41d5b9352ad4f602220cb6c95271b767fa75"
)
EXPECTED_PERSISTENCE_SAFEGUARD_CATALOG_SHA256 = (
    "8ce5cad77540dfaba3e1448a9bf35e9ffaf3340010c0c636cee2c7af361f5f13"
)
EXPECTED_REQUANTIZATION_CASE_SHA256 = {
    "droplet_idempotent_10_to_10": "714f1c212bef572de306a7f2b35d47e28c477477467dc36cec4c4acf2ec8d98f",
    "droplet_volume_increase_10_to_9": "f9bc246789292641551a4606bf6bfcff233bdebf741215c10e1e836e9a18bd99",
    "droplet_volume_decrease_10_to_11": "028cc1b70dd6023a40596b0fef21704bddfde8fa95c72406ad8a8b3cfbf5c35d",
    "droplet_multi_target_10_to_9_and_1_to_1": "98912b757f51b31d8246e1c52b78e5b163d4f3ae76ca380b87380318bf485e62",
    "stream_to_droplet_40_to_10_8": "dd066433aa0888bc24bf70479e9ebf3651a428dbb35dc526c0e8441056a846e1",
    "fill_volume_decrease_4_to_5": "793b4f28bbb8ea691d8ed3b595d8a0ee4f100e08bf111b5701f16500ec8a0467",
    "zero_fill_missing_fill_rejected": "8a3336f8cd834276ea24538cae41e96642b4defbc381f9206cc92db002f623b4",
    "two_reagent_second_1_to_2_isolated": "c8d294ebc31d2cef6c81c933ad10023d89a7f96f2ada93ec1681e286cd3f7f54",
}
EXPECTED_GROUPED_PLAN_SHA256 = {
    "droplet_multi_target_10_to_9_and_1_to_1": "9a10fa11b46ee3355815e80f900ea120c65fadafd2879718c91f2be4570ea4b9",
    "stream_to_droplet_40_to_10_8": "d2577b4f6c25cf12d0e2d280624dcccdb19fd03cae9b2d0feb97f5d9d1c70725",
    "fill_volume_decrease_4_to_5": "8ad43c8533415291a41bbdce46b943339ce7aa8680c905dea8516f6ae5a30e24",
    "zero_fill_missing_fill_rejected": "b20a262896745b70e0755afd69a27996bec76289c1e3e0d473c284e2106bcf59",
    "two_reagent_second_1_to_2_isolated": "06264aa348474ab6e81e8f8bb78637655c6b6b83f6d78a74201754bc9990766c",
}


EXPECTED_CASES = (
    "mixed_ab_baseline_pass",
    "mixed_ba_alternate_pass",
    "droplet_pair_ab_alternate",
    "droplet_pair_ba_baseline",
    "stream_pair_ab_baseline_pass",
    "stream_pair_ba_alternate_second_rise",
    "mixed_ab_alternate_fell",
    "mixed_ba_baseline_unclear",
)
EXPECTED_REQUANTIZATION_CASES = (
    "droplet_idempotent_10_to_10",
    "droplet_volume_increase_10_to_9",
    "droplet_volume_decrease_10_to_11",
    "droplet_multi_target_10_to_9_and_1_to_1",
    "stream_to_droplet_40_to_10_8",
    "fill_volume_decrease_4_to_5",
    "zero_fill_missing_fill_rejected",
    "two_reagent_second_1_to_2_isolated",
)


@dataclass(frozen=True)
class _SyntheticCase:
    case_id: str
    expected_label: str

    def normalized(self):
        return {
            "case_id": self.case_id,
            "expected_label": self.expected_label,
        }


class _MalformedCase:
    case_id = "control"

    def normalized(self):
        return {"case_id": "different"}


def _synthetic_definition(tmp_path: Path) -> MatrixDefinition:
    source = tmp_path / "synthetic_reference.json"
    source.write_text("{}", encoding="utf-8")

    def build(case):
        return {
            "fixture_id": f"synthetic__{case.case_id}",
            "expected_label": case.expected_label,
        }, source

    return MatrixDefinition(
        matrix_id="aaa_contract_matrix_v1",
        base_scenario_id="synthetic_base_v1",
        journey_family="synthetic_contract",
        platform="windows_sil",
        execution="manual_on_demand",
        cases=(
            _SyntheticCase("control", "alpha"),
            _SyntheticCase("alternate", "beta"),
        ),
        catalog_metadata={"profiles": [{"profile_id": "synthetic"}]},
        fixture_builder=build,
    )


def test_catalog_freezes_eight_cases_profiles_and_pairwise_coverage():
    assert matrix_case_ids() == EXPECTED_CASES
    entries = {row["id"]: row for row in matrix_catalog()["matrices"]}
    assert entries[MIXED_MODE_MATRIX_ID]["case_count"] == 8
    assert [row["profile_id"] for row in normalized_catalog()["profiles"]] == [
        "alternate",
        "baseline",
    ]
    assert {
        (case.mode_family, case.stock_order) for case in MATRIX_CASES
    } == {
        (family, order)
        for family in ("mixed", "droplet_pair", "stream_pair")
        for order in (("A", "B"), ("B", "A"))
    }
    assert {
        item.operator_judgment
        for case in MATRIX_CASES
        for item in case.refuel_outcomes
    } == {"stable", "level_rose", "level_fell", "unclear"}


def test_requantization_catalog_freezes_exact_boundary_oracles_and_hashes():
    assert matrix_case_ids(CALIBRATION_REQUANTIZATION_MATRIX_ID) == (
        EXPECTED_REQUANTIZATION_CASES
    )
    assert [
        (
            case.prepared_volume_nL,
            case.calibrated_volume_nL,
            case.design_printed_volume_nL,
            case.expected_prepared_droplets,
            case.expected_requantized_droplets,
            (case.margin_numerator, case.margin_denominator),
        )
        for case in REQUANTIZATION_CASES[:3]
    ] == [
        (9.0, 9.0, 90.0, 10, 10, (1, 2)),
        (8.0, 9.0, 80.0, 10, 9, (7, 18)),
        (10.0, 9.0, 100.0, 10, 11, (7, 18)),
    ]
    grouped = [case.normalized() for case in REQUANTIZATION_CASES[3:6]]
    assert [case["case_id"] for case in grouped] == list(
        EXPECTED_REQUANTIZATION_CASES[3:6]
    )
    assert [case["case_kind"] for case in grouped] == [
        "composite_requantization"
    ] * 3
    assert [
        build_case_fixture(
            CALIBRATION_REQUANTIZATION_MATRIX_ID, case["case_id"]
        )[0]["lifecycle"]["dispense_count_oracle"]["schema_version"]
        for case in grouped
    ] == [2, 2, 2]
    assert [case["expected_completion_count"] for case in grouped] == [36, 48, 48]
    assert [case["require_terminal_reload"] for case in grouped] == [False, True, False]
    missing_fill = REQUANTIZATION_CASES[6]
    isolation = REQUANTIZATION_CASES[7]
    assert isinstance(missing_fill, MissingFillRequantizationCase)
    assert missing_fill.expected_terminal == "calibration_apply_rejected"
    assert missing_fill.expected_hypothetical_reagent_droplets == 0
    assert missing_fill.expected_missing_fill_droplets == 1
    assert isinstance(isolation, TwoReagentIsolationCase)
    assert isolation.stock_ids == TWO_REAGENT_STOCK_IDS
    assert isolation.first_pass_completion_count == 24
    assert isolation.expected_total_droplets == 72
    missing_fixture = build_case_fixture(
        CALIBRATION_REQUANTIZATION_MATRIX_ID, missing_fill.case_id
    )[0]
    assert missing_fixture["lifecycle"]["calibration_rejection_oracle"][
        "expected_intent_count"
    ] == 0
    isolation_fixture = build_case_fixture(
        CALIBRATION_REQUANTIZATION_MATRIX_ID, isolation.case_id
    )[0]
    assert isolation_fixture["lifecycle"]["dispense_count_oracle"][
        "schema_version"
    ] == 2
    assert isolation_fixture["lifecycle"]["two_reagent_isolation_oracle"][
        "expected_total_droplets"
    ] == 72
    assert catalog_sha256(
        CALIBRATION_REQUANTIZATION_MATRIX_ID
    ) == EXPECTED_REQUANTIZATION_CATALOG_SHA256
    observed_case_hashes = {
        row["case"]["case_id"]: row["case_sha256"]
        for row in resolve_matrix_plan(
            CALIBRATION_REQUANTIZATION_MATRIX_ID,
            seed=7,
            timeout_seconds=12,
            execution_authorized=False,
        )["cases"]
    }
    assert observed_case_hashes == EXPECTED_REQUANTIZATION_CASE_SHA256
    plan = resolve_matrix_plan(
        CALIBRATION_REQUANTIZATION_MATRIX_ID,
        case_id="droplet_idempotent_10_to_10",
        seed=7,
        timeout_seconds=12,
        execution_authorized=False,
    )
    assert hashlib.sha256(
        json.dumps(
            plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest() == EXPECTED_REQUANTIZATION_PLAN_SHA256
    for case_id, expected_hash in EXPECTED_GROUPED_PLAN_SHA256.items():
        grouped_plan = resolve_matrix_plan(
            CALIBRATION_REQUANTIZATION_MATRIX_ID,
            case_id=case_id,
            seed=7,
            timeout_seconds=12,
            execution_authorized=False,
        )
        assert hashlib.sha256(
            json.dumps(
                grouped_plan,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest() == expected_hash


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"margin_numerator": 1, "margin_denominator": 4}, "margin drifted"),
        (
            {"design_printed_volume_nL": 78.75, "margin_numerator": 1,
             "margin_denominator": 4},
            "margin is too small",
        ),
        ({"design_printed_volume_nL": 84.0}, "rounding interval"),
        ({"expected_requantized_droplets": 10}, "count direction drifted"),
        ({"calibrated_volume_nL": 9.1}, "frozen response"),
        ({"prepared_volume_nL": 9.0}, "volume direction drifted"),
    ],
)
def test_requantization_case_rejects_drift(changes, message):
    with pytest.raises(MatrixValidationError, match=message):
        replace(REQUANTIZATION_CASES[1], **changes)


def test_composite_requantization_rejects_group_and_transition_drift():
    case = REQUANTIZATION_CASES[3]
    first = case.count_groups[0]
    with pytest.raises(MatrixValidationError, match="overlap"):
        replace(case, count_groups=(*case.count_groups, first))
    with pytest.raises(MatrixValidationError, match="margin is too small"):
        replace(first, margin_numerator=1, margin_denominator=4)
    with pytest.raises(MatrixValidationError, match="count oracle drifted"):
        replace(
            case,
            count_groups=(
                replace(first, requantized_droplets=2),
                *case.count_groups[1:],
            ),
        )
    with pytest.raises(MatrixValidationError, match="preview projection"):
        replace(
            case,
            count_groups=(
                replace(first, preview_row=1),
                *case.count_groups[1:],
            ),
        )
    with pytest.raises(MatrixValidationError, match="primary transition"):
        replace(
            case,
            calibration_steps=(
                replace(case.calibration_steps[0], primary=False),
                replace(case.calibration_steps[1], primary=True),
            ),
        )


def test_composite_requantization_requires_exact_stock_well_membership():
    case = REQUANTIZATION_CASES[5]
    fill = case.count_groups[1]
    with pytest.raises(MatrixValidationError, match="incomplete"):
        replace(
            case,
            count_groups=(
                case.count_groups[0],
                replace(fill, well_ids=fill.well_ids[:-1]),
            ),
        )
    with pytest.raises(MatrixValidationError, match="stock is invalid"):
        RequantizationCountGroup(
            stock_id=f"{REQUANTIZATION_FILL_STOCK_ID}-wrong",
            well_ids=("A1",),
            prepared_droplets=1,
            requantized_droplets=1,
            rounding_rule="nearest_integer",
            margin_numerator=1,
            margin_denominator=2,
        )


def test_missing_fill_requantization_rejects_oracle_and_profile_drift():
    case = REQUANTIZATION_CASES[6]
    with pytest.raises(MatrixValidationError, match="count oracle drifted"):
        replace(case, expected_missing_fill_droplets=0)
    with pytest.raises(MatrixValidationError, match="reagent margin drifted"):
        replace(case, reagent_margin_numerator=1, reagent_margin_denominator=3)
    with pytest.raises(MatrixValidationError, match="profiles drifted"):
        replace(case, rejected_profile_id="nominal_stream")
    with pytest.raises(MatrixValidationError, match="warning contract drifted"):
        replace(case, expected_warning_fragment="different warning")


def test_two_reagent_isolation_rejects_membership_and_count_drift():
    case = REQUANTIZATION_CASES[7]
    with pytest.raises(MatrixValidationError, match="primary stock drifted"):
        replace(case, primary_stock_id=case.stock_ids[0])
    with pytest.raises(MatrixValidationError, match="count groups are incomplete"):
        replace(case, count_groups=case.count_groups[:-1])
    with pytest.raises(MatrixValidationError, match="count oracle drifted"):
        replace(
            case,
            count_groups=(
                case.count_groups[0],
                replace(case.count_groups[1], requantized_droplets=1),
            ),
        )
    with pytest.raises(MatrixValidationError, match="total droplet count drifted"):
        replace(case, expected_total_droplets=71)


def test_profiles_freeze_calibration_and_trial_values():
    baseline = PROFILES["baseline"].normalized()
    alternate = PROFILES["alternate"].normalized()

    assert baseline["droplet"] == {"pulse_width_us": 1300, "volume_nL": 9.0}
    assert baseline["stream"]["volume_nL"] == 60.0
    assert baseline["manual_refuel"] == {
        "trial_count": 2,
        "trial_droplet_count": 5,
    }
    assert alternate["droplet"] == {
        "pulse_width_us": 1550,
        "volume_nL": 13.5,
    }
    assert alternate["stream"]["volume_nL"] == 98.0
    assert alternate["manual_refuel"] == {
        "trial_count": 3,
        "trial_droplet_count": 10,
    }


def test_plan_is_deterministic_hashed_and_supports_one_case():
    plan = resolve_matrix_plan(
        MIXED_MODE_MATRIX_ID,
        case_id="mixed_ab_baseline_pass",
        seed=7,
        timeout_seconds=12,
        execution_authorized=False,
    )

    assert plan["schema_name"] == MATRIX_PLAN_SCHEMA_NAME
    assert plan["execution_authorized"] is False
    assert plan["case_count"] == 1
    assert plan["seed"] == 7
    assert plan["matrix"]["catalog_sha256"] == catalog_sha256()
    case = plan["cases"][0]
    expected = hashlib.sha256(
        json.dumps(
            case["case"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert case["case_sha256"] == expected
    assert resolve_matrix_plan(
        MIXED_MODE_MATRIX_ID,
        case_id="mixed_ab_baseline_pass",
        seed=7,
        timeout_seconds=12,
        execution_authorized=False,
    ) == plan
    assert catalog_sha256() == EXPECTED_CATALOG_SHA256
    assert hashlib.sha256(
        json.dumps(
            plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest() == EXPECTED_REPRESENTATIVE_PLAN_SHA256


def test_registry_supports_multiple_sorted_independent_definitions(tmp_path):
    synthetic = _synthetic_definition(tmp_path)
    registry = MatrixRegistry((MIXED_MODE_DEFINITION, synthetic))

    assert registry.registered_ids() == (
        "aaa_contract_matrix_v1",
        MIXED_MODE_MATRIX_ID,
    )
    assert [row["id"] for row in registry.operator_catalog()["matrices"]] == [
        "aaa_contract_matrix_v1",
        MIXED_MODE_MATRIX_ID,
    ]
    plan = registry.resolve_plan(
        synthetic.matrix_id,
        case_id="alternate",
        seed=13,
        timeout_seconds=4,
        execution_authorized=False,
    )
    assert plan["matrix"] == {
        "id": synthetic.matrix_id,
        "catalog_sha256": synthetic.catalog_sha256(),
        "base_scenario_id": synthetic.base_scenario_id,
    }
    assert plan["cases"][0]["case"] == {
        "case_id": "alternate",
        "expected_label": "beta",
    }
    assert synthetic.catalog_sha256() != EXPECTED_CATALOG_SHA256
    fixture, source = registry.build_case_fixture(
        synthetic.matrix_id, "alternate"
    )
    assert fixture == {
        "fixture_id": "synthetic__alternate",
        "expected_label": "beta",
    }
    assert source == tmp_path / "synthetic_reference.json"


def test_registry_rejects_duplicate_and_malformed_definitions(tmp_path):
    synthetic = _synthetic_definition(tmp_path)
    with pytest.raises(MatrixValidationError, match="only MatrixDefinition"):
        MatrixRegistry((object(),))
    with pytest.raises(MatrixValidationError, match="duplicate matrix IDs"):
        MatrixRegistry((synthetic, synthetic))
    with pytest.raises(MatrixValidationError, match="duplicate case IDs"):
        MatrixDefinition(
            matrix_id="duplicate_cases_v1",
            base_scenario_id="synthetic_base_v1",
            journey_family="synthetic_contract",
            platform="windows_sil",
            execution="manual_on_demand",
            cases=(
                _SyntheticCase("same", "alpha"),
                _SyntheticCase("same", "beta"),
            ),
            catalog_metadata={},
            fixture_builder=synthetic.fixture_builder,
        )
    with pytest.raises(MatrixValidationError, match="reserved keys"):
        MatrixDefinition(
            matrix_id="reserved_metadata_v1",
            base_scenario_id="synthetic_base_v1",
            journey_family="synthetic_contract",
            platform="windows_sil",
            execution="manual_on_demand",
            cases=(_SyntheticCase("control", "alpha"),),
            catalog_metadata={"cases": []},
            fixture_builder=synthetic.fixture_builder,
        )
    with pytest.raises(MatrixValidationError, match="normalized identity drifted"):
        MatrixDefinition(
            matrix_id="malformed_case_v1",
            base_scenario_id="synthetic_base_v1",
            journey_family="synthetic_contract",
            platform="windows_sil",
            execution="manual_on_demand",
            cases=(_MalformedCase(),),
            catalog_metadata={},
            fixture_builder=synthetic.fixture_builder,
        )


def test_case_fixture_is_in_memory_and_preserves_reference_fixture(tmp_path):
    before = BASE_FIXTURE_PATH.read_bytes()
    fixture, source = build_case_fixture(
        MIXED_MODE_MATRIX_ID, "mixed_ba_alternate_pass"
    )

    assert source == BASE_FIXTURE_PATH
    assert BASE_FIXTURE_PATH.read_bytes() == before
    assert not tuple(tmp_path.iterdir())
    assert fixture["workload"]["completion_count"] == 48
    assert [stock["matrix_stock_key"] for stock in fixture["stocks"]] == ["B", "A"]
    assert [stock["printing_mode"] for stock in fixture["stocks"]] == [
        "stream",
        "droplet",
    ]
    assert sum(stock["target_concentration"] for stock in fixture["stocks"]) == pytest.approx(23.0)
    assert fixture["lifecycle"]["case_sha256"] == resolve_matrix_plan(
        MIXED_MODE_MATRIX_ID, case_id="mixed_ba_alternate_pass"
    )["cases"][0]["case_sha256"]


def test_requantization_fixture_is_in_memory_one_stock_and_catalog_owned():
    before = REQUANTIZATION_BASE_FIXTURE_PATH.read_bytes()
    fixture, source = build_case_fixture(
        CALIBRATION_REQUANTIZATION_MATRIX_ID,
        "droplet_volume_increase_10_to_9",
    )

    assert source == REQUANTIZATION_BASE_FIXTURE_PATH
    assert REQUANTIZATION_BASE_FIXTURE_PATH.read_bytes() == before
    assert fixture["workload"] == {
        "target_dispenses_per_stock_per_well": 9,
        "well_count": 24,
        "stock_count": 1,
        "array_passes": 1,
        "completion_count": 24,
    }
    stock = fixture["stocks"][0]
    assert (
        f"{stock['factor_name']}_{stock['concentration']:.2f}_{stock['units']}"
        == REQUANTIZATION_STOCK_ID
    )
    assert fixture["lifecycle"]["design"] == {
        "printed_volume_nL": 80.0,
        "final_volume_nL": 80.0,
    }
    assert fixture["lifecycle"]["dispense_count_oracle"][
        "requantized_droplets_per_well"
    ] == 9


def test_unknown_matrix_and_case_fail_closed():
    with pytest.raises(MatrixValidationError, match="unsupported matrix"):
        resolve_matrix_plan("unknown")
    with pytest.raises(MatrixValidationError, match="unsupported matrix case"):
        build_case_fixture(MIXED_MODE_MATRIX_ID, "unknown")


def test_cli_lists_and_dry_runs_matrices_without_execution(capsys):
    assert main(["--list", "matrices"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in catalog["matrices"]] == [
        PERSISTENCE_SAFEGUARD_MATRIX_ID,
        CALIBRATION_REQUANTIZATION_MATRIX_ID,
        EDITOR_SAFEGUARD_MATRIX_ID,
        EXECUTION_PREFLIGHT_MATRIX_ID,
        EXPERIMENT_DESIGN_MATRIX_ID,
        MIXED_MODE_MATRIX_ID,
    ]
    entries = {row["id"]: row for row in catalog["matrices"]}
    assert entries[MIXED_MODE_MATRIX_ID]["case_ids"] == list(EXPECTED_CASES)
    assert entries[CALIBRATION_REQUANTIZATION_MATRIX_ID]["case_ids"] == list(
        EXPECTED_REQUANTIZATION_CASES
    )
    assert entries[EXPERIMENT_DESIGN_MATRIX_ID]["case_ids"] == [
        "single_reagent_control",
        "multi_reagent_seed_4321",
        "one_stock_feasible",
        "two_stock_required",
        "custom_wells_with_exclusions",
        "multi_reagent_seed_1234",
        "exact_custom_capacity",
        "capacity_plus_one_rejected",
        "fixed_stock_exceeds_max_rejected",
    ]
    assert entries[EXPERIMENT_DESIGN_MATRIX_ID]["catalog_sha256"] == (
        EXPECTED_EXPERIMENT_DESIGN_PREFIX_CATALOG_SHA256
    )
    assert entries[EDITOR_SAFEGUARD_MATRIX_ID]["case_ids"] == list(
        EXPECTED_EDITOR_SAFEGUARD_CASES
    )
    assert entries[EDITOR_SAFEGUARD_MATRIX_ID]["catalog_sha256"] == (
        EXPECTED_EDITOR_SAFEGUARD_CATALOG_SHA256
    )
    assert entries[EXECUTION_PREFLIGHT_MATRIX_ID]["case_ids"] == list(
        EXPECTED_EXECUTION_PREFLIGHT_CASES
    )
    assert entries[EXECUTION_PREFLIGHT_MATRIX_ID]["catalog_sha256"] == (
        EXPECTED_EXECUTION_PREFLIGHT_CATALOG_SHA256
    )
    assert entries[PERSISTENCE_SAFEGUARD_MATRIX_ID]["case_ids"] == list(
        EXPECTED_PERSISTENCE_SAFEGUARD_CASES
    )
    assert entries[PERSISTENCE_SAFEGUARD_MATRIX_ID]["catalog_sha256"] == (
        EXPECTED_PERSISTENCE_SAFEGUARD_CATALOG_SHA256
    )

    design_plan = resolve_matrix_plan(
        EXPERIMENT_DESIGN_MATRIX_ID,
        case_id="single_reagent_control",
        seed=7,
        timeout_seconds=12,
        execution_authorized=False,
    )
    assert hashlib.sha256(
        json.dumps(
            design_plan,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest() == EXPECTED_EXPERIMENT_DESIGN_CONTROL_PLAN_SHA256

    assert main(
        [
            "--matrix",
            MIXED_MODE_MATRIX_ID,
            "--case",
            "mixed_ab_baseline_pass",
            "--seed",
            "9",
            "--timeout-seconds",
            "17",
            "--dry-run",
        ]
    ) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["execution_authorized"] is False
    assert plan["seed"] == 9
    assert plan["timeout_seconds"] == 17.0
    assert plan["cases"][0]["case"]["case_id"] == "mixed_ab_baseline_pass"
