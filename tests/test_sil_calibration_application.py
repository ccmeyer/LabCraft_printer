from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from tools.sil.calibration_application import SyntheticCalibrationApplicationAdapter


class _Manager:
    def __init__(self, context):
        self.context = dict(context)
        self.candidate = None

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


class _Recorder:
    healthy = True

    def __init__(self):
        self.events = []

    def record_event(self, kind, **kwargs):
        self.events.append((kind, kwargs))


def _adapter(tmp_path, *, context=None):
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
        printing_mode="droplet",
    )
    experiment = SimpleNamespace(
        applied_imaging_calibration_changed=SignalStub(),
        get_execution_plan_snapshot=lambda: SimpleNamespace(stocks=(stock,)),
        get_execution_plan_source=lambda: "finalized",
        get_fill_reagent_name=lambda: "Water",
    )
    model = SimpleNamespace(
        calibration_manager=manager,
        experiment_model=experiment,
        machine_model=SimpleNamespace(
            get_target_print_pressure=lambda: 1.25,
            get_print_pulse_width=lambda: 1400,
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
        session_id="session-1",
        application_session_id="application-1",
        seed=7,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        open_dialog_callback=lambda candidate_id: opened.append(candidate_id) or object(),
        failure_callback=failures.append,
    )
    return adapter, manager, recorder, opened, failures


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
            "source_row_fingerprint": list(result.source_row_fingerprint),
        }
    )
    assert "Apply: Applied" in statuses[-1]
    assert recorder.events[-1][0] == "synthetic_calibration_applied"


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


def test_adapter_rejects_multi_stock_plan_before_evidence_or_injection(tmp_path):
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

    assert result["ok"] is False
    assert result["code"] == "single_stock_required"
    assert manager.candidate is None
    assert opened == []
    assert recorder.events == []
    assert not (tmp_path / "artifacts" / "synthetic-calibration").exists()
