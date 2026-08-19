from dataclasses import replace
from pathlib import Path

import pytest

import MachineData


MACHINE_UUID = "00000000-0000-0000-0000-000000000001"
MACHINE_ID = "LC-001"
ASSIGNED_AT = "2026-08-19T12:00:00Z"


def _resolve(tmp_path, **overrides):
    args = {
        "app_local_data_root": tmp_path / "app-local",
        "repo_root": tmp_path / "repo",
        "environment": {},
    }
    args.update(overrides)
    return MachineData.resolve_machine_data_base(**args)


def _canonical_identity_payload(**overrides):
    payload = {
        "schema_name": MachineData.MACHINE_IDENTITY_SCHEMA_NAME,
        "schema_version": MachineData.MACHINE_IDENTITY_SCHEMA_VERSION,
        "machine_id": MACHINE_ID,
        "machine_uuid": MACHINE_UUID,
        "assigned_at": ASSIGNED_AT,
        "notes": "qualification identity",
    }
    payload.update(overrides)
    return payload


def _legacy_identity_payload(**overrides):
    payload = {
        "machine_id": MACHINE_ID,
        "machine_uuid": MACHINE_UUID,
        "assigned_at": ASSIGNED_AT,
        "notes": "legacy identity",
    }
    payload.update(overrides)
    return payload


def _active_machine_payload(**overrides):
    payload = {
        "schema_name": MachineData.ACTIVE_MACHINE_SCHEMA_NAME,
        "schema_version": MachineData.ACTIVE_MACHINE_SCHEMA_VERSION,
        "machine_id": MACHINE_ID,
        "machine_uuid": MACHINE_UUID,
        "selected_at_utc": ASSIGNED_AT,
        "selection_source": "migration",
    }
    payload.update(overrides)
    return payload


def test_default_base_is_app_local_machine_data_and_has_no_side_effects(tmp_path):
    app_local = tmp_path / "not-created" / "app-local"

    resolved = _resolve(tmp_path, app_local_data_root=app_local)

    assert resolved.root == (app_local / MachineData.MACHINE_DATA_DIRNAME).resolve()
    assert resolved.active_machine_path == resolved.root / "active_machine.json"
    assert resolved.machines_root == resolved.root / "machines"
    assert not app_local.exists()
    assert not resolved.root.exists()


def test_explicit_root_takes_precedence_over_environment(tmp_path):
    explicit = tmp_path / "explicit-machine-data"
    environment = {
        MachineData.MACHINE_DATA_ROOT_ENV: str(tmp_path / "environment-machine-data")
    }

    resolved = _resolve(
        tmp_path,
        explicit_root=explicit,
        environment=environment,
    )

    assert resolved.root == explicit.resolve()


def test_environment_root_takes_precedence_over_default(tmp_path):
    environment_root = tmp_path / "environment-machine-data"

    resolved = _resolve(
        tmp_path,
        environment={MachineData.MACHINE_DATA_ROOT_ENV: str(environment_root)},
    )

    assert resolved.root == environment_root.resolve()


@pytest.mark.parametrize("value", ["relative/path", "", "."])
def test_relative_or_empty_explicit_root_is_rejected(tmp_path, value):
    with pytest.raises(MachineData.MachineDataPathError):
        _resolve(tmp_path, explicit_root=value)


def test_empty_environment_override_is_rejected(tmp_path):
    with pytest.raises(MachineData.MachineDataPathError):
        _resolve(
            tmp_path,
            environment={MachineData.MACHINE_DATA_ROOT_ENV: ""},
        )


def test_missing_app_local_root_without_override_is_rejected(tmp_path):
    with pytest.raises(MachineData.MachineDataPathError):
        _resolve(tmp_path, app_local_data_root="")


def test_filesystem_root_override_is_rejected(tmp_path):
    filesystem_root = Path(tmp_path.anchor)

    with pytest.raises(MachineData.MachineDataPathError, match="filesystem root"):
        _resolve(tmp_path, explicit_root=filesystem_root)


def test_user_home_override_is_rejected(tmp_path):
    with pytest.raises(MachineData.MachineDataPathError, match="user home"):
        _resolve(tmp_path, explicit_root=Path.home())


@pytest.mark.parametrize("suffix", [(), ("child",), ("child", "nested")])
def test_repo_or_repo_descendant_override_is_rejected(tmp_path, suffix):
    repo_root = tmp_path / "repo"
    candidate = repo_root.joinpath(*suffix)

    with pytest.raises(MachineData.MachineDataPathError, match="repository"):
        _resolve(tmp_path, repo_root=repo_root, explicit_root=candidate)


def test_same_app_local_root_is_independent_of_checkout(tmp_path):
    app_local = tmp_path / "app-local"

    first = _resolve(
        tmp_path,
        app_local_data_root=app_local,
        repo_root=tmp_path / "checkout-a",
    )
    second = _resolve(
        tmp_path,
        app_local_data_root=app_local,
        repo_root=tmp_path / "checkout-b",
    )

    assert first == second


@pytest.mark.parametrize(
    ("active_name", "machines_name"),
    [
        ("wrong.json", "machines"),
        ("active_machine.json", "wrong-machines"),
    ],
)
def test_base_paths_reject_inconsistent_direct_construction(
    tmp_path,
    active_name,
    machines_name,
):
    root = (tmp_path / "machine-data").resolve()

    with pytest.raises(MachineData.MachineDataPathError):
        MachineData.MachineDataBasePaths(
            root=root,
            active_machine_path=root / active_name,
            machines_root=root / machines_name,
        )


def test_build_machine_paths_uses_canonical_uuid_and_stays_contained(tmp_path):
    base = _resolve(tmp_path)

    paths = MachineData.build_machine_data_paths(
        base,
        "{00000000-0000-0000-0000-000000000001}",
    )

    assert paths.machine_uuid == MACHINE_UUID
    assert paths.machine_root == base.machines_root / MACHINE_UUID
    assert paths.config_root == paths.machine_root / "config"
    assert paths.calibration_memory_root == paths.machine_root / "CalibrationMemory"
    assert paths.calibration_root == paths.machine_root / "calibration"
    assert (
        paths.droplet_imager_optics_path
        == paths.calibration_root / "droplet_imager_optics.json"
    )
    assert (
        paths.regulator_optimization_root
        == paths.calibration_root / "regulator_optimization"
    )
    assert paths.identity_path == paths.metadata_root / "machine_identity.json"
    assert paths.verification_path == paths.metadata_root / "verification.json"
    assert paths.migration_receipt_path == paths.metadata_root / "migration_receipt.json"
    assert paths.configuration_events_root == paths.history_root / "configuration_events"
    assert paths.pending_transactions_root == paths.history_root / "pending_transactions"
    assert paths.configuration_lock_path == paths.locks_root / "configuration.lock"
    assert base.root in paths.configuration_lock_path.parents
    assert not paths.machine_root.exists()


def test_machine_paths_reject_inconsistent_direct_construction(tmp_path):
    paths = MachineData.build_machine_data_paths(_resolve(tmp_path), MACHINE_UUID)

    with pytest.raises(MachineData.MachineDataPathError, match="config_root"):
        replace(paths, config_root=tmp_path / "escaped-config")


@pytest.mark.parametrize("value", ["", "not-a-uuid", "../escape", None])
def test_build_machine_paths_rejects_invalid_uuid(tmp_path, value):
    base = _resolve(tmp_path)

    with pytest.raises(MachineData.MachineIdentityError):
        MachineData.build_machine_data_paths(base, value)


def test_parse_canonical_identity_and_serialize_exact_payload():
    payload = _canonical_identity_payload()

    identity = MachineData.parse_machine_identity(payload)

    assert identity.machine_id == MACHINE_ID
    assert identity.machine_uuid == MACHINE_UUID
    assert identity.assigned_at == ASSIGNED_AT
    assert identity.notes == "qualification identity"
    assert identity.to_payload() == payload


def test_parse_identity_canonicalizes_uuid_and_timestamp():
    payload = _canonical_identity_payload(
        machine_uuid="{00000000-0000-0000-0000-000000000001}",
        assigned_at="2026-08-19T12:00:00+00:00",
    )

    identity = MachineData.parse_machine_identity(payload)

    assert identity.machine_uuid == MACHINE_UUID
    assert identity.assigned_at == ASSIGNED_AT


def test_parse_legacy_identity_requires_explicit_permission():
    payload = _legacy_identity_payload()

    with pytest.raises(MachineData.MachineIdentityError, match="legacy"):
        MachineData.parse_machine_identity(payload)

    identity = MachineData.parse_machine_identity(payload, allow_legacy=True)
    assert identity.machine_id == MACHINE_ID
    assert identity.to_payload()["schema_name"] == MachineData.MACHINE_IDENTITY_SCHEMA_NAME


@pytest.mark.parametrize(
    "overrides",
    [
        {"machine_id": ""},
        {"machine_id": 123},
        {"machine_uuid": "bad"},
        {"assigned_at": ""},
        {"assigned_at": "not-a-time"},
        {"assigned_at": "2026-08-19T12:00:00-07:00"},
        {"notes": 123},
        {"schema_name": "unknown"},
        {"schema_version": 2},
        {"schema_version": True},
    ],
)
def test_parse_identity_rejects_invalid_canonical_payload(overrides):
    with pytest.raises(MachineData.MachineIdentityError):
        MachineData.parse_machine_identity(_canonical_identity_payload(**overrides))


def test_unassigned_identity_is_inspectable_but_not_activatable():
    payload = _legacy_identity_payload(machine_id=MachineData.UNASSIGNED_MACHINE_ID)

    with pytest.raises(MachineData.MachineIdentityError, match="unassigned"):
        MachineData.parse_machine_identity(payload, allow_legacy=True)

    identity = MachineData.parse_machine_identity(
        payload,
        allow_legacy=True,
        allow_unassigned=True,
    )
    assert identity.machine_id == MachineData.UNASSIGNED_MACHINE_ID


def test_identity_notes_default_to_empty_text():
    payload = _canonical_identity_payload()
    del payload["notes"]

    identity = MachineData.parse_machine_identity(payload)

    assert identity.notes == ""
    assert identity.to_payload()["notes"] == ""


def test_parse_active_machine_and_serialize_exact_payload():
    payload = _active_machine_payload()

    active = MachineData.parse_active_machine(payload)

    assert active.machine_id == MACHINE_ID
    assert active.machine_uuid == MACHINE_UUID
    assert active.selected_at_utc == ASSIGNED_AT
    assert active.selection_source == "migration"
    assert active.to_payload() == payload


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_name": "unknown"},
        {"schema_version": 2},
        {"schema_version": False},
        {"machine_id": ""},
        {"machine_id": MachineData.UNASSIGNED_MACHINE_ID},
        {"machine_uuid": "bad"},
        {"selected_at_utc": "not-a-time"},
        {"selection_source": "unknown"},
        {"selection_source": []},
    ],
)
def test_parse_active_machine_rejects_invalid_payload(overrides):
    with pytest.raises(MachineData.ActiveMachineError):
        MachineData.parse_active_machine(_active_machine_payload(**overrides))


@pytest.mark.parametrize(
    "source",
    sorted(MachineData.ACTIVE_MACHINE_SELECTION_SOURCES),
)
def test_active_machine_accepts_each_frozen_selection_source(source):
    active = MachineData.parse_active_machine(
        _active_machine_payload(selection_source=source)
    )
    assert active.selection_source == source


def test_machine_data_contract_module_has_no_qt_mvc_or_hardware_imports():
    source = Path("FreeRTOS-interface/MachineData.py").read_text(encoding="utf-8")

    for forbidden in (
        "PySide",
        "from App import",
        "from Model import",
        "from Controller import",
        "from View import",
        "Machine_FreeRTOS",
    ):
        assert forbidden not in source


def test_milestone_three_bootstrap_precedes_production_composition():
    app_source = Path("FreeRTOS-interface/App.py").read_text(encoding="utf-8")
    main_source = app_source.split("def main():", 1)[1]

    lock_index = main_source.index("app_lock = acquire_single_instance_lock")
    bootstrap_index = main_source.index("from MachineDataBootstrap import")
    composition_index = main_source.index("from ApplicationComposition import")
    assert lock_index < bootstrap_index < composition_index
    assert "get_machine_config_path(" not in main_source
