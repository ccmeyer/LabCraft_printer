import json
import shutil
from pathlib import Path

import MachineData
import MachineDataLock
import MachineDataMigration


MACHINE_UUID = "00000000-0000-0000-0000-000000000001"
MACHINE_ID = "LC-001"
MIGRATION_ID = "00000000-0000-0000-0000-000000000002"
FIXED_TIME = "2026-08-19T12:00:00Z"

PRESETS = Path("FreeRTOS-interface/Presets")
CALIBRATION_TEMPLATE = Path("FreeRTOS-interface/CalibrationMemory")
FIXTURE_RULES = json.loads(
    Path("tests/fixtures/machine_data_migration/cohort_fixture_rules.json").read_text(
        encoding="utf-8"
    )
)


def fixed_clock():
    return FIXED_TIME


def target_identity():
    return MachineData.parse_machine_identity(
        {
            "schema_name": MachineData.MACHINE_IDENTITY_SCHEMA_NAME,
            "schema_version": MachineData.MACHINE_IDENTITY_SCHEMA_VERSION,
            "machine_id": MACHINE_ID,
            "machine_uuid": MACHINE_UUID,
            "assigned_at": FIXED_TIME,
            "notes": "synthetic migration target",
        }
    )


def machine_data_paths(tmp_path):
    base = MachineData.resolve_machine_data_base(
        app_local_data_root=tmp_path / "app-local",
        repo_root=tmp_path / "repo",
        explicit_root=tmp_path / "external" / "machine-data",
        environment={},
    )
    return base, MachineData.build_machine_data_paths(base, MACHINE_UUID)


def write_candidate(
    root,
    *,
    cohort="v1.3.0-rc.1",
    custom_camera=False,
    calibration_memory=True,
    identity_payload=None,
    extra_files=None,
    optics=False,
    regulator_optimization=False,
):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rule = FIXTURE_RULES["cohorts"][cohort]
    for filename in MachineDataMigration.REQUIRED_CONFIG_NAMES:
        payload = json.loads((PRESETS / filename).read_text(encoding="utf-8"))
        if filename == "Settings.json":
            for key in rule["remove_settings_keys"]:
                payload.pop(key, None)
        if filename == "Locations.json" and custom_camera:
            payload["camera"] = dict(FIXTURE_RULES["custom_camera"])
        (root / filename).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    if calibration_memory:
        destination = root / "CalibrationMemory"
        for relative in MachineDataMigration.CALIBRATION_MEMORY_SEED_TYPES:
            source = CALIBRATION_TEMPLATE / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        run = destination / "runs" / "synthetic.json"
        run.parent.mkdir(parents=True, exist_ok=True)
        run.write_text('{"synthetic": true}\n', encoding="utf-8")
    if identity_payload is not None:
        (root / "machine_identity.json").write_text(
            json.dumps(identity_payload, indent=2) + "\n", encoding="utf-8"
        )
    if optics:
        (root / "droplet_imager_optics.json").write_text(
            '{"pixel_to_step": 1.25}\n', encoding="utf-8"
        )
    if regulator_optimization:
        optimization = root / "regulator_optimization" / "synthetic_run.json"
        optimization.parent.mkdir(parents=True, exist_ok=True)
        optimization.write_text('{"result": "synthetic"}\n', encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def write_wrapper(tmp_path, **kwargs):
    wrapper = tmp_path / "preserved-source"
    local_root = write_candidate(wrapper / "local", **kwargs)
    cohort = kwargs.get("cohort", "v1.3.0-rc.1")
    (wrapper / "VERSION").write_text(cohort + "\n", encoding="utf-8")
    return wrapper, local_root


def inspect_wrapper(wrapper):
    return MachineDataMigration.inspect_candidate(
        MachineDataMigration.CandidateSelection(
            MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
            wrapper,
            "synthetic preserved source",
        ),
        clock=fixed_clock,
    )


def migration_policy(**archive_overrides):
    return MachineDataMigration.MigrationPolicy(
        archive_policy=MachineDataMigration.ArchivePolicy(**archive_overrides),
        safety_margin_bytes=0,
    )


def publish_candidate(tmp_path, *, candidate=None, wrapper_kwargs=None):
    """Publish one synthetic copied-unverified tree for M3 contract tests."""

    if candidate is None:
        options = {"custom_camera": True}
        options.update(dict(wrapper_kwargs or {}))
        wrapper, _local = write_wrapper(
            Path(tmp_path) / "candidate",
            **options,
        )
        candidate = inspect_wrapper(wrapper)
    base, paths = machine_data_paths(Path(tmp_path))
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()
    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )
        result = MachineDataMigration.import_verified_candidate(
            candidate,
            backup,
            workspace=workspace,
            target_paths=paths,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    return base, paths, identity, candidate, result
