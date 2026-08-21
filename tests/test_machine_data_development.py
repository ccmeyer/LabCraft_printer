import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ApplicationComposition
import MachineData
import MachineDataDevelopment


MACHINE_UUID = "00000000-0000-0000-0000-000000000001"
ACTIVATION_ID = "00000000-0000-0000-0000-000000000002"
MIGRATION_ID = "00000000-0000-0000-0000-000000000003"
STORE_ID = "00000000-0000-0000-0000-000000000004"
SESSION_ID = "00000000-0000-0000-0000-000000000005"
FIXED_TIME = "2026-08-20T12:00:00Z"


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "production-machine-data"
    machine_root = root / "machines" / MACHINE_UUID
    (machine_root / "config").mkdir(parents=True)
    (machine_root / "config" / "Locations.json").write_text(
        '{"camera":{"X":1,"Y":2,"Z":3}}\n', encoding="utf-8"
    )
    pointer = MachineData.ActiveMachine(
        machine_id="LC-001",
        machine_uuid=MACHINE_UUID,
        selected_at_utc=FIXED_TIME,
        selection_source="migration",
        activation_id=ACTIVATION_ID,
        migration_id=MIGRATION_ID,
        activation_receipt_sha256="a" * 64,
    )
    (root / "active_machine.json").write_text(
        json.dumps(pointer.to_payload(), indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def _prepare(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "development-machine-data"
    store = MachineDataDevelopment.prepare_development_store(
        source,
        target,
        repo_root=tmp_path / "repo",
        operator="Test Operator",
        app_commit="b" * 40,
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: STORE_ID,
    )
    return source, target, store


def test_prepare_development_store_is_exact_disjoint_and_never_overlays(tmp_path):
    source, target, store = _prepare(tmp_path)

    assert store.root == target.resolve()
    assert store.source_machine_data_root == source.resolve()
    assert store.store_id == STORE_ID
    assert (target / "active_machine.json").read_bytes() == (
        source / "active_machine.json"
    ).read_bytes()
    assert (
        target / "machines" / MACHINE_UUID / "config" / "Locations.json"
    ).read_bytes() == (
        source / "machines" / MACHINE_UUID / "config" / "Locations.json"
    ).read_bytes()
    assert (target / MachineDataDevelopment.DEVELOPMENT_STORE_FILENAME).is_file()

    with pytest.raises(
        MachineDataDevelopment.DevelopmentStoreError,
        match="already exists",
    ):
        MachineDataDevelopment.prepare_development_store(
            source,
            target,
            repo_root=tmp_path / "repo",
            operator="Test Operator",
            app_commit="b" * 40,
        )


def test_prepare_rejects_repo_targets_and_development_sources(tmp_path):
    source, target, _store = _prepare(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(
        MachineDataDevelopment.DevelopmentStoreError,
        match="outside the repository",
    ):
        MachineDataDevelopment.prepare_development_store(
            source,
            repo / "machine-data",
            repo_root=repo,
            operator="Operator",
            app_commit="c" * 40,
        )
    with pytest.raises(
        MachineDataDevelopment.DevelopmentStoreError,
        match="cannot be used as production",
    ):
        MachineDataDevelopment.prepare_development_store(
            target,
            tmp_path / "second-development",
            repo_root=repo,
            operator="Operator",
            app_commit="c" * 40,
        )


def test_development_environment_defaults_to_no_hardware_and_requires_exact_ack(
    tmp_path, monkeypatch
):
    _source_root, target, store = _prepare(tmp_path)
    environment = {
        MachineDataDevelopment.DEVELOPMENT_MODE_ENV: "development",
        MachineDataDevelopment.DEVELOPMENT_OPERATOR_ENV: "Attending Operator",
    }

    launch = MachineDataDevelopment.development_launch_from_environment(
        target, environment
    )
    assert launch is not None
    assert launch.store == store
    assert launch.hardware_enabled is False

    environment[MachineDataDevelopment.DEVELOPMENT_HARDWARE_ENV] = "1"
    with pytest.raises(
        MachineDataDevelopment.DevelopmentStoreError,
        match="exact attended confirmation",
    ):
        MachineDataDevelopment.development_launch_from_environment(
            target, environment
        )
    environment[MachineDataDevelopment.DEVELOPMENT_HARDWARE_CONFIRMATION_ENV] = (
        MachineDataDevelopment.DEVELOPMENT_HARDWARE_CONFIRMATION
    )
    with pytest.raises(
        MachineDataDevelopment.DevelopmentStoreError,
        match="clear-envelope",
    ):
        MachineDataDevelopment.development_launch_from_environment(target, environment)
    environment[MachineDataDevelopment.DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION_ENV] = (
        MachineDataDevelopment.DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION
    )
    environment[MachineDataDevelopment.DEVELOPMENT_EXPECTED_COMMIT_ENV] = "c" * 40
    environment[MachineDataDevelopment.DEVELOPMENT_HARDWARE_AUTHORIZATION_ENV] = str(
        tmp_path / "authorization.json"
    )
    monkeypatch.setattr(
        MachineDataDevelopment,
        "validate_authorization",
        lambda *_args, **_kwargs: {"authorization_id": SESSION_ID},
    )
    attended = MachineDataDevelopment.development_launch_from_environment(
        target, environment
    )
    assert attended.hardware_enabled is True
    assert attended.hardware_authorization_id == SESSION_ID


def test_development_session_binds_exact_commit_pointer_marker_and_operator(tmp_path):
    _source_root, target, _store = _prepare(tmp_path)
    launch = MachineDataDevelopment.development_launch_from_environment(
        target,
        {
            MachineDataDevelopment.DEVELOPMENT_MODE_ENV: "development",
            MachineDataDevelopment.DEVELOPMENT_OPERATOR_ENV: "Operator",
        },
    )
    path = MachineDataDevelopment.record_development_session(
        launch,
        app_version="v1.3.0-rc.4",
        app_commit="d" * 40,
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: SESSION_ID,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["session_id"] == SESSION_ID
    assert payload["app_commit"] == "d" * 40
    assert payload["operator"] == "Operator"
    assert payload["hardware_enabled"] is False
    assert len(payload["active_pointer_sha256"]) == 64
    assert len(payload["development_store_marker_sha256"]) == 64

    runtime_path = MachineDataDevelopment.record_no_hardware_runtime_evidence(
        path,
        app_commit="d" * 40,
        machine_type="SimulatedMachine",
        runtime_mode="development",
        identity_text="DEVELOPMENT BUILD — NO HARDWARE CONNECTED",
        hardware_access_allowed=False,
        updater_access_allowed=False,
        peripheral_factories={
            "serial": "blocked_serial_access",
            "refuel_camera": "blocked_refuel_camera_access",
            "droplet_camera": "blocked_droplet_camera_access",
            "log_reader": "blocked_log_reader_access",
            "balance": "blocked_balance_access",
            "experimental_balance": "blocked_experimental_balance_access",
            "legacy_calibration": "blocked_legacy_calibration_hardware_access",
        },
        clock=lambda: FIXED_TIME,
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert runtime["schema_name"] == "labcraft.development_no_hardware_runtime"
    assert runtime["session_id"] == SESSION_ID
    assert runtime["machine_type"] == "SimulatedMachine"
    assert runtime["hardware_access_allowed"] is False
    assert runtime["updater_access_allowed"] is False
    assert len(runtime["session_evidence_sha256"]) == 64


def test_runtime_evidence_rejects_hardware_capable_composition(tmp_path):
    _source_root, target, _store = _prepare(tmp_path)
    launch = MachineDataDevelopment.development_launch_from_environment(
        target,
        {
            MachineDataDevelopment.DEVELOPMENT_MODE_ENV: "development",
            MachineDataDevelopment.DEVELOPMENT_OPERATOR_ENV: "Operator",
        },
    )
    session = MachineDataDevelopment.record_development_session(
        launch,
        app_version="v1.3.0-dev",
        app_commit="d" * 40,
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: SESSION_ID,
    )
    with pytest.raises(
        MachineDataDevelopment.DevelopmentStoreError,
        match="not no-hardware safe",
    ):
        MachineDataDevelopment.record_no_hardware_runtime_evidence(
            session,
            app_commit="d" * 40,
            machine_type="Machine",
            runtime_mode="development",
            identity_text="ATTENDED DEVELOPMENT BUILD — HARDWARE ENABLED",
            hardware_access_allowed=True,
            updater_access_allowed=False,
            peripheral_factories={
                name: f"blocked_{name}"
                for name in (
                    "serial", "refuel_camera", "droplet_camera", "log_reader",
                    "balance", "experimental_balance", "legacy_calibration",
                )
            },
        )


def test_development_dependencies_are_visibly_isolated_and_block_hardware(tmp_path):
    base = SimpleNamespace(root=tmp_path / "development-machine-data")
    machine_root = base.root / "machines" / MACHINE_UUID
    paths = SimpleNamespace(
        base=base,
        config_root=machine_root / "config",
        calibration_memory_root=machine_root / "CalibrationMemory",
        droplet_imager_optics_path=machine_root / "calibration" / "optics.json",
        regulator_optimization_root=machine_root / "calibration" / "regulator",
        identity_path=machine_root / "metadata" / "machine_identity.json",
    )
    authorized = SimpleNamespace(paths=paths)

    dependencies = ApplicationComposition.development_dependencies(
        authorized, hardware_enabled=False
    )
    assert dependencies.runtime_context.is_development is True
    assert dependencies.runtime_context.is_simulation is True
    assert dependencies.runtime_context.hardware_access_allowed is False
    assert dependencies.runtime_context.updater_access_allowed is False
    assert dependencies.roots.config_root == paths.config_root
    assert dependencies.roots.experiments_root == (
        base.root / "development_runtime" / "experiments"
    )
    with pytest.raises(ApplicationComposition.HardwareAccessBlocked):
        dependencies.serial_factory()

    attended = ApplicationComposition.development_dependencies(
        authorized, hardware_enabled=True
    )
    assert attended.runtime_context.is_development is True
    assert attended.runtime_context.is_simulation is False
    assert attended.runtime_context.hardware_access_allowed is True
    assert attended.runtime_context.updater_access_allowed is False
