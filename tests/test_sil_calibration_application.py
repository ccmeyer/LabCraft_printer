from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from tools.sil.calibration_application import SyntheticCalibrationApplicationAdapter


class _Manager:
    def __init__(self, context):
        self.context = dict(context)
        self.candidate = None
        self.historical_candidates = ()

    def get_characterization_application_context(self):
        return dict(self.context)

    def set_transient_characterization_candidate(self, candidate):
        self.candidate = candidate

    def clear_transient_characterization_candidate(self, candidate_id=None):
        if self.candidate is None:
            return False
        if candidate_id is not None and self.candidate.candidate_id != candidate_id:
            return False
        self.candidate = None
        return True

    def set_historical_characterization_candidates(self, candidates):
        self.historical_candidates = tuple(candidates or ())
        return tuple(candidate.candidate_id for candidate in self.historical_candidates)

    def clear_historical_characterization_candidates(self):
        changed = bool(self.historical_candidates)
        self.historical_candidates = ()
        return changed


class _Recorder:
    healthy = True

    def __init__(self):
        self.events = []

    def record_event(self, kind, **kwargs):
        self.events.append((kind, kwargs))


def _adapter(
    tmp_path,
    *,
    context=None,
    session_id="session-1",
    application_session_id="application-1",
    pulse_width_us=1400,
):
    context = context or {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": 10.0,
    }
    manager = _Manager(context)
    stock = SimpleNamespace(
        stock_id=context["stock_id"],
        factor_name=context["factor_name"],
        option_name=None,
        printing_mode=context["printing_mode"],
    )
    experiment = SimpleNamespace(
        applied_imaging_calibration_changed=SignalStub(),
        get_execution_plan_snapshot=lambda: SimpleNamespace(stocks=(stock,)),
        get_execution_plan_source=lambda: "finalized",
        get_fill_reagent_name=lambda: "Water",
        execution_calibrations_file_path=tmp_path / "execution_calibrations.json",
    )
    settings = {"pulse_width_us": int(pulse_width_us)}
    model = SimpleNamespace(
        calibration_manager=manager,
        experiment_model=experiment,
        print_profiles=[
            {
                "id": "water_droplet",
                "name": "Water - droplet",
                "mode": "droplet",
                "print_pressure": 0.6,
                "refuel_pressure": 0.3,
                "print_pulse_width": 1300,
                "refuel_pulse_width": 3000,
            },
            {
                "id": "water_stream",
                "name": "Water - stream",
                "mode": "stream",
                "print_pressure": 0.8,
                "refuel_pressure": 0.8,
                "print_pulse_width": 2500,
                "refuel_pulse_width": 6000,
            },
        ],
        machine_model=SimpleNamespace(
            get_target_print_pressure=lambda: 1.25,
            get_print_pulse_width=lambda: settings["pulse_width_us"],
        ),
    )
    machine = SimpleNamespace(
        state=SimpleNamespace(
            connected=True,
            motors_enabled=True,
            homed=True,
            regulating_print_pressure=True,
            simulated_elapsed_ms=100,
        ),
        check_if_all_completed=lambda: True,
    )
    controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    recorder = _Recorder()
    opened = []
    failures = []
    adapter = SyntheticCalibrationApplicationAdapter(
        session_root=Path(tmp_path),
        session_id=session_id,
        application_session_id=application_session_id,
        seed=7,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        open_dialog_callback=lambda candidate_id: opened.append(candidate_id) or object(),
        failure_callback=failures.append,
    )
    adapter._test_settings = settings
    return adapter, manager, recorder, opened, failures


def _record_for_result(result, *, record_id="record-1"):
    payload = {
        "stock_id": result.stock_id,
        "printer_head_id": result.printer_head_id,
        "factor_name": result.factor_name,
        "option_name": result.option_name,
        "is_fill": result.is_fill,
        "source_row_fingerprint": list(result.source_row_fingerprint),
        "original_printing_mode": result.original_printing_mode,
        "applied_printing_mode": result.applied_printing_mode,
        "effective_volume_nL": result.effective_volume_nL,
        "pressure_psi": result.pressure_psi,
        "pw_us": result.pw_us,
    }
    return SimpleNamespace(
        record_id=record_id,
        source_row_fingerprint=result.source_row_fingerprint,
        recorded_at_utc="2026-08-05T00:00:00Z",
        to_dict=lambda payload=payload: dict(payload),
    )


def test_adapter_generates_deterministic_candidate_and_canonical_evidence(tmp_path):
    adapter, manager, recorder, opened, failures = _adapter(tmp_path)
    statuses = []
    adapter.set_status_changed_callback(statuses.append)

    first = adapter.generate_and_present_nominal_droplet()
    second = adapter.generate_and_present_nominal_droplet()

    assert first["ok"] is True
    assert second["result_fingerprint"] == first["result_fingerprint"]
    assert opened == [first["result_fingerprint"], first["result_fingerprint"]]
    assert manager.candidate.result_fingerprint == first["result_fingerprint"]
    assert failures == []
    result = adapter.current_result
    artifact_dir = (
        tmp_path
        / "artifacts"
        / "synthetic-calibration"
        / "application-1"
        / result.result_fingerprint
    )
    assert (artifact_dir / "request.json").read_bytes() == adapter.current_request.canonical_bytes()
    assert (artifact_dir / "result.json").read_bytes() == result.canonical_bytes()
    assert [kind for kind, _payload in recorder.events] == [
        "synthetic_calibration_generated",
        "synthetic_calibration_generated",
    ]
    assert "Readiness: Ready" in statuses[-1]
    assert f"Candidate: {first['result_fingerprint']}" in statuses[-1]
    assert "Apply: Awaiting Apply" in statuses[-1]

    adapter.model.experiment_model.applied_imaging_calibration_changed.emit(
        {
            "stock_id": result.stock_id,
            "printer_head_id": result.printer_head_id,
            "factor_name": result.factor_name,
            "option_name": result.option_name,
            "is_fill": result.is_fill,
            "source_row_fingerprint": list(result.source_row_fingerprint),
            "original_printing_mode": result.original_printing_mode,
            "applied_printing_mode": result.applied_printing_mode,
            "effective_volume_nL": result.effective_volume_nL,
            "pressure_psi": result.pressure_psi,
            "pw_us": result.pw_us,
        }
    )
    assert "Apply: Applied" in statuses[-1]
    assert recorder.events[-1][0] == "synthetic_calibration_applied"


def test_generated_artifacts_append_by_fingerprint_and_identical_results_deduplicate(
    tmp_path,
):
    adapter, manager, _recorder, _opened, failures = _adapter(
        tmp_path,
        pulse_width_us=1800,
    )

    droplet = adapter.generate("nominal_droplet")
    adapter._test_settings["pulse_width_us"] = 2500
    stream = adapter.generate("droplet_to_stream")
    repeated = adapter.generate("droplet_to_stream")

    assert droplet["ok"] is True
    assert stream["ok"] is True
    assert repeated["result_fingerprint"] == stream["result_fingerprint"]
    assert failures == []
    assert {candidate.result_fingerprint for candidate in manager.historical_candidates} == {
        droplet["result_fingerprint"],
        stream["result_fingerprint"],
    }
    assert {
        candidate.application_record_state
        for candidate in manager.historical_candidates
    } == {"generated_unapplied"}
    assert manager.candidate.result_fingerprint == stream["result_fingerprint"]
    assert manager.candidate.application_record_state == "pending_apply"


def test_generated_artifact_rehydrates_without_execution_sidecar(tmp_path):
    first, _manager, _recorder, _opened, failures = _adapter(
        tmp_path,
        application_session_id="application-1",
        pulse_width_us=1800,
    )
    generated = first.generate("nominal_droplet")
    reopened, reopened_manager, _recorder, _opened, reopened_failures = _adapter(
        tmp_path,
        application_session_id="application-2",
        pulse_width_us=1800,
    )

    readiness = reopened.availability("nominal_droplet")

    assert generated["ok"] is True
    assert readiness["ok"] is True
    assert failures == []
    assert reopened_failures == []
    assert len(reopened_manager.historical_candidates) == 1
    retained = reopened_manager.historical_candidates[0]
    assert retained.result_fingerprint == generated["result_fingerprint"]
    assert retained.application_record_state == "generated_unapplied"
    assert retained.application_allowed is True


def test_apply_signal_promotes_matching_generated_artifact_without_duplication(
    monkeypatch,
    tmp_path,
):
    adapter, manager, recorder, _opened, failures = _adapter(
        tmp_path,
        pulse_width_us=1800,
    )
    droplet = adapter.generate("nominal_droplet")
    adapter._test_settings["pulse_width_us"] = 2500
    stream = adapter.generate("droplet_to_stream")
    stream_result = adapter.current_result
    stream_record = _record_for_result(stream_result, record_id="stream-record")
    adapter.model.experiment_model.execution_calibrations_file_path.write_text(
        "{}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ExecutionCalibrationStore.load_execution_calibrations",
        lambda _path: SimpleNamespace(records={"stream-record": stream_record}),
    )

    adapter.model.experiment_model.applied_imaging_calibration_changed.emit(
        stream_record.to_dict()
    )

    assert failures == []
    assert recorder.events[-1][0] == "synthetic_calibration_applied"
    assert manager.candidate is None
    assert len(manager.historical_candidates) == 2
    states = {
        candidate.result_fingerprint: candidate.application_record_state
        for candidate in manager.historical_candidates
    }
    assert states == {
        droplet["result_fingerprint"]: "generated_unapplied",
        stream["result_fingerprint"]: "applied_history",
    }


def test_missing_artifact_pair_latches_history_failure_and_clears_candidates(tmp_path):
    adapter, manager, _recorder, _opened, failures = _adapter(tmp_path)
    generated = adapter.generate("nominal_droplet")
    request_path = (
        tmp_path
        / "artifacts"
        / "synthetic-calibration"
        / "application-1"
        / generated["result_fingerprint"]
        / "request.json"
    )
    request_path.unlink()

    with pytest.raises(RuntimeError, match="request artifact is missing"):
        adapter._refresh_historical_candidates(force=True)

    assert failures
    assert manager.candidate is None
    assert manager.historical_candidates == ()
    assert adapter.availability("nominal_droplet")["code"] == "history_validation_failed"


def test_adapter_reports_correctable_target_mode_pulse_and_profiles(tmp_path):
    adapter, manager, recorder, opened, _failures = _adapter(
        tmp_path,
        pulse_width_us=1300,
    )

    preflight = adapter.calibration_settings_preflight("droplet_to_stream")
    generated = adapter.generate("droplet_to_stream")

    assert preflight["ok"] is False
    assert preflight["correctable"] is True
    assert preflight["code"] == "synthetic_pulse_width_out_of_range"
    assert preflight["minimum_print_pulse_width_us"] == 2500
    assert preflight["maximum_print_pulse_width_us"] == 10000
    assert [profile["id"] for profile in preflight["matching_profiles"]] == [
        "water_stream"
    ]
    assert generated["ok"] is False
    assert manager.candidate is None
    assert recorder.events == []
    assert opened == []


@pytest.mark.parametrize(
    ("profile_id", "mode", "source_volume", "pulse_width", "expected_volume"),
    (
        ("nominal_droplet", "droplet", 9.0, 1300, 9.0),
        ("nominal_droplet", "droplet", 9.0, 1800, 18.0),
        ("droplet_to_stream", "droplet", 9.0, 2500, 60.0),
        ("nominal_stream", "stream", 60.0, 10000, 250.0),
        ("stream_to_droplet", "stream", 60.0, 1300, 9.0),
    ),
)
def test_adapter_uses_pulse_aware_v3_for_all_ui_profiles(
    tmp_path,
    profile_id,
    mode,
    source_volume,
    pulse_width,
    expected_volume,
):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": mode,
        "design_volume_nL": source_volume,
    }
    adapter, manager, _recorder, _opened, failures = _adapter(
        tmp_path,
        context=context,
        pulse_width_us=pulse_width,
    )

    generated = adapter.generate(profile_id)

    assert generated["ok"] is True
    assert adapter.current_result.schema_version == 3
    assert adapter.current_result.measured_volume_nL == expected_volume
    assert adapter.current_result.pw_us == pulse_width
    assert manager.candidate.application_allowed is True
    assert failures == []


def test_adapter_fails_closed_before_injection_when_evidence_write_is_ambiguous(
    monkeypatch,
    tmp_path,
):
    adapter, manager, _recorder, opened, failures = _adapter(tmp_path)
    attempts = []

    def fail_write(*_args, **_kwargs):
        attempts.append(_args)
        raise PermissionError("verified write denial")

    monkeypatch.setattr(
        "tools.sil.calibration_application._write_canonical_once",
        fail_write,
    )
    result = adapter.generate_and_present_nominal_droplet()

    assert result["ok"] is False
    assert result["code"] == "evidence_persistence_failed"
    assert manager.candidate is None
    assert opened == []
    assert failures and "verified write denial" in failures[0]

    second = adapter.generate_and_present_nominal_droplet()
    assert second["code"] == "evidence_persistence_failed"
    assert len(attempts) == 1


def test_adapter_rejects_missing_or_mismatched_execution_identity(tmp_path):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "different-stock",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": 10.0,
    }
    adapter, manager, _recorder, opened, _failures = _adapter(tmp_path, context=context)
    # Make the plan disagree with the manager-resolved stock identity.
    adapter.model.experiment_model.get_execution_plan_snapshot = lambda: SimpleNamespace(
        stocks=(
            SimpleNamespace(
                stock_id="plan-stock",
                factor_name="Virtual Factor",
                option_name=None,
                printing_mode="droplet",
            ),
        )
    )

    result = adapter.generate_and_present_nominal_droplet()

    assert result["ok"] is False
    assert result["code"] == "stock_identity_mismatch"
    assert manager.candidate is None
    assert opened == []


def test_adapter_accepts_exact_loaded_stock_in_multi_stock_plan(tmp_path):
    adapter, manager, recorder, opened, _failures = _adapter(tmp_path)
    matching_stock = adapter.model.experiment_model.get_execution_plan_snapshot().stocks[0]
    adapter.model.experiment_model.get_execution_plan_snapshot = lambda: SimpleNamespace(
        stocks=(
            matching_stock,
            SimpleNamespace(
                stock_id="other-stock",
                factor_name="Other Factor",
                option_name=None,
                printing_mode="droplet",
            ),
            SimpleNamespace(
                stock_id="water-stock",
                factor_name="Water",
                option_name=None,
                printing_mode="droplet",
            ),
        )
    )

    result = adapter.generate_and_present_nominal_droplet()

    assert result["ok"] is True
    assert manager.candidate.stock_id == matching_stock.stock_id
    assert manager.candidate.factor_name == matching_stock.factor_name
    assert opened == [result["result_fingerprint"]]
    assert [kind for kind, _payload in recorder.events] == [
        "synthetic_calibration_generated"
    ]
    artifact = (
        tmp_path
        / "artifacts"
        / "synthetic-calibration"
        / "application-1"
        / result["result_fingerprint"]
    )
    assert (artifact / "request.json").is_file()
    assert (artifact / "result.json").is_file()


def test_adapter_rejects_duplicate_loaded_stock_identity_before_evidence(tmp_path):
    adapter, manager, recorder, opened, _failures = _adapter(tmp_path)
    matching_stock = adapter.model.experiment_model.get_execution_plan_snapshot().stocks[0]
    adapter.model.experiment_model.get_execution_plan_snapshot = lambda: SimpleNamespace(
        stocks=(
            matching_stock,
            SimpleNamespace(
                stock_id=matching_stock.stock_id,
                factor_name=matching_stock.factor_name,
                option_name=matching_stock.option_name,
                printing_mode=matching_stock.printing_mode,
            ),
            SimpleNamespace(
                stock_id="other-stock",
                factor_name="Other Factor",
                option_name=None,
                printing_mode="droplet",
            ),
        )
    )

    result = adapter.generate_and_present_nominal_droplet()

    assert result["ok"] is False
    assert result["code"] == "stock_identity_mismatch"
    assert manager.candidate is None
    assert opened == []
    assert recorder.events == []
    assert not (tmp_path / "artifacts" / "synthetic-calibration").exists()


@pytest.mark.parametrize("source_volume_nL", (1.0, 9.0, 20.0, 25.0, 39.999999))
def test_droplet_to_stream_generation_is_deterministic_and_reaches_boundary(
    tmp_path,
    source_volume_nL,
):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": source_volume_nL,
    }
    adapter, manager, _recorder, opened, failures = _adapter(
        tmp_path,
        context=context,
        pulse_width_us=2500,
    )

    first = adapter.generate_and_present("droplet_to_stream")
    second = adapter.generate_and_present("droplet_to_stream")

    assert first["ok"] is True
    assert second["result_fingerprint"] == first["result_fingerprint"]
    assert opened == [first["result_fingerprint"], first["result_fingerprint"]]
    assert failures == []
    result = adapter.current_result
    assert result.original_printing_mode == "droplet"
    assert result.applied_printing_mode == "stream"
    assert result.schema_version == 3
    assert result.profile_version == 3
    assert result.provider_version == "milestone-4d-v1"
    assert result.source_volume_nL == source_volume_nL
    assert result.measured_volume_nL == 60.0
    assert manager.candidate.requested_printing_mode == "droplet"
    assert manager.candidate.printing_mode == "stream"
    assert manager.candidate.summary_row["original_printing_mode"] == "droplet"
    assert manager.candidate.summary_row["applied_printing_mode"] == "stream"
    assert manager.candidate.summary_row["source_volume_nL"] == source_volume_nL
    assert manager.candidate.summary_row["synthetic_response_model_version"] == 1
    generated_event = _recorder.events[-1]
    assert generated_event[1]["payload"]["source_volume_nL"] == source_volume_nL
    assert generated_event[1]["payload"]["target_volume_nL"] is None


@pytest.mark.parametrize("source_volume_nL", (40.0, 250.0))
def test_droplet_to_stream_adapter_rejects_non_droplet_source_volume(
    tmp_path,
    source_volume_nL,
):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": source_volume_nL,
    }
    adapter, manager, recorder, opened, _failures = _adapter(
        tmp_path,
        context=context,
    )

    result = adapter.generate("droplet_to_stream")

    assert result["ok"] is False
    assert result["code"] == "volume_out_of_range"
    assert manager.candidate is None
    assert recorder.events == []
    assert opened == []


def test_generate_registers_in_current_dialog_without_opening_another(tmp_path):
    adapter, manager, _recorder, opened, _failures = _adapter(tmp_path)

    generated = adapter.generate("nominal_droplet")

    assert generated["ok"] is True
    assert generated["code"] == "generated"
    assert manager.candidate.candidate_id == generated["candidate_id"]
    assert opened == []


def test_stream_to_droplet_generation_uses_droplet_pulse_response(tmp_path):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "stream",
        "design_volume_nL": 40.0,
    }
    adapter, manager, _recorder, opened, failures = _adapter(
        tmp_path,
        context=context,
    )

    first = adapter.generate("stream_to_droplet")
    second = adapter.generate("stream_to_droplet")

    assert first["ok"] is True
    assert second["result_fingerprint"] == first["result_fingerprint"]
    assert opened == []
    assert failures == []
    assert adapter.current_result.original_printing_mode == "stream"
    assert adapter.current_result.applied_printing_mode == "droplet"
    assert adapter.current_result.measured_volume_nL == 10.8
    assert manager.candidate.requested_printing_mode == "stream"
    assert manager.candidate.printing_mode == "droplet"


def test_stream_to_droplet_accepts_full_stream_source_envelope(tmp_path):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "stream",
        "design_volume_nL": 200.0,
    }
    adapter, manager, recorder, opened, _failures = _adapter(
        tmp_path,
        context=context,
    )

    result = adapter.generate("stream_to_droplet")

    assert result["ok"] is True
    assert manager.candidate is not None
    assert adapter.current_result.measured_volume_nL == 10.8
    assert recorder.events
    assert opened == []


def test_stream_generation_is_stable_across_instances_call_order_and_application_sessions(
    tmp_path,
):
    transition_context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": 25.0,
    }
    first, _manager, _recorder, _opened, _failures = _adapter(
        tmp_path,
        context=transition_context,
        application_session_id="application-1",
        pulse_width_us=2500,
    )
    first_transition = first.generate_and_present("droplet_to_stream")

    reordered, _manager, _recorder, _opened, _failures = _adapter(
        tmp_path,
        context=transition_context,
        application_session_id="application-2",
        pulse_width_us=2500,
    )
    reordered_transition = reordered.generate_and_present("droplet_to_stream")

    assert reordered_transition["result_fingerprint"] == first_transition[
        "result_fingerprint"
    ]
    assert reordered.current_request.canonical_bytes() == first.current_request.canonical_bytes()
    assert reordered.current_result.canonical_bytes() == first.current_result.canonical_bytes()

    stream_context = dict(transition_context)
    stream_context.update(printing_mode="stream", design_volume_nL=40.0)
    stream_first, _manager, _recorder, _opened, _failures = _adapter(
        tmp_path,
        context=stream_context,
        application_session_id="application-1",
        pulse_width_us=2500,
    )
    stream_reopened, _manager, _recorder, _opened, _failures = _adapter(
        tmp_path,
        context=stream_context,
        application_session_id="application-2",
        pulse_width_us=2500,
    )
    first_stream = stream_first.generate_and_present("nominal_stream")
    reopened_stream = stream_reopened.generate_and_present("nominal_stream")

    assert reopened_stream["result_fingerprint"] == first_stream["result_fingerprint"]
    assert (
        stream_reopened.current_result.canonical_bytes()
        == stream_first.current_result.canonical_bytes()
    )


def test_nominal_stream_generation_uses_current_stream_context(tmp_path):
    context = {
        "printer_head_id": "virtual-head-1",
        "stock_id": "virtual-stock-1",
        "factor_name": "Virtual Factor",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "stream",
        "design_volume_nL": 40.0,
    }
    adapter, manager, _recorder, _opened, _failures = _adapter(
        tmp_path,
        context=context,
        pulse_width_us=2500,
    )

    result = adapter.generate_and_present("nominal_stream")

    assert result["ok"] is True
    assert adapter.current_result.original_printing_mode == "stream"
    assert adapter.current_result.applied_printing_mode == "stream"
    assert adapter.current_result.measured_volume_nL == 60.0
    assert manager.candidate.requested_printing_mode == "stream"


def test_application_adapter_allowlist_and_stream_context_fail_closed(tmp_path):
    adapter, manager, recorder, opened, _failures = _adapter(tmp_path)

    unsupported = adapter.generate_and_present("invalid_outlier")
    wrong_mode = adapter.generate_and_present("nominal_stream")

    assert unsupported["code"] == "unsupported_profile"
    assert wrong_mode["code"] == "stream_mode_required"
    assert manager.candidate is None
    assert recorder.events == []
    assert opened == []


def test_historical_rehydration_accepts_coexisting_v1_and_v2_results(
    monkeypatch,
    tmp_path,
):
    adapter, manager, _recorder, _opened, _failures = _adapter(tmp_path)
    assert adapter.generate("nominal_droplet")["ok"] is True
    v1_result = adapter.current_result
    adapter._test_settings["pulse_width_us"] = 2500
    assert adapter.generate("droplet_to_stream")["ok"] is True
    v2_result = adapter.current_result

    calibration_path = tmp_path / "execution_calibrations.json"
    calibration_path.write_text("{}", encoding="utf-8")
    adapter.model.experiment_model.execution_calibrations_file_path = calibration_path
    document = SimpleNamespace(
        records={
            "v1-record": _record_for_result(v1_result, record_id="v1-record"),
            "v2-record": _record_for_result(v2_result, record_id="v2-record"),
        }
    )
    monkeypatch.setattr(
        "ExecutionCalibrationStore.load_execution_calibrations",
        lambda _path: document,
    )

    adapter._refresh_historical_candidates(force=True)

    assert {candidate.result_fingerprint for candidate in manager.historical_candidates} == {
        v1_result.result_fingerprint,
        v2_result.result_fingerprint,
    }
    assert {candidate.printing_mode for candidate in manager.historical_candidates} == {
        "droplet",
        "stream",
    }
