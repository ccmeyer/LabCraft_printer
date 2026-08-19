"""Safe archive and evidence primitives for inert machine-data migration.

This module is deliberately standard-library-only.  It never imports Qt, the
application MVC, updater code, or hardware modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Iterator, Mapping, Sequence
from uuid import UUID


BACKUP_MANIFEST_SCHEMA_NAME = "labcraft.machine_backup_manifest"
BACKUP_MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_ZIP_COMPRESSION = frozenset(
    {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
)
_COPY_CHUNK_SIZE = 1024 * 1024
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class MachineDataArchiveError(ValueError):
    """Base error for unsafe or unverifiable archive input."""


class ArchiveSafetyError(MachineDataArchiveError):
    """Raised before following an unsafe source path or archive member."""


class ArchiveVerificationError(MachineDataArchiveError):
    """Raised when bytes do not match their recorded evidence."""


class SourceChangedDuringArchive(ArchiveVerificationError):
    """Raised when a live source member no longer matches inspected evidence."""


class ArchiveLimitError(ArchiveSafetyError):
    """Raised when a reviewed archive policy limit is exceeded."""


@dataclass(frozen=True)
class ArchivePolicy:
    max_files: int = 100_000
    max_member_bytes: int = 4 * 1024**3
    max_total_bytes: int = 20 * 1024**3
    max_compression_ratio: float = 200.0

    def __post_init__(self) -> None:
        if type(self.max_files) is not int or self.max_files <= 0:
            raise ValueError("max_files must be a positive integer.")
        if type(self.max_member_bytes) is not int or self.max_member_bytes <= 0:
            raise ValueError("max_member_bytes must be a positive integer.")
        if type(self.max_total_bytes) is not int or self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be a positive integer.")
        if isinstance(self.max_compression_ratio, bool) or not isinstance(
            self.max_compression_ratio, (int, float)
        ):
            raise ValueError("max_compression_ratio must be numeric.")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive.")

    def to_payload(self) -> dict[str, object]:
        return {
            "max_files": self.max_files,
            "max_member_bytes": self.max_member_bytes,
            "max_total_bytes": self.max_total_bytes,
            "max_compression_ratio": float(self.max_compression_ratio),
        }


@dataclass(frozen=True)
class FileEvidence:
    relative_path: str
    size: int
    raw_sha256: str
    semantic_json_sha256: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "relative_path": self.relative_path,
            "size": self.size,
            "raw_sha256": self.raw_sha256,
        }
        if self.semantic_json_sha256 is not None:
            payload["semantic_json_sha256"] = self.semantic_json_sha256
        return payload


@dataclass(frozen=True)
class SourceLocator:
    """A normalized legacy source that can be captured without extraction."""

    container_kind: str
    selected_path: Path
    local_root: Path | None = None
    version_path: Path | None = None
    zip_local_prefix: str | None = None
    zip_version_member: str | None = None

    def __post_init__(self) -> None:
        if self.container_kind not in {"directory", "zip"}:
            raise ArchiveSafetyError(
                f"Unsupported source container kind: {self.container_kind!r}"
            )
        selected = Path(self.selected_path).resolve(strict=False)
        object.__setattr__(self, "selected_path", selected)
        if self.container_kind == "directory":
            if self.local_root is None:
                raise ArchiveSafetyError("Directory sources require local_root.")
            object.__setattr__(
                self, "local_root", Path(self.local_root).resolve(strict=False)
            )
            if self.version_path is not None:
                object.__setattr__(
                    self,
                    "version_path",
                    Path(self.version_path).resolve(strict=False),
                )
        elif self.zip_local_prefix is None:
            raise ArchiveSafetyError("ZIP sources require zip_local_prefix.")


@dataclass(frozen=True)
class SourceMember:
    relative_path: str
    evidence: FileEvidence
    filesystem_path: Path | None = None
    zip_path: Path | None = None
    zip_member: str | None = None

    @contextmanager
    def open_binary(self) -> Iterator[BinaryIO]:
        if self.filesystem_path is not None:
            with self.filesystem_path.open("rb") as stream:
                yield stream
            return
        if self.zip_path is None or self.zip_member is None:
            raise ArchiveVerificationError(
                f"Source member has no readable locator: {self.relative_path}"
            )
        with zipfile.ZipFile(self.zip_path, "r") as archive:
            try:
                with archive.open(self.zip_member, "r") as stream:
                    yield stream
            except (KeyError, OSError, zipfile.BadZipFile) as exc:
                raise ArchiveVerificationError(
                    f"Cannot reopen ZIP member {self.zip_member!r}: {exc}"
                ) from exc


@dataclass(frozen=True)
class SourceSnapshot:
    locator: SourceLocator
    local_members: tuple[SourceMember, ...]
    local_directories: tuple[str, ...]
    version_member: SourceMember | None
    full_source_fingerprint: str
    total_local_bytes: int

    def local_member(self, relative_path: str) -> SourceMember:
        for member in self.local_members:
            if member.relative_path == relative_path:
                return member
        raise KeyError(relative_path)


@dataclass(frozen=True)
class VerifiedBackup:
    archive_path: Path
    archive_sha256: str
    manifest: Mapping[str, object]


class VerifiedBackupReader:
    """One-pass reader for an archive that was fully reverified on entry."""

    def __init__(self, backup: VerifiedBackup, archive: zipfile.ZipFile) -> None:
        self.backup = backup
        self._archive = archive
        self._expected = {
            str(item["archive_path"]): item for item in backup.manifest["members"]
        }

    def read(self, archive_member: str) -> bytes:
        item = self._expected.get(archive_member)
        if item is None:
            raise ArchiveVerificationError(
                f"Member is not present in verified manifest: {archive_member}"
            )
        try:
            data = self._archive.read(archive_member)
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ArchiveVerificationError(
                f"Cannot read verified member {archive_member}: {exc}"
            ) from exc
        if len(data) != item["size"] or sha256_bytes(data) != item["raw_sha256"]:
            raise ArchiveVerificationError(
                f"Verified member changed while reading: {archive_member}"
            )
        return data


class DurableFileOps:
    """Narrow durable-write adapter with deterministic fault checkpoints."""

    def __init__(
        self,
        fault_hook: Callable[[str, Path], None] | None = None,
    ) -> None:
        self._fault_hook = fault_hook
        self.directory_fsync_supported: bool | None = None

    def checkpoint(self, name: str, path: Path) -> None:
        if self._fault_hook is not None:
            self._fault_hook(name, Path(path))

    def fsync_file(self, path: Path) -> None:
        # Windows rejects fsync on a read-only CRT descriptor.  Reopen the
        # completed file read/write without changing its contents.
        with Path(path).open("r+b") as stream:
            os.fsync(stream.fileno())

    def fsync_directory(self, path: Path) -> bool:
        try:
            descriptor = os.open(str(path), os.O_RDONLY)
        except OSError:
            self.directory_fsync_supported = False
            return False
        try:
            os.fsync(descriptor)
        except OSError:
            self.directory_fsync_supported = False
            return False
        finally:
            os.close(descriptor)
        if self.directory_fsync_supported is None:
            self.directory_fsync_supported = True
        return True

    def atomic_write_json(
        self,
        path: Path,
        payload: Mapping[str, object],
        *,
        checkpoint_prefix: str,
    ) -> bool:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_bytes(payload) + b"\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        temporary = Path(temporary_name)
        try:
            self.checkpoint(f"before_{checkpoint_prefix}_write", target)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.checkpoint(f"after_{checkpoint_prefix}_fsync", target)
            os.replace(temporary, target)
            self.checkpoint(f"after_{checkpoint_prefix}_replace", target)
            directory_fsynced = self.fsync_directory(target.parent)
            reopened = json.loads(target.read_text(encoding="utf-8"))
            if reopened != dict(payload):
                raise ArchiveVerificationError(
                    f"Reopened JSON differs after atomic write: {target}"
                )
            return directory_fsynced
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise


def canonical_json_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArchiveVerificationError(f"Value is not canonical JSON: {exc}") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(_COPY_CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def sha256_file(path: Path) -> tuple[str, int]:
    with Path(path).open("rb") as stream:
        return sha256_stream(stream)


def semantic_json_sha256(payload: object) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def evidence_fingerprint(entries: Sequence[FileEvidence]) -> str:
    payload = [
        {
            "relative_path": item.relative_path,
            "size": item.size,
            "raw_sha256": item.raw_sha256,
        }
        for item in sorted(entries, key=lambda item: item.relative_path)
    ]
    return sha256_bytes(canonical_json_bytes(payload))


def _validate_relative_path(value: str, *, allow_directory: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise ArchiveSafetyError("Archive member path must not be empty.")
    if "\\" in value or value.startswith("/"):
        raise ArchiveSafetyError(f"Unsafe archive member path: {value!r}")
    trimmed = value[:-1] if allow_directory and value.endswith("/") else value
    if not trimmed:
        raise ArchiveSafetyError(f"Unsafe archive member path: {value!r}")
    pure = PurePosixPath(trimmed)
    parts = pure.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ArchiveSafetyError(f"Unsafe archive member path: {value!r}")
    if ":" in parts[0]:
        raise ArchiveSafetyError(f"Drive-qualified archive member: {value!r}")
    normalized = pure.as_posix()
    if normalized != trimmed:
        raise ArchiveSafetyError(f"Non-normal archive member path: {value!r}")
    return normalized


def _is_link_or_reparse(path: Path) -> bool:
    details = path.lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(
        attributes & _WINDOWS_REPARSE_POINT
    )


def _enforce_sizes(count: int, member_size: int, total: int, policy: ArchivePolicy) -> None:
    if count > policy.max_files:
        raise ArchiveLimitError(
            f"Source contains {count} files; limit is {policy.max_files}."
        )
    if member_size > policy.max_member_bytes:
        raise ArchiveLimitError(
            f"Source member is {member_size} bytes; limit is "
            f"{policy.max_member_bytes}."
        )
    if total > policy.max_total_bytes:
        raise ArchiveLimitError(
            f"Source totals {total} bytes; limit is {policy.max_total_bytes}."
        )


def _filesystem_members(
    root: Path, policy: ArchivePolicy
) -> tuple[tuple[SourceMember, ...], tuple[str, ...]]:
    root = Path(root)
    if not root.is_dir():
        raise ArchiveSafetyError(f"Selected local directory does not exist: {root}")
    if _is_link_or_reparse(root):
        raise ArchiveSafetyError(f"Selected local directory is a link/reparse point: {root}")

    members: list[SourceMember] = []
    directories: list[str] = []
    casefolded: dict[str, str] = {}
    total = 0

    def visit(directory: Path, relative_parent: PurePosixPath) -> None:
        nonlocal total
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            raise ArchiveSafetyError(f"Cannot enumerate source {directory}: {exc}") from exc
        for entry in entries:
            child = Path(entry.path)
            relative = (relative_parent / entry.name).as_posix()
            _validate_relative_path(relative)
            if entry.is_symlink() or _is_link_or_reparse(child):
                raise ArchiveSafetyError(f"Source contains link/reparse point: {relative}")
            folded = relative.casefold()
            previous = casefolded.get(folded)
            if previous is not None:
                raise ArchiveSafetyError(
                    f"Case-colliding source paths: {previous!r} and {relative!r}"
                )
            casefolded[folded] = relative
            if entry.is_dir(follow_symlinks=False):
                directories.append(relative)
                visit(child, relative_parent / entry.name)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ArchiveSafetyError(f"Source contains special file: {relative}")
            digest, size = sha256_file(child)
            total += size
            _enforce_sizes(len(members) + 1, size, total, policy)
            evidence = FileEvidence(relative, size, digest)
            members.append(
                SourceMember(
                    relative_path=relative,
                    evidence=evidence,
                    filesystem_path=child,
                )
            )

    visit(root, PurePosixPath())
    return (
        tuple(sorted(members, key=lambda item: item.relative_path)),
        tuple(sorted(directories)),
    )


def _validated_zip_infos(
    archive: zipfile.ZipFile,
    policy: ArchivePolicy,
) -> dict[str, zipfile.ZipInfo]:
    files: dict[str, zipfile.ZipInfo] = {}
    folded: dict[str, str] = {}
    total = 0
    for info in archive.infolist():
        normalized = _validate_relative_path(info.filename, allow_directory=True)
        key = normalized.casefold()
        if key in folded:
            raise ArchiveSafetyError(
                f"Duplicate/case-colliding ZIP members: {folded[key]!r} and "
                f"{info.filename!r}"
            )
        folded[key] = info.filename
        mode = (info.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode)
        if mode and kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ArchiveSafetyError(f"ZIP contains link/special member: {info.filename}")
        if info.flag_bits & 0x1:
            raise ArchiveSafetyError(f"Encrypted ZIP member is unsupported: {info.filename}")
        if info.compress_type not in SUPPORTED_ZIP_COMPRESSION:
            raise ArchiveSafetyError(
                f"Unsupported ZIP compression for member: {info.filename}"
            )
        if info.is_dir():
            continue
        total += info.file_size
        _enforce_sizes(len(files) + 1, info.file_size, total, policy)
        if info.file_size and info.file_size / max(info.compress_size, 1) > float(
            policy.max_compression_ratio
        ):
            raise ArchiveLimitError(
                f"ZIP compression ratio exceeds policy for: {info.filename}"
            )
        files[normalized] = info
    return files


def discover_zip_source(
    zip_path: Path,
    *,
    required_names: Sequence[str],
    policy: ArchivePolicy,
) -> SourceLocator:
    selected = Path(zip_path).resolve(strict=False)
    if not selected.is_file() or _is_link_or_reparse(selected):
        raise ArchiveSafetyError(f"Selected ZIP is missing or unsafe: {selected}")
    try:
        with zipfile.ZipFile(selected, "r") as archive:
            files = _validated_zip_infos(archive, policy)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveSafetyError(f"Invalid ZIP source {selected}: {exc}") from exc

    required = set(required_names)
    candidates: list[tuple[str, str | None]] = []
    if required.issubset(files):
        candidates.append(("", "VERSION" if "VERSION" in files else None))
    if {f"local/{name}" for name in required}.issubset(files):
        candidates.append(("local", "VERSION" if "VERSION" in files else None))
    wrappers = {
        parts[0]
        for name in files
        if len((parts := PurePosixPath(name).parts)) >= 3 and parts[1] == "local"
    }
    for wrapper in sorted(wrappers):
        prefix = f"{wrapper}/local"
        if {f"{prefix}/{name}" for name in required}.issubset(files):
            version = f"{wrapper}/VERSION"
            candidates.append((prefix, version if version in files else None))
    if len(candidates) != 1:
        raise ArchiveSafetyError(
            "ZIP must contain exactly one supported direct/local/wrapper candidate; "
            f"found {len(candidates)}."
        )
    prefix, version = candidates[0]
    allowed_prefix = f"{prefix}/" if prefix else ""
    allowed = {
        name
        for name in files
        if (allowed_prefix and name.startswith(allowed_prefix))
        or (not prefix and name != "VERSION")
    }
    if version is not None:
        allowed.add(version)
    unexpected = sorted(set(files) - allowed)
    if unexpected:
        raise ArchiveSafetyError(
            "ZIP contains files outside the selected local/VERSION layout: "
            + ", ".join(unexpected[:5])
        )
    return SourceLocator(
        container_kind="zip",
        selected_path=selected,
        zip_local_prefix=prefix,
        zip_version_member=version,
    )


def capture_source(locator: SourceLocator, policy: ArchivePolicy) -> SourceSnapshot:
    if locator.container_kind == "directory":
        assert locator.local_root is not None
        members, local_directories = _filesystem_members(locator.local_root, policy)
        version_member = None
        if locator.version_path is not None and locator.version_path.exists():
            version_path = locator.version_path
            if not version_path.is_file() or _is_link_or_reparse(version_path):
                raise ArchiveSafetyError(f"VERSION evidence is unsafe: {version_path}")
            digest, size = sha256_file(version_path)
            _enforce_sizes(len(members) + 1, size, sum(m.evidence.size for m in members) + size, policy)
            version_member = SourceMember(
                relative_path="VERSION",
                evidence=FileEvidence("VERSION", size, digest),
                filesystem_path=version_path,
            )
    else:
        try:
            with zipfile.ZipFile(locator.selected_path, "r") as archive:
                infos = _validated_zip_infos(archive, policy)
                prefix = locator.zip_local_prefix or ""
                marker = f"{prefix}/" if prefix else ""
                selected_infos = {
                    name: info
                    for name, info in infos.items()
                    if (marker and name.startswith(marker))
                    or (not prefix and name != "VERSION")
                }
                members_list: list[SourceMember] = []
                for archive_name, info in sorted(selected_infos.items()):
                    relative = archive_name[len(marker) :] if marker else archive_name
                    with archive.open(info, "r") as stream:
                        digest, size = sha256_stream(stream)
                    if size != info.file_size:
                        raise ArchiveVerificationError(
                            f"ZIP size changed while reading {archive_name!r}."
                        )
                    members_list.append(
                        SourceMember(
                            relative_path=relative,
                            evidence=FileEvidence(relative, size, digest),
                            zip_path=locator.selected_path,
                            zip_member=archive_name,
                        )
                    )
                members = tuple(members_list)
                directory_names: set[str] = set()
                for member in members:
                    parts = PurePosixPath(member.relative_path).parts
                    for length in range(1, len(parts)):
                        directory_names.add(PurePosixPath(*parts[:length]).as_posix())
                local_directories = tuple(sorted(directory_names))
                version_member = None
                if locator.zip_version_member is not None:
                    info = infos[locator.zip_version_member]
                    with archive.open(info, "r") as stream:
                        digest, size = sha256_stream(stream)
                    version_member = SourceMember(
                        relative_path="VERSION",
                        evidence=FileEvidence("VERSION", size, digest),
                        zip_path=locator.selected_path,
                        zip_member=locator.zip_version_member,
                    )
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ArchiveVerificationError(
                f"Cannot capture selected ZIP {locator.selected_path}: {exc}"
            ) from exc

    fingerprint_entries = [member.evidence for member in members]
    if version_member is not None:
        fingerprint_entries.append(version_member.evidence)
    return SourceSnapshot(
        locator=locator,
        local_members=members,
        local_directories=local_directories,
        version_member=version_member,
        full_source_fingerprint=evidence_fingerprint(fingerprint_entries),
        total_local_bytes=sum(member.evidence.size for member in members),
    )


def _copy_member_to_zip(
    archive: zipfile.ZipFile,
    archive_path: str,
    member: SourceMember,
) -> None:
    info = zipfile.ZipInfo(archive_path)
    # Generated backups use stored members so a legitimately repetitive local
    # file cannot make our own archive exceed the hostile-input ratio policy.
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    digest = hashlib.sha256()
    size = 0
    with member.open_binary() as source, archive.open(info, "w", force_zip64=True) as target:
        while True:
            chunk = source.read(_COPY_CHUNK_SIZE)
            if not chunk:
                break
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size != member.evidence.size or digest.hexdigest() != member.evidence.raw_sha256:
        raise SourceChangedDuringArchive(
            f"Source changed while archiving {member.relative_path!r}."
        )


def create_backup_archive(
    snapshot: SourceSnapshot,
    destination: Path,
    *,
    manifest_metadata: Mapping[str, object],
    policy: ArchivePolicy,
    io: DurableFileOps,
    firmware_artifact: Path | None = None,
) -> VerifiedBackup:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    member_payloads: list[dict[str, object]] = []
    try:
        io.checkpoint("before_backup_write", destination)
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for member in snapshot.local_members:
                archive_path = f"source/local/{member.relative_path}"
                io.checkpoint("before_backup_member", destination)
                _copy_member_to_zip(archive, archive_path, member)
                io.checkpoint("after_backup_member", destination)
                member_payloads.append(
                    {
                        "archive_path": archive_path,
                        "size": member.evidence.size,
                        "raw_sha256": member.evidence.raw_sha256,
                    }
                )
            if snapshot.version_member is not None:
                member = snapshot.version_member
                archive_path = "source/VERSION"
                _copy_member_to_zip(archive, archive_path, member)
                member_payloads.append(
                    {
                        "archive_path": archive_path,
                        "size": member.evidence.size,
                        "raw_sha256": member.evidence.raw_sha256,
                    }
                )
            firmware_payload = None
            if firmware_artifact is not None:
                firmware = Path(firmware_artifact).resolve(strict=False)
                if not firmware.is_file() or _is_link_or_reparse(firmware):
                    raise ArchiveSafetyError(
                        f"Firmware package evidence is missing or unsafe: {firmware}"
                    )
                digest, size = sha256_file(firmware)
                _enforce_sizes(len(member_payloads) + 1, size, sum(int(item["size"]) for item in member_payloads) + size, policy)
                firmware_member = SourceMember(
                    relative_path="firmware/LabCraft_firmware.bin",
                    evidence=FileEvidence(
                        "firmware/LabCraft_firmware.bin", size, digest
                    ),
                    filesystem_path=firmware,
                )
                archive_path = "source/firmware/LabCraft_firmware.bin"
                _copy_member_to_zip(archive, archive_path, firmware_member)
                member_payloads.append(
                    {"archive_path": archive_path, "size": size, "raw_sha256": digest}
                )
                firmware_payload = {
                    "archive_path": archive_path,
                    "raw_sha256": digest,
                    "evidence_kind": "package_artifact_not_installed_firmware_proof",
                }
            manifest = {
                "schema_name": BACKUP_MANIFEST_SCHEMA_NAME,
                "schema_version": BACKUP_MANIFEST_SCHEMA_VERSION,
                **dict(manifest_metadata),
                "members": sorted(member_payloads, key=lambda item: str(item["archive_path"])),
                "archive_policy": policy.to_payload(),
                "firmware_artifact": firmware_payload,
            }
            manifest_info = zipfile.ZipInfo("manifest.json")
            manifest_info.compress_type = zipfile.ZIP_STORED
            manifest_info.external_attr = (stat.S_IFREG | 0o600) << 16
            io.checkpoint("before_backup_manifest", destination)
            archive.writestr(manifest_info, canonical_json_bytes(manifest) + b"\n")
            io.checkpoint("after_backup_manifest", destination)
        io.fsync_file(temporary)
        io.checkpoint("after_backup_fsync", destination)
        os.replace(temporary, destination)
        io.checkpoint("after_backup_replace", destination)
        io.fsync_directory(destination.parent)
        io.checkpoint("before_backup_verification", destination)
        verified = verify_backup_archive(destination, policy=policy)
        io.checkpoint("after_backup_verification", destination)
        return verified
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _parse_manifest(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ArchiveVerificationError("Backup manifest must be a JSON object.")
    if payload.get("schema_name") != BACKUP_MANIFEST_SCHEMA_NAME:
        raise ArchiveVerificationError("Unknown backup manifest schema_name.")
    if type(payload.get("schema_version")) is not int or payload.get(
        "schema_version"
    ) != BACKUP_MANIFEST_SCHEMA_VERSION:
        raise ArchiveVerificationError("Unknown backup manifest schema_version.")
    members = payload.get("members")
    if not isinstance(members, list):
        raise ArchiveVerificationError("Backup manifest members must be a list.")
    try:
        UUID(str(payload.get("migration_id")))
    except ValueError as exc:
        raise ArchiveVerificationError("Backup manifest migration_id is invalid.") from exc
    for name in (
        "candidate_id",
        "required_config_fingerprint",
        "migratable_tree_fingerprint",
        "full_source_fingerprint",
    ):
        value = payload.get(name)
        if not isinstance(value, str) or len(value) != 64 or value != value.lower():
            raise ArchiveVerificationError(f"Backup manifest {name} is invalid.")
        try:
            int(value, 16)
        except ValueError as exc:
            raise ArchiveVerificationError(
                f"Backup manifest {name} is invalid."
            ) from exc
    for name in ("source_kind", "source_path"):
        if not isinstance(payload.get(name), str) or not payload.get(name):
            raise ArchiveVerificationError(f"Backup manifest {name} is required.")
    created = payload.get("created_at_utc")
    if not isinstance(created, str) or not created.endswith("Z"):
        raise ArchiveVerificationError("Backup manifest created_at_utc must be UTC.")
    try:
        parsed_created = datetime.fromisoformat(created[:-1] + "+00:00")
    except ValueError as exc:
        raise ArchiveVerificationError(
            "Backup manifest created_at_utc is invalid."
        ) from exc
    if parsed_created.utcoffset() != timedelta(0):
        raise ArchiveVerificationError("Backup manifest created_at_utc must be UTC.")
    recorded_policy = payload.get("archive_policy")
    if not isinstance(recorded_policy, dict):
        raise ArchiveVerificationError("Backup manifest archive_policy is invalid.")
    try:
        ArchivePolicy(**recorded_policy)
    except (TypeError, ValueError) as exc:
        raise ArchiveVerificationError("Backup manifest archive_policy is invalid.") from exc
    directory_fsync_supported = payload.get("directory_fsync_supported")
    if directory_fsync_supported is not None and type(directory_fsync_supported) is not bool:
        raise ArchiveVerificationError(
            "Backup manifest directory fsync capability is invalid."
        )
    return payload


def verify_backup_archive(
    archive_path: Path,
    *,
    policy: ArchivePolicy,
) -> VerifiedBackup:
    path = Path(archive_path).resolve(strict=False)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = _validated_zip_infos(archive, policy)
            if "manifest.json" not in infos:
                raise ArchiveVerificationError("Backup archive lacks manifest.json.")
            with archive.open(infos["manifest.json"], "r") as stream:
                manifest = _parse_manifest(json.load(stream))
            expected: dict[str, tuple[int, str]] = {}
            for entry in manifest["members"]:
                if not isinstance(entry, dict):
                    raise ArchiveVerificationError("Invalid backup member entry.")
                member_path = _validate_relative_path(entry.get("archive_path"))
                if not (
                    member_path.startswith("source/local/")
                    or member_path == "source/VERSION"
                    or member_path == "source/firmware/LabCraft_firmware.bin"
                ):
                    raise ArchiveVerificationError(
                        f"Unsupported backup member path: {member_path}"
                    )
                size = entry.get("size")
                digest = entry.get("raw_sha256")
                if type(size) is not int or size < 0:
                    raise ArchiveVerificationError("Invalid backup member size.")
                if not isinstance(digest, str) or len(digest) != 64:
                    raise ArchiveVerificationError("Invalid backup member SHA-256.")
                if member_path in expected:
                    raise ArchiveVerificationError("Duplicate backup manifest member.")
                expected[member_path] = (size, digest)
            source_fingerprint_entries: list[FileEvidence] = []
            for member_path, (size, digest) in expected.items():
                if member_path.startswith("source/local/"):
                    relative = member_path.removeprefix("source/local/")
                elif member_path == "source/VERSION":
                    relative = "VERSION"
                else:
                    continue
                source_fingerprint_entries.append(
                    FileEvidence(relative, size, digest)
                )
            if evidence_fingerprint(source_fingerprint_entries) != manifest.get(
                "full_source_fingerprint"
            ):
                raise ArchiveVerificationError(
                    "Backup full-source fingerprint differs from its member evidence."
                )
            actual_names = set(infos) - {"manifest.json"}
            if actual_names != set(expected):
                raise ArchiveVerificationError(
                    "Backup members differ from manifest: "
                    f"missing={sorted(set(expected) - actual_names)}, "
                    f"extra={sorted(actual_names - set(expected))}"
                )
            for member_path, (expected_size, expected_digest) in expected.items():
                with archive.open(infos[member_path], "r") as stream:
                    digest, size = sha256_stream(stream)
                if size != expected_size or digest != expected_digest:
                    raise ArchiveVerificationError(
                        f"Backup member hash/size mismatch: {member_path}"
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError, json.JSONDecodeError) as exc:
        if isinstance(exc, MachineDataArchiveError):
            raise
        raise ArchiveVerificationError(f"Cannot verify backup archive {path}: {exc}") from exc
    archive_digest, _ = sha256_file(path)
    return VerifiedBackup(path, archive_digest, manifest)


def read_verified_member(
    backup: VerifiedBackup,
    archive_member: str,
    *,
    policy: ArchivePolicy,
) -> bytes:
    current = verify_backup_archive(backup.archive_path, policy=policy)
    if current.archive_sha256 != backup.archive_sha256:
        raise ArchiveVerificationError("Backup archive changed after verification.")
    expected = {
        str(item["archive_path"]): item for item in current.manifest["members"]
    }
    if archive_member not in expected:
        raise ArchiveVerificationError(
            f"Member is not present in verified manifest: {archive_member}"
        )
    try:
        with zipfile.ZipFile(current.archive_path, "r") as archive:
            data = archive.read(archive_member)
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ArchiveVerificationError(
            f"Cannot read verified member {archive_member}: {exc}"
        ) from exc
    item = expected[archive_member]
    if len(data) != item["size"] or sha256_bytes(data) != item["raw_sha256"]:
        raise ArchiveVerificationError(
            f"Verified member changed while reading: {archive_member}"
        )
    return data


@contextmanager
def open_verified_backup(
    backup: VerifiedBackup,
    *,
    policy: ArchivePolicy,
) -> Iterator[VerifiedBackupReader]:
    current = verify_backup_archive(backup.archive_path, policy=policy)
    if current.archive_sha256 != backup.archive_sha256:
        raise ArchiveVerificationError("Backup archive changed after verification.")
    archive = zipfile.ZipFile(current.archive_path, "r")
    try:
        yield VerifiedBackupReader(current, archive)
    finally:
        archive.close()


__all__ = [
    "BACKUP_MANIFEST_SCHEMA_NAME",
    "BACKUP_MANIFEST_SCHEMA_VERSION",
    "ArchiveLimitError",
    "ArchivePolicy",
    "ArchiveSafetyError",
    "ArchiveVerificationError",
    "DurableFileOps",
    "FileEvidence",
    "MachineDataArchiveError",
    "SourceLocator",
    "SourceChangedDuringArchive",
    "SourceMember",
    "SourceSnapshot",
    "VerifiedBackup",
    "VerifiedBackupReader",
    "canonical_json_bytes",
    "capture_source",
    "create_backup_archive",
    "discover_zip_source",
    "evidence_fingerprint",
    "open_verified_backup",
    "read_verified_member",
    "semantic_json_sha256",
    "sha256_bytes",
    "sha256_file",
    "verify_backup_archive",
]
