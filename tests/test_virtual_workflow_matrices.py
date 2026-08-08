from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from tools.run_virtual_workflow import main
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
    REQUANTIZATION_STOCK_ID,
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
    "d36330cddd7f3e168c2802314371837d96c9d4393021c338d487ff27e0c8ada8"
)
EXPECTED_REQUANTIZATION_PLAN_SHA256 = (
    "54bc74e13e9eb82b84105d0cc94cf3472b693b7969fffb4908db5e7d837dec98"
)


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
        for case in REQUANTIZATION_CASES
    ] == [
        (9.0, 9.0, 90.0, 10, 10, (1, 2)),
        (8.0, 9.0, 80.0, 10, 9, (7, 18)),
        (10.0, 9.0, 100.0, 10, 11, (7, 18)),
    ]
    assert catalog_sha256(
        CALIBRATION_REQUANTIZATION_MATRIX_ID
    ) == EXPECTED_REQUANTIZATION_CATALOG_SHA256
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
        CALIBRATION_REQUANTIZATION_MATRIX_ID,
        MIXED_MODE_MATRIX_ID,
    ]
    entries = {row["id"]: row for row in catalog["matrices"]}
    assert entries[MIXED_MODE_MATRIX_ID]["case_ids"] == list(EXPECTED_CASES)
    assert entries[CALIBRATION_REQUANTIZATION_MATRIX_ID]["case_ids"] == list(
        EXPECTED_REQUANTIZATION_CASES
    )

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
