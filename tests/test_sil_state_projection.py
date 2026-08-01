import json
from pathlib import Path
from types import SimpleNamespace

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
        "controller": {"available": True, "state": {"array_state": "running"}},
        "ui": {
            "available": True,
            "state": {"primary_controls": [{"text": "Start Array"}]},
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
    assert reconciliation["domains"]["controller_ui"] == 1
    assert reconciliation["domains"]["rack_head"] == 1
    assert reconciliation["domains"]["experiment_persistence"] == 2
    assert reconciliation["domains"]["calibration_persistence"] == 2
    assert {item["domain"] for item in reconciliation["mismatches"]} == {
        "controller_ui",
        "rack_head",
        "experiment_persistence",
        "calibration_persistence",
    }
