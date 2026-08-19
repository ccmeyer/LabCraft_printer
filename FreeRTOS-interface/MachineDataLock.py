"""Qt-backed UUID-scoped lock adapter for inert machine-data migration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile

from MachineData import (
    MachineDataBasePaths,
    MachineDataPathError,
    build_machine_data_paths,
)


class MigrationLockError(RuntimeError):
    """Base error for migration-lock acquisition or ownership."""


class MigrationLockUnavailable(MigrationLockError):
    def __init__(self, lock_path: Path, owner_info: tuple[object, ...] | None) -> None:
        self.lock_path = Path(lock_path)
        self.owner_info = owner_info
        detail = f" Owner information: {owner_info!r}." if owner_info else ""
        super().__init__(f"Migration lock is unavailable: {self.lock_path}.{detail}")


class AcquiredMigrationLock:
    """Owned lock token required by the migration core."""

    def __init__(self, machine_uuid: str, path: Path, lock: QLockFile) -> None:
        self.machine_uuid = machine_uuid
        self.path = Path(path).resolve(strict=False)
        self._lock = lock
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def assert_owns(self, machine_uuid: str, expected_path: Path) -> None:
        if self._released:
            raise MigrationLockError("Migration lock has already been released.")
        if self.machine_uuid != machine_uuid:
            raise MigrationLockError(
                "Migration lock UUID does not match the target machine UUID."
            )
        if self.path != Path(expected_path).resolve(strict=False):
            raise MigrationLockError(
                "Migration lock path does not match the target workspace lock."
            )

    def release(self) -> None:
        if not self._released:
            self._lock.unlock()
            self._released = True

    def __enter__(self) -> "AcquiredMigrationLock":
        if self._released:
            raise MigrationLockError("Cannot re-enter a released migration lock.")
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


def migration_lock_path(base: MachineDataBasePaths, machine_uuid: str) -> Path:
    """Return the base-scoped lock path without creating it."""

    if not isinstance(base, MachineDataBasePaths):
        raise MachineDataPathError("base must be a MachineDataBasePaths value.")
    canonical_uuid = build_machine_data_paths(base, machine_uuid).machine_uuid
    path = (base.root / "locks" / f"migration-{canonical_uuid}.lock").resolve(
        strict=False
    )
    if base.root not in path.parents:
        raise MachineDataPathError(f"Migration lock escaped machine-data base: {path}")
    return path


def acquire_migration_lock(
    base: MachineDataBasePaths,
    machine_uuid: str,
) -> AcquiredMigrationLock:
    """Acquire immediately; never remove an uncertain stale lock automatically."""

    path = migration_lock_path(base, machine_uuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        owner_info = None
        try:
            info = lock.getLockInfo()
            if isinstance(info, tuple):
                owner_info = tuple(info)
        except Exception:
            owner_info = None
        raise MigrationLockUnavailable(path, owner_info)
    return AcquiredMigrationLock(
        build_machine_data_paths(base, machine_uuid).machine_uuid,
        path,
        lock,
    )


__all__ = [
    "AcquiredMigrationLock",
    "MigrationLockError",
    "MigrationLockUnavailable",
    "acquire_migration_lock",
    "migration_lock_path",
]
