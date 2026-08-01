import ast
import json
import math
from pathlib import Path
import random

import pytest

from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import _summary_row_fingerprint
from Model import validate_ejection_volume_for_mode
from tools.sil.synthetic_calibration import (
    CALIBRATION_REQUEST_SCHEMA_ID,
    CALIBRATION_RESULT_SCHEMA_ID,
    CALIBRATION_SCHEMA_VERSION,
    SYNTHETIC_CALIBRATION_PROVIDER_VERSION,
    CalibrationApplicationError,
    CalibrationContractError,
    CalibrationGenerationRequestV1,
    CalibrationGenerationResultV1,
    SyntheticCalibrationProvider,
)


PROFILE_IDS = (
    "nominal_droplet",
    "nominal_stream",
    "droplet_to_stream",
    "low_volume_boundary",
    "high_volume_boundary",
    "invalid_outlier",
    "missing_measurement",
)


def _request(profile_id="nominal_droplet", *, seed=1729, **overrides):
    defaults = {
        "seed": seed,
        "profile_id": profile_id,
        "virtual_run_id": "virtual-run-001",
        "printer_head_id": "virtual-head-A",
        "stock_id": "virtual-stock-1",
        "factor_name": "Protein",
        "option_name": "High",
        "is_fill": False,
        "requested_mode": "droplet",
        "nominal_volume_nL": 10.0,
        "volume_variation_fraction": 0.1,
        "pressure_bounds_psi": (0.8, 2.2),
        "pulse_width_bounds_us": (1200, 1800),
    }
    profile_overrides = {
        "nominal_stream": {
            "requested_mode": "stream",
            "nominal_volume_nL": 60.0,
        },
        "droplet_to_stream": {
            "requested_mode": "droplet",
            "nominal_volume_nL": 60.0,
        },
        "low_volume_boundary": {
            "nominal_volume_nL": 1.0,
            "volume_variation_fraction": 0.0,
        },
        "high_volume_boundary": {
            "requested_mode": "stream",
            "nominal_volume_nL": 250.0,
            "volume_variation_fraction": 0.0,
        },
    }
    defaults.update(profile_overrides.get(profile_id, {}))
    defaults.update(overrides)
    return CalibrationGenerationRequestV1(**defaults)


class _ExistingSummaryContract:
    """Minimal host for the application's existing normalization methods."""

    _format_pressure_sweep_summary_timestamp = staticmethod(
        CalibrationManager._format_pressure_sweep_summary_timestamp
    )
    _pressure_sweep_phase_label = staticmethod(
        CalibrationManager._pressure_sweep_phase_label
    )
    _stream_summary_warning_list = staticmethod(
        CalibrationManager._stream_summary_warning_list
    )
    _stream_summary_invalid_reason = staticmethod(
        CalibrationManager._stream_summary_invalid_reason
    )
    _is_stream_summary_terminal_step = staticmethod(
        CalibrationManager._is_stream_summary_terminal_step
    )
    _build_stream_summary_row_from_step = CalibrationManager._build_stream_summary_row_from_step
    _build_stream_summary_rows = CalibrationManager._build_stream_summary_rows

    def __init__(self, run):
        self.run = run

    @staticmethod
    def _recheck_xyz_list_or_none(_value):
        return None

    def _get_pressure_sweep_summary_matching_runs(self):
        return "virtual-stock-1", [(0, self.run)]

    def get_pressure_sweep_summary_focus_run_id(self):
        return self.run["run_id"]


def _normalize_with_existing_manager(result):
    step_key = (
        "online_stream_calibration"
        if result.applied_printing_mode == "stream"
        else "pressure_sweep_characterization"
    )
    run = {
        "run_id": result.run_id,
        "steps": {step_key: [result.to_application_calibration_step()]},
    }
    contract = _ExistingSummaryContract(run)
    return CalibrationManager.get_characterization_summary_rows(contract)


def test_public_schema_identities_and_profile_registry_are_frozen():
    provider = SyntheticCalibrationProvider()

    assert CALIBRATION_REQUEST_SCHEMA_ID == "labcraft.sil_calibration_request"
    assert CALIBRATION_RESULT_SCHEMA_ID == "labcraft.sil_calibration_result"
    assert CALIBRATION_SCHEMA_VERSION == 1
    assert SYNTHETIC_CALIBRATION_PROVIDER_VERSION == "milestone-3-v1"
    assert tuple(profile.profile_id for profile in provider.list_profiles()) == PROFILE_IDS
    assert all(profile.profile_version == 1 for profile in provider.list_profiles())


def test_request_round_trip_is_canonical_and_strict():
    request = _request()
    payload = request.to_dict()

    assert CalibrationGenerationRequestV1.from_dict(payload) == request
    assert request.canonical_bytes() == json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(request.fingerprint) == 64

    missing = dict(payload)
    missing.pop("stock_id")
    with pytest.raises(CalibrationContractError, match="missing required"):
        CalibrationGenerationRequestV1.from_dict(missing)

    unknown = {**payload, "unexpected": True}
    with pytest.raises(CalibrationContractError, match="unknown field"):
        CalibrationGenerationRequestV1.from_dict(unknown)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"seed": True}, "seed"),
        ({"seed": -1}, "seed"),
        ({"seed": 2**63}, "seed"),
        ({"requested_mode": "auto"}, "requested_mode"),
        ({"nominal_volume_nL": float("nan")}, "finite"),
        ({"nominal_volume_nL": float("inf")}, "finite"),
        ({"volume_variation_fraction": 1.0}, r"\[0, 1\)"),
        ({"pressure_bounds_psi": (2.0, 1.0)}, "lower bound"),
        ({"pressure_bounds_psi": (0.2, 1.0)}, "0.3-5.0"),
        ({"pulse_width_bounds_us": (0, 100)}, "at least 1"),
        ({"pulse_width_bounds_us": (1800, 1200)}, "lower bound"),
    ],
)
def test_request_rejects_invalid_values(overrides, message):
    with pytest.raises(CalibrationContractError, match=message):
        _request(**overrides)


def test_request_rejects_interval_outside_application_volume_envelope():
    with pytest.raises(CalibrationContractError, match="1-250 nL"):
        _request(nominal_volume_nL=1.0, volume_variation_fraction=0.1)
    with pytest.raises(CalibrationContractError, match="1-250 nL"):
        _request(nominal_volume_nL=250.0, volume_variation_fraction=0.1)


def test_same_request_is_byte_identical_across_instances_and_call_order():
    request = _request(seed=43)
    first_provider = SyntheticCalibrationProvider()
    first = first_provider.generate(request)
    first_provider.generate(_request(seed=999))
    repeated = first_provider.generate(request)
    separate = SyntheticCalibrationProvider().generate(request)

    assert first.canonical_bytes() == repeated.canonical_bytes()
    assert first.canonical_bytes() == separate.canonical_bytes()
    assert first.result_fingerprint == repeated.result_fingerprint
    assert first.request_fingerprint == request.fingerprint


def test_different_seeds_retain_inputs_and_stay_bounded_with_variation():
    provider = SyntheticCalibrationProvider()
    results = [provider.generate(_request(seed=seed)) for seed in range(12)]

    assert len({result.result_fingerprint for result in results}) == len(results)
    assert len({result.measured_volume_nL for result in results}) > 1
    for seed, result in enumerate(results):
        assert result.seed == seed
        assert result.virtual_run_id == "virtual-run-001"
        assert result.printer_head_id == "virtual-head-A"
        assert result.stock_id == "virtual-stock-1"
        assert 9.0 <= result.measured_volume_nL <= 11.0
        assert 0.8 <= result.pressure_psi <= 2.2
        assert 1200 <= result.pw_us <= 1800


def test_generation_does_not_change_global_random_state_or_filesystem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    random.seed(99127)
    before_state = random.getstate()
    before_paths = tuple(tmp_path.rglob("*"))

    SyntheticCalibrationProvider().generate(_request())

    assert random.getstate() == before_state
    assert tuple(tmp_path.rglob("*")) == before_paths


def test_module_has_only_standard_library_imports():
    source_path = Path(__file__).parents[1] / "tools" / "sil" / "synthetic_calibration.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
        "math",
        "random",
        "re",
        "typing",
    }


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_every_profile_generates_a_round_trip_result(profile_id):
    result = SyntheticCalibrationProvider().generate(_request(profile_id))
    payload = result.to_dict()

    assert result.schema_id == CALIBRATION_RESULT_SCHEMA_ID
    assert result.request_fingerprint == result.to_request().fingerprint
    assert CalibrationGenerationResultV1.from_dict(payload) == result
    assert len(result.result_fingerprint) == 64
    assert result.timestamp.startswith("2000-")
    assert result.run_id == result.virtual_run_id
    assert result.synthetic_limitations


@pytest.mark.parametrize("profile_id", ("nominal_droplet", "nominal_stream"))
def test_nominal_results_pass_existing_application_summary_contract(profile_id):
    result = SyntheticCalibrationProvider().generate(_request(profile_id))
    row = result.to_application_summary_row()
    existing_rows = _normalize_with_existing_manager(result)

    assert result.application_valid is True
    assert result.validation_errors == ()
    assert len(existing_rows) == 1
    existing_row = existing_rows[0]
    assert existing_row["valid"] is True
    assert existing_row["printing_mode"] == result.applied_printing_mode
    assert existing_row["mean_nL"] == pytest.approx(result.measured_volume_nL)
    assert validate_ejection_volume_for_mode(
        row["mean_nL"], row["printing_mode"]
    ) == pytest.approx(result.measured_volume_nL)
    assert tuple(_summary_row_fingerprint(row)) == result.source_row_fingerprint
    if profile_id == "nominal_stream":
        assert existing_row["tail_phase_status"] == "captured"
        assert existing_row["warnings"] == [
            "synthetic_result_without_camera_evidence"
        ]


def test_droplet_to_stream_retains_explicit_mode_transition():
    result = SyntheticCalibrationProvider().generate(_request("droplet_to_stream"))
    row = result.to_application_summary_row()

    assert result.original_printing_mode == "droplet"
    assert result.applied_printing_mode == "stream"
    assert result.measured_volume_nL >= 40.0
    assert row["printing_mode"] == "stream"
    assert row["phase"] == "stream"


def test_boundary_profiles_land_on_exact_inclusive_application_bounds():
    provider = SyntheticCalibrationProvider()
    low = provider.generate(_request("low_volume_boundary"))
    high = provider.generate(_request("high_volume_boundary"))

    assert low.measured_volume_nL == 1.0
    assert high.measured_volume_nL == 250.0
    low.validate_for_application()
    high.validate_for_application()


@pytest.mark.parametrize(
    ("profile_id", "expected_error"),
    [
        ("invalid_outlier", "measured_volume_outside_requested_bounds"),
        ("missing_measurement", "missing_measurement"),
    ],
)
def test_invalid_profiles_are_inspectable_but_rejected_before_adaptation(
    profile_id, expected_error
):
    result = SyntheticCalibrationProvider().generate(_request(profile_id))

    assert result.application_valid is False
    assert expected_error in result.validation_errors
    with pytest.raises(CalibrationApplicationError, match=expected_error):
        result.validate_for_application()
    with pytest.raises(CalibrationApplicationError, match=expected_error):
        result.to_application_summary_row()
    with pytest.raises(CalibrationApplicationError, match=expected_error):
        result.to_application_calibration_step()


def test_unknown_profile_and_profile_mode_mismatches_fail_closed():
    provider = SyntheticCalibrationProvider()
    with pytest.raises(CalibrationContractError, match="unsupported"):
        provider.generate(_request("unknown_profile"))
    with pytest.raises(CalibrationContractError, match="requires requested_mode"):
        provider.generate(_request("nominal_droplet", requested_mode="stream"))
    with pytest.raises(CalibrationContractError, match="below 40"):
        provider.generate(
            _request(
                "nominal_droplet",
                nominal_volume_nL=39.0,
                volume_variation_fraction=0.1,
            )
        )
    with pytest.raises(CalibrationContractError, match="at or above 40"):
        provider.generate(
            _request(
                "nominal_stream",
                requested_mode="stream",
                nominal_volume_nL=40.0,
                volume_variation_fraction=0.1,
            )
        )


def test_result_rejects_unknown_fields_and_fingerprint_or_payload_tampering():
    result = SyntheticCalibrationProvider().generate(_request())
    payload = result.to_dict()

    with pytest.raises(CalibrationContractError, match="unknown field"):
        CalibrationGenerationResultV1.from_dict({**payload, "unexpected": 1})

    altered_fingerprint = dict(payload)
    altered_fingerprint["result_fingerprint"] = "0" * 64
    with pytest.raises(CalibrationContractError, match="result_fingerprint"):
        CalibrationGenerationResultV1.from_dict(altered_fingerprint)

    altered_input = dict(payload)
    altered_input["stock_id"] = "different-stock"
    with pytest.raises(CalibrationContractError, match="request_fingerprint"):
        CalibrationGenerationResultV1.from_dict(altered_input)

    non_finite = dict(payload)
    non_finite["measured_volume_nL"] = math.inf
    with pytest.raises(CalibrationContractError, match="finite"):
        CalibrationGenerationResultV1.from_dict(non_finite)
