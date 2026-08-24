import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ExecutionCalibrationStore import (
    ExecutionCalibrationDocument,
    ExecutionCalibrationRecord,
    deterministic_calibration_record_id,
    save_execution_calibrations,
)
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)
from tools.sil.state_projection import StateProjectionBuilder


def _session(qapp, root: Path):
    return SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            root_policy=SessionRootPolicy.RETAINED,
            session_root=root.resolve(),
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            speed_multiplier=1000.0,
            source_identity="pytest-projection",
        )
    )


def _execution_calibration_document(plan_id: str) -> ExecutionCalibrationDocument:
    records = {}
    for index, (volume, mode) in enumerate(((9.0, "droplet"), (40.0, "stream")), 1):
        values = {
            "stock_id": "stock-1",
            "printer_head_id": "head-1",
            "factor_name": "Factor A",
            "option_name": "",
            "is_fill": False,
            "measured_volume_nL": volume,
            "effective_volume_nL": volume,
            "pw_us": 1400,
            "pressure_psi": 1.2,
            "run_id": f"run-{index}",
            "phase": "synthetic_characterization",
            "timestamp": f"2000-01-0{index}T00:00:00Z",
            "source_row_fingerprint": ("head-1", "stock-1", index, 1.2, 1400, volume),
            "original_printing_mode": "droplet",
            "applied_printing_mode": mode,
            "printing_mode": mode,
            "applied_design_volume_nL": volume,
            "recorded_at": f"2000-01-0{index}T00:00:00Z",
            "recorded_at_utc": f"2000-01-0{index}T00:00:00Z",
        }
        record_id = deterministic_calibration_record_id(plan_id, values)
        records[record_id] = ExecutionCalibrationRecord(
            record_id=record_id,
            **values,
        )
    latest_id = next(reversed(records))
    latest = records[latest_id]
    return ExecutionCalibrationDocument(
        plan_id=plan_id,
        records=records,
        manual_refuel_checks={
            "check-1": {
                "status": "passed",
                "source": "sil_simulated_manual_refuel_check",
                "stock_id": "stock-1",
                "printer_head_id": "head-1",
                "printing_mode": "stream",
                "factor_name": "Factor A",
                "option_name": "",
                "is_fill": False,
                "calibration_record_id": latest_id,
                "applied_calibration_fingerprint": "fingerprint-1",
                "applied_calibration_record": latest.to_dict(),
                "previous_status": "failed",
                "recorded_at": "2000-01-03T00:00:00Z",
            }
        },
    )


def test_projection_is_read_only_and_persistence_is_explicit(qapp, tmp_path, monkeypatch):
    session = _session(qapp, tmp_path / "projection")
    experiment = session.components.model.experiment_model
    experiment.metadata["name"] = "projection-test"
    experiment.initialize_experiment()
    experiment_root = Path(experiment.experiment_dir_path)
    authority = experiment_root / "progress.json"
    authority_payload = {
        "schema_id": "labcraft.execution_progress",
        "schema_version": 1,
        "plan_id": "plan-1",
        "plan_revision": 2,
        "wells": {"A1": {"status": "pending"}},
        "intents": [
            {"status": "pending"},
            {"status": "completed"},
        ],
    }
    authority.write_text(json.dumps(authority_payload), encoding="utf-8")
    before = authority.read_bytes()

    def mutation_was_called(*_args, **_kwargs):
        raise AssertionError("projection called an application mutation")

    monkeypatch.setattr(session.components.controller, "toggle_motors", mutation_was_called)
    monkeypatch.setattr(session.components.controller, "home_machine", mutation_was_called)

    try:
        projector = StateProjectionBuilder(session)
        frequent = projector.capture(reason="high-frequency")
        simulator_state = frequent["layers"]["simulator"]["state"]
        model_state = frequent["layers"]["model_machine"]["state"]
        assert simulator_state["current_print_pressure_raw"] == 0
        assert simulator_state["current_print_pressure_psi"] == -1.8746
        assert model_state["current_print_pressure"] == 0
        assert frequent["layers"]["controller"]["state"]["loaded_array"][
            "state"
        ] == "no_head"
        assert frequent["reconciliation"]["status"] == "ok"
        assert frequent["layers"]["persistence"]["state"] == {
            "status": "not_captured"
        }
        assert authority.read_bytes() == before

        explicit = projector.capture(reason="manual", include_persistence=True)
        persistence = explicit["layers"]["persistence"]
        assert persistence["available"] is True
        progress = persistence["state"]["documents"]["progress.json"]
        assert progress["exists"] is True
        assert progress["size_bytes"] == len(before)
        assert progress["document"]["well_count"] == 1
        assert progress["document"]["intent_counts"] == {
            "completed": 1,
            "pending": 1,
        }
        assert authority.read_bytes() == before

        cached = projector.capture(reason="coalesced")
        assert cached["layers"]["persistence"] == persistence
        assert authority.read_bytes() == before
        assert set(explicit["layers"]) == {
            "session",
            "simulator",
            "controller",
            "model_machine",
            "rack_head",
            "experiment",
            "calibration",
            "refuel_check",
            "ui",
            "persistence",
        }
    finally:
        assert session.close()


def test_unavailable_layers_and_reconciliation_are_explicit(tmp_path):
    class BrokenMachine:
        @property
        def state(self):
            raise RuntimeError("unavailable simulator state")

    session = SimpleNamespace(
        config=SimpleNamespace(
            source_identity="test",
            expected_runtime_mode="simulation",
            seed=1,
            speed_multiplier=1.0,
        ),
        application_roots=SimpleNamespace(
            config_root=tmp_path / "config",
            experiments_root=tmp_path / "experiments",
            calibration_memory_root=tmp_path / "calibration-memory",
        ),
        session_id="session",
        application_session_id="application",
        session_root=tmp_path,
        recorder=None,
        components=SimpleNamespace(
            machine=BrokenMachine(),
            model=None,
            controller=None,
            view=None,
        ),
    )

    projection = StateProjectionBuilder(session).capture(reason="broken")
    assert projection["layers"]["simulator"] == {
        "available": False,
        "state": {},
        "error": "RuntimeError: unavailable simulator state",
    }
    assert projection["layers"]["model_machine"]["available"] is False
    assert projection["reconciliation"] == {
        "status": "unavailable",
        "compared_fields": 0,
        "mismatches": [],
        "domains": {},
    }


def test_authoritative_bundle_supplies_calibration_and_refuel_memory_layers():
    class Record:
        def __init__(self, payload):
            self.payload = dict(payload)

        def to_dict(self):
            return dict(self.payload)

    calibration = Record(
        {
            "record_id": "cal-1",
            "stock_id": "stock-1",
            "pw_us": 1400,
        }
    )
    refuel = Record(
        {
            "status": "passed",
            "stock_id": "stock-1",
        }
    )
    document = SimpleNamespace(
        schema_version=1,
        plan_id="plan-1",
        records={"cal-1": calibration},
        manual_refuel_checks={"check-1": refuel},
    )
    bundle = SimpleNamespace(
        plan=SimpleNamespace(plan_id="plan-1"),
        calibrations=document,
    )
    manager = SimpleNamespace(
        activeCalibration=None,
        calibration_queue=[],
        get_stream_calibration_sequence_state=lambda: {},
        get_droplet_calibration_sequence_state=lambda: {},
    )
    experiment = SimpleNamespace(
        applied_imaging_calibrations={"schema_version": 1, "records": {}},
        manual_refuel_checks={"schema_version": 1, "records": {}},
        _active_authoritative_execution_session=SimpleNamespace(bundle=bundle),
    )
    session = SimpleNamespace(
        components=SimpleNamespace(
            model=SimpleNamespace(
                experiment_model=experiment,
                calibration_manager=manager,
            )
        )
    )
    projector = StateProjectionBuilder(session)

    calibration_state = projector._calibration_state()
    refuel_state = projector._refuel_state()

    assert calibration_state["applied_records"] == {
        "cal-1": {
            "record_id": "cal-1",
            "stock_id": "stock-1",
            "pw_us": 1400,
        }
    }
    assert refuel_state["records"] == {
        "check-1": {
            "stock_id": "stock-1",
            "status": "passed",
        }
    }
    reconciliation = projector._reconcile(
        {
            "simulator": {"available": True, "state": {}},
            "model_machine": {"available": True, "state": {}},
            "calibration": {"available": True, "state": calibration_state},
            "refuel_check": {"available": True, "state": refuel_state},
            "persistence": {
                "available": True,
                "state": {
                    "documents": {
                        "execution_calibrations.json": {
                            "document": {
                                "record_count": 1,
                                "manual_refuel_check_count": 1,
                            }
                        }
                    }
                },
            },
        }
    )
    assert reconciliation["status"] == "ok"


def test_stale_bundle_falls_back_to_current_contained_sidecar_without_writes(
    tmp_path,
):
    session_root = tmp_path / "session"
    experiments_root = session_root / "experiments"
    experiment_root = experiments_root / "experiment"
    experiment_root.mkdir(parents=True)
    plan_id = "11111111-1111-4111-8111-111111111111"
    sidecar_path = experiment_root / "execution_calibrations.json"
    save_execution_calibrations(
        sidecar_path,
        _execution_calibration_document(plan_id),
    )
    before = sidecar_path.read_bytes()
    stale_document = SimpleNamespace(
        schema_version=1,
        plan_id=plan_id,
        records={},
        manual_refuel_checks={},
    )
    stale_bundle = SimpleNamespace(
        plan=SimpleNamespace(plan_id=plan_id, plan_revision=3),
        calibrations=stale_document,
    )
    current_plan = SimpleNamespace(plan_id=plan_id, plan_revision=4)
    manager = SimpleNamespace(
        activeCalibration=None,
        calibration_queue=[],
        get_stream_calibration_sequence_state=lambda: {},
        get_droplet_calibration_sequence_state=lambda: {},
    )
    experiment = SimpleNamespace(
        experiment_dir_path=str(experiment_root),
        execution_calibrations_file_path=str(sidecar_path),
        get_execution_plan_snapshot=lambda: current_plan,
        applied_imaging_calibrations={"schema_version": 1, "records": {}},
        manual_refuel_checks={"schema_version": 1, "records": {}},
        _active_authoritative_execution_session=SimpleNamespace(
            bundle=stale_bundle
        ),
        _authoritative_execution_bundle=stale_bundle,
    )
    session = SimpleNamespace(
        session_root=session_root,
        application_roots=SimpleNamespace(experiments_root=experiments_root),
        components=SimpleNamespace(
            model=SimpleNamespace(
                experiment_model=experiment,
                calibration_manager=manager,
            )
        ),
    )
    projector = StateProjectionBuilder(session)

    calibration_state = projector._calibration_state()
    refuel_state = projector._refuel_state()

    assert len(calibration_state["applied_records"]) == 2
    assert len(refuel_state["records"]) == 1
    reconciliation = projector._reconcile(
        {
            "simulator": {"available": True, "state": {}},
            "model_machine": {"available": True, "state": {}},
            "calibration": {"available": True, "state": calibration_state},
            "refuel_check": {"available": True, "state": refuel_state},
            "persistence": {
                "available": True,
                "state": {
                    "documents": {
                        "execution_calibrations.json": {
                            "document": {
                                "record_count": 2,
                                "manual_refuel_check_count": 1,
                            }
                        }
                    }
                },
            },
        }
    )
    assert reconciliation["status"] == "ok"
    assert sidecar_path.read_bytes() == before


def test_current_sidecar_identity_and_schema_fail_closed(tmp_path):
    session_root = tmp_path / "session"
    experiments_root = session_root / "experiments"
    experiment_root = experiments_root / "experiment"
    experiment_root.mkdir(parents=True)
    plan_id = "11111111-1111-4111-8111-111111111111"
    other_plan_id = "22222222-2222-4222-8222-222222222222"
    sidecar_path = experiment_root / "execution_calibrations.json"
    manager = SimpleNamespace(
        activeCalibration=None,
        calibration_queue=[],
        get_stream_calibration_sequence_state=lambda: {},
        get_droplet_calibration_sequence_state=lambda: {},
    )
    experiment = SimpleNamespace(
        experiment_dir_path=str(experiment_root),
        execution_calibrations_file_path=str(sidecar_path),
        get_execution_plan_snapshot=lambda: SimpleNamespace(
            plan_id=plan_id,
            plan_revision=4,
        ),
        applied_imaging_calibrations={"schema_version": 1, "records": {}},
        manual_refuel_checks={"schema_version": 1, "records": {}},
        _active_authoritative_execution_session=None,
        _authoritative_execution_bundle=None,
    )
    session = SimpleNamespace(
        session_root=session_root,
        application_roots=SimpleNamespace(experiments_root=experiments_root),
        components=SimpleNamespace(
            model=SimpleNamespace(
                experiment_model=experiment,
                calibration_manager=manager,
            )
        ),
    )
    projector = StateProjectionBuilder(session)

    save_execution_calibrations(
        sidecar_path,
        _execution_calibration_document(other_plan_id),
    )
    mismatched_before = sidecar_path.read_bytes()
    with pytest.raises(ValueError, match="different plan ID"):
        projector._calibration_state()
    assert sidecar_path.read_bytes() == mismatched_before

    sidecar_path.write_text('{"schema_name":', encoding="utf-8")
    malformed_before = sidecar_path.read_bytes()
    with pytest.raises((ValueError, json.JSONDecodeError)):
        projector._calibration_state()
    assert sidecar_path.read_bytes() == malformed_before


def test_reconciliation_reports_controller_rack_and_persistence_domains():
    layers = {
        "simulator": {
            "available": True,
            "state": {
                "connected": False,
                "motors_enabled": False,
                "homed": False,
                "x": 0,
                "y": 0,
                "z": 0,
                "target_x": 0,
                "target_y": 0,
                "target_z": 0,
                "regulating_print_pressure": False,
                "regulating_refuel_pressure": False,
                "gripper_open": False,
                "current_command": 0,
                "last_completed": 0,
                "last_accepted": 0,
                "last_retired": 0,
                "command_depth": 0,
                "pause_after_seq32": 0,
                "pause_watermark_reached": False,
                "transport_paused": False,
            },
        },
        "model_machine": {
            "available": True,
            "state": {
                "machine_connected": False,
                "motors_enabled": False,
                "motors_homed": False,
                "current_x": 0,
                "current_y": 0,
                "current_z": 0,
                "target_x": 0,
                "target_y": 0,
                "target_z": 0,
                "regulating_print_pressure": False,
                "regulating_refuel_pressure": False,
                "gripper_open": False,
                "current_command_num": 0,
                "last_completed_command_num": 0,
                "last_accepted_command_num": 0,
                "last_retired_command_num": 0,
                "command_depth": 0,
                "pause_after_seq32": 0,
                "pause_watermark_reached": False,
                "transport_paused": False,
            },
        },
        "controller": {
            "available": True,
            "state": {
                "array_state": "running",
                "loaded_array": {"state": "not_started"},
            },
        },
        "ui": {
            "available": True,
            "state": {
                "primary_controls": [{"text": "Start Array", "enabled": True}]
            },
        },
        "rack_head": {
            "available": True,
            "state": {
                "slots": [
                    {
                        "slot": 1,
                        "confirmed": True,
                        "expected_printer_head": {
                            "printer_head_id": "head-1",
                            "stock_id": "stock-1",
                        },
                        "printer_head": {
                            "printer_head_id": "head-2",
                            "stock_id": "stock-2",
                        },
                    }
                ]
            },
        },
        "experiment": {
            "available": True,
            "state": {"plan": {"plan_id": "plan-1", "plan_revision": 2}},
        },
        "persistence": {
            "available": True,
            "state": {
                "documents": {
                    "execution_plan.json": {
                        "document": {"plan_id": "plan-1", "plan_revision": 1}
                    },
                    "execution_calibrations.json": {
                        "document": {
                            "record_count": 1,
                            "manual_refuel_check_count": 0,
                        }
                    },
                }
            },
        },
        "calibration": {
            "available": True,
            "state": {"applied_records": {}},
        },
        "refuel_check": {"available": True, "state": {"records": {}}},
    }

    reconciliation = StateProjectionBuilder._reconcile(layers)
    assert reconciliation["status"] == "mismatch"
    assert reconciliation["domains"]["simulator_model"] > 0
    assert reconciliation["domains"]["controller_ui"] == 2
    assert reconciliation["domains"]["rack_head"] == 1
    assert reconciliation["domains"]["experiment_persistence"] == 2
    assert reconciliation["domains"]["calibration_persistence"] == 2
    assert {item["domain"] for item in reconciliation["mismatches"]} == {
        "controller_ui",
        "rack_head",
        "experiment_persistence",
        "calibration_persistence",
    }


@pytest.mark.parametrize(
    ("array_state", "loaded_state", "text", "enabled"),
    [
        ("idle", "no_head", "Start Array", False),
        ("idle", "no_array", "No Array", False),
        ("idle", "not_started", "Start Array", True),
        ("idle", "in_progress", "Resume Print", True),
        ("resume_ready", "not_started", "Start Array", True),
        ("resume_ready", "in_progress", "Resume Print", True),
        ("idle", "complete", "Array Complete", False),
        ("idle", "unavailable", "Array Unavailable", False),
        ("running", "in_progress", "Stop After Well", True),
        ("stop_requested", "in_progress", "Stop Pending", False),
    ],
)
def test_reconciliation_projects_loaded_reagent_array_controls(
    array_state,
    loaded_state,
    text,
    enabled,
):
    reconciliation = StateProjectionBuilder._reconcile(
        {
            "simulator": {"available": True, "state": {}},
            "model_machine": {"available": True, "state": {}},
            "controller": {
                "available": True,
                "state": {
                    "array_state": array_state,
                    "loaded_array": {"state": loaded_state},
                },
            },
            "ui": {
                "available": True,
                "state": {
                    "primary_controls": [{"text": text, "enabled": enabled}]
                },
            },
        }
    )

    assert reconciliation["status"] == "ok"
    assert reconciliation["domains"]["controller_ui"] == 2


@pytest.mark.parametrize(
    ("array_state", "loaded_state", "terminal_code", "text", "enabled"),
    [
        ("idle", "in_progress", "terminal_aborted", "Experiment Aborted", False),
        ("resume_ready", "in_progress", "terminal_completed", "Experiment Complete", False),
        ("idle", "complete", "terminal_completed", "Array Complete", False),
        ("running", "in_progress", "terminal_aborted", "Stop After Well", True),
        ("stop_requested", "in_progress", "terminal_aborted", "Stop Pending", False),
    ],
)
def test_reconciliation_projects_terminal_plan_array_controls(
    array_state,
    loaded_state,
    terminal_code,
    text,
    enabled,
):
    reconciliation = StateProjectionBuilder._reconcile(
        {
            "simulator": {"available": True, "state": {}},
            "model_machine": {"available": True, "state": {}},
            "controller": {
                "available": True,
                "state": {
                    "array_state": array_state,
                    "loaded_array": {"state": loaded_state},
                    "print_array_terminal_guard": {
                        "blocked": terminal_code != "ok",
                        "code": terminal_code,
                    },
                },
            },
            "ui": {
                "available": True,
                "state": {
                    "primary_controls": [{"text": text, "enabled": enabled}]
                },
            },
        }
    )

    assert reconciliation["status"] == "ok"
    assert reconciliation["domains"]["controller_ui"] == 2
