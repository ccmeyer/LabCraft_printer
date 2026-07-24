"""Fail-closed Raspberry Pi SIL preflight and artifact transport helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.virtual_workflows.compare import (  # noqa: E402
    load_baseline_summary,
    load_report_set,
    write_baseline_summary,
)
from tools.virtual_workflows.report import validate_report_v1  # noqa: E402


PI_PREFLIGHT_SCHEMA = "labcraft.pi_sil_preflight"
PI_HARDWARE_PROOF_SCHEMA = "labcraft.pi_sil_hardware_proof"
PI_ARTIFACT_MANIFEST_SCHEMA = "labcraft.pi_sil_artifact_bundle"
PI_SIL_SCHEMA_VERSION = 1
SANDBOX_METHOD = "bubblewrap_private_dev_v1"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "verification_reports" / "virtual_workflows"

FORBIDDEN_DEVICE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("serial_uart", r"/dev/(?:serial(?:/[^\"'\s,)]+)?|ttyAMA\d*|ttyS\d+|ttyUSB\d+|ttyACM\d+)"),
    ("gpio", r"/dev/gpiochip\d+|/sys/class/gpio(?:/|[\"'\s,)])"),
    ("camera", r"/dev/(?:video|media|v4l-subdev)\d+"),
    ("i2c", r"/dev/i2c-\d+"),
    ("usb_dfu", r"/dev/bus/usb/\d+/\d+"),
)


class PiSilError(RuntimeError):
    """Raised when Pi SIL safety, portability, or artifact checks fail."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PiSilError(f"could not load {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PiSilError(f"{source} must contain a JSON object")
    return payload


def _resolved_beneath(path: str | Path, root: str | Path) -> bool:
    candidate = Path(path).resolve()
    parent = Path(root).resolve()
    return candidate == parent or parent in candidate.parents


def _require_beneath(path: str | Path, root: str | Path, label: str) -> Path:
    candidate = Path(path).resolve()
    if not _resolved_beneath(candidate, root):
        raise PiSilError(f"{label} escaped its allowed root: {candidate}")
    return candidate


def _run_text(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> str:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PiSilError(f"could not run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise PiSilError(
            f"{command[0]} exited {result.returncode}: {detail or 'no output'}"
        )
    return result.stdout.strip()


def _read_pi_model() -> str:
    for candidate in (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    ):
        try:
            value = candidate.read_bytes().replace(b"\x00", b"").decode(
                "utf-8", errors="replace"
            ).strip()
        except OSError:
            continue
        if value:
            return value
    return "unknown"


def _qt_probe(repo_root: Path, qt_platform: str) -> dict[str, str]:
    script = (
        "import json, PySide6;"
        "from PySide6 import QtCore, QtGui, QtWidgets;"
        "app=QtWidgets.QApplication.instance() or QtWidgets.QApplication(['pi-sil-preflight']);"
        "print(json.dumps({'pyside_version':PySide6.__version__,"
        "'qt_version':QtCore.qVersion(),"
        "'platform':QtGui.QGuiApplication.platformName()}));"
        "app.quit()"
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = qt_platform
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    output = _run_text(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=environment,
        timeout=60.0,
    )
    try:
        payload = json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise PiSilError(f"Qt preflight returned invalid output: {output}") from exc
    if payload.get("platform") != qt_platform:
        raise PiSilError(
            f"Qt selected {payload.get('platform')!r}, expected {qt_platform!r}"
        )
    return {key: str(value) for key, value in payload.items()}


def _filesystem_identity(output_root: Path, repo_root: Path) -> dict[str, Any]:
    output = _run_text(
        ["findmnt", "-n", "-o", "FSTYPE,SOURCE", "-T", str(output_root)],
        cwd=repo_root,
    )
    parts = output.split(maxsplit=1)
    filesystem_type = parts[0] if parts else "unknown"
    source = parts[1] if len(parts) > 1 else "unknown"
    lowered = source.lower()
    storage_class = (
        "nvme"
        if "nvme" in lowered
        else "sd"
        if "mmc" in lowered
        else "usb"
        if any(token in lowered for token in ("usb", "sd"))
        else "other"
    )
    usage = shutil.disk_usage(output_root)
    return {
        "filesystem_type": filesystem_type,
        "storage_class": storage_class,
        "mount_source": source,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def _thermal_identity() -> dict[str, Any]:
    result: dict[str, Any] = {
        "temperature_c": None,
        "throttled_flags": None,
    }
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        result["temperature_c"] = int(thermal.read_text(encoding="ascii").strip()) / 1000
    except (OSError, ValueError):
        pass
    return result


def _atomic_storage_probe(output_root: Path) -> None:
    probe_dir = Path(
        tempfile.mkdtemp(prefix=".pi-sil-atomic-", dir=output_root)
    ).resolve()
    try:
        first = probe_dir / "first.tmp"
        final = probe_dir / "final.json"
        with first.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write('{"probe":true}\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(first, final)
        with final.open("rb") as handle:
            os.fsync(handle.fileno())
        if os.name != "nt":
            directory_fd = os.open(probe_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


@dataclass(frozen=True)
class PiSilPreflightResult:
    schema_name: str
    schema_version: int
    created_at_utc: str
    status: str
    sandbox_method: str
    repo_root: str
    output_root: str
    source_commit: str
    dirty_worktree: bool
    operating_system: str
    architecture: str
    pi_model: str
    python_version: str
    python_executable: str
    qt_platform: str
    pyside_version: str
    qt_version: str
    filesystem: Mapping[str, Any]
    thermal: Mapping[str, Any]
    requirements: Mapping[str, Any]


def run_pi_preflight(
    repo_root: str | Path,
    output_root: str | Path,
    *,
    qt_platform: str = "offscreen",
    require_pi: bool = True,
) -> PiSilPreflightResult:
    """Validate a Pi SIL host without opening any production hardware."""

    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    allowed = (root / "verification_reports" / "virtual_workflows").resolve()
    _require_beneath(output, allowed, "Pi SIL output root")
    output.mkdir(parents=True, exist_ok=True)

    system_name = platform.system()
    architecture = platform.machine()
    pi_model = _read_pi_model()
    if require_pi:
        if system_name != "Linux":
            raise PiSilError(f"Pi SIL requires Linux, found {system_name}")
        if architecture.lower() not in {"aarch64", "arm64"}:
            raise PiSilError(
                f"Pi SIL requires a 64-bit ARM userspace, found {architecture}"
            )
        if "raspberry pi" not in pi_model.lower():
            raise PiSilError(f"Pi SIL requires Raspberry Pi hardware, found {pi_model}")

    commands = {
        name: shutil.which(name)
        for name in ("bwrap", "strace", "findmnt")
    }
    missing = [name for name, path in commands.items() if path is None]
    if missing:
        raise PiSilError("missing Pi SIL commands: " + ", ".join(missing))
    try:
        import psutil
    except ImportError as exc:
        raise PiSilError("Pi SIL requires psutil in the selected environment") from exc

    ignored = _run_text(
        ["git", "check-ignore", output.relative_to(root).as_posix()],
        cwd=root,
    )
    if not ignored:
        raise PiSilError("Pi SIL output root is not ignored by Git")
    source_commit = _run_text(["git", "rev-parse", "HEAD"], cwd=root)
    dirty = bool(_run_text(["git", "status", "--porcelain"], cwd=root))
    _atomic_storage_probe(output)
    qt = _qt_probe(root, qt_platform)
    filesystem = _filesystem_identity(output, root)
    if int(filesystem["free_bytes"]) < 1024 * 1024 * 1024:
        raise PiSilError("Pi SIL requires at least 1 GiB free in the output filesystem")

    return PiSilPreflightResult(
        schema_name=PI_PREFLIGHT_SCHEMA,
        schema_version=PI_SIL_SCHEMA_VERSION,
        created_at_utc=_utc_now(),
        status="pass",
        sandbox_method=SANDBOX_METHOD,
        repo_root=str(root),
        output_root=str(output),
        source_commit=source_commit,
        dirty_worktree=dirty,
        operating_system=system_name,
        architecture=architecture,
        pi_model=pi_model,
        python_version=platform.python_version(),
        python_executable=str(Path(sys.executable).resolve()),
        qt_platform=qt_platform,
        pyside_version=qt["pyside_version"],
        qt_version=qt["qt_version"],
        filesystem=filesystem,
        thermal=_thermal_identity(),
        requirements={
            "commands": commands,
            "psutil_version": str(psutil.__version__),
            "private_dev_present": Path("/dev").is_dir(),
            "host_serial_visible": any(
                any(Path("/dev").glob(pattern))
                for pattern in ("ttyAMA*", "ttyUSB*", "ttyACM*")
            ),
        },
    )


def write_pi_preflight(
    path: str | Path, result: PiSilPreflightResult
) -> Path:
    return _write_json_atomic(path, asdict(result))


def validate_pi_preflight(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_name") != PI_PREFLIGHT_SCHEMA:
        raise PiSilError("unsupported Pi preflight schema")
    if payload.get("schema_version") != PI_SIL_SCHEMA_VERSION:
        raise PiSilError("unsupported Pi preflight schema version")
    if payload.get("status") != "pass":
        raise PiSilError("Pi preflight did not pass")
    if payload.get("sandbox_method") != SANDBOX_METHOD:
        raise PiSilError("Pi preflight sandbox method is incompatible")
    if payload.get("operating_system") != "Linux":
        raise PiSilError("Pi preflight operating system is not Linux")
    if str(payload.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        raise PiSilError("Pi preflight architecture is not 64-bit ARM")
    if "raspberry pi" not in str(payload.get("pi_model", "")).lower():
        raise PiSilError("Pi preflight model is not a Raspberry Pi")
    if payload.get("qt_platform") not in {"offscreen", "minimal"}:
        raise PiSilError("Pi preflight Qt platform is unsupported")
    filesystem = payload.get("filesystem")
    if not isinstance(filesystem, Mapping) or not filesystem.get("filesystem_type"):
        raise PiSilError("Pi preflight filesystem identity is incomplete")
    requirements = payload.get("requirements")
    if not isinstance(requirements, Mapping):
        raise PiSilError("Pi preflight requirements evidence is incomplete")
    if requirements.get("private_dev_present") is not True:
        raise PiSilError("Pi preflight did not run with a private /dev")
    if requirements.get("host_serial_visible") is not False:
        raise PiSilError("Pi preflight sandbox exposes a host serial device")


def _trace_matches(text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for name, expression in FORBIDDEN_DEVICE_PATTERNS:
        regex = re.compile(expression, re.IGNORECASE)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(
                    {
                        "interface": name,
                        "line_number": line_number,
                        "line": line[:1000],
                    }
                )
    return matches


@dataclass(frozen=True)
class PiSilHardwareProof:
    schema_name: str
    schema_version: int
    created_at_utc: str
    status: str
    sandbox_method: str
    preflight_path: str
    preflight_sha256: str
    trace_path: str
    trace_sha256: str
    audit_report_path: str
    audit_report_sha256: str
    source_commit: str
    qt_platform: str
    pi_model: str
    private_dev: bool
    root_read_only: bool
    network_unshared: bool
    forbidden_patterns: Sequence[Mapping[str, str]]
    forbidden_matches: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class PiSilArtifactManifest:
    schema_name: str
    schema_version: int
    created_at_utc: str
    repo_root: str
    report_set_path: str
    proof_path: str
    trace_path: str
    files: Sequence[Mapping[str, Any]]
    cleanup_roots: Sequence[str]


def validate_pi_hardware_trace(
    preflight_path: str | Path,
    trace_path: str | Path,
    audit_report_path: str | Path,
) -> PiSilHardwareProof:
    preflight_source = Path(preflight_path).resolve()
    trace_source = Path(trace_path).resolve()
    report_source = Path(audit_report_path).resolve()
    preflight = _read_json(preflight_source)
    validate_pi_preflight(preflight)
    report = _read_json(report_source)
    validate_report_v1(report)
    if report["classification"]["status"] == "fail":
        raise PiSilError("the traced Pi safety-audit scenario failed")
    if report["source"].get("git_commit") != preflight.get("source_commit"):
        raise PiSilError("the traced safety report source does not match preflight")
    if report["run"].get("run_mode") != f"{preflight['qt_platform']}_pi_sil":
        raise PiSilError("the traced safety report is not a Pi SIL run")
    report_environment = report["environment"]
    for field in ("operating_system", "architecture", "python_version"):
        if report_environment.get(field) != preflight.get(field):
            raise PiSilError(
                f"the traced safety report {field} does not match preflight"
            )
    if report_environment.get("qt", {}).get("platform") != preflight.get(
        "qt_platform"
    ):
        raise PiSilError("the traced safety report Qt platform does not match preflight")
    trace = trace_source.read_text(encoding="utf-8", errors="replace")
    matches = _trace_matches(trace)
    proof = PiSilHardwareProof(
        schema_name=PI_HARDWARE_PROOF_SCHEMA,
        schema_version=PI_SIL_SCHEMA_VERSION,
        created_at_utc=_utc_now(),
        status="fail" if matches else "pass",
        sandbox_method=SANDBOX_METHOD,
        preflight_path=str(preflight_source),
        preflight_sha256=_sha256(preflight_source),
        trace_path=str(trace_source),
        trace_sha256=_sha256(trace_source),
        audit_report_path=str(report_source),
        audit_report_sha256=_sha256(report_source),
        source_commit=str(preflight["source_commit"]),
        qt_platform=str(preflight["qt_platform"]),
        pi_model=str(preflight["pi_model"]),
        private_dev=True,
        root_read_only=True,
        network_unshared=True,
        forbidden_patterns=[
            {"interface": name, "pattern": expression}
            for name, expression in FORBIDDEN_DEVICE_PATTERNS
        ],
        forbidden_matches=matches,
    )
    if matches:
        raise PiSilError(
            "Pi hardware trace contains prohibited device access: "
            + ", ".join(sorted({str(item["interface"]) for item in matches}))
        )
    return proof


def write_pi_hardware_proof(
    path: str | Path, proof: PiSilHardwareProof
) -> Path:
    return _write_json_atomic(path, asdict(proof))


def validate_pi_hardware_proof(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_name") != PI_HARDWARE_PROOF_SCHEMA:
        raise PiSilError("unsupported Pi hardware-proof schema")
    if payload.get("schema_version") != PI_SIL_SCHEMA_VERSION:
        raise PiSilError("unsupported Pi hardware-proof schema version")
    if payload.get("status") != "pass":
        raise PiSilError("Pi hardware proof did not pass")
    if payload.get("sandbox_method") != SANDBOX_METHOD:
        raise PiSilError("Pi hardware-proof sandbox method is incompatible")
    if not all(
        payload.get(key) is True
        for key in ("private_dev", "root_read_only", "network_unshared")
    ):
        raise PiSilError("Pi hardware proof is missing sandbox protections")
    if payload.get("forbidden_matches") != []:
        raise PiSilError("Pi hardware proof contains forbidden access")


def load_and_validate_pi_evidence(
    preflight_path: str | Path,
    proof_path: str | Path,
    *,
    expected_qt_platform: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    preflight_source = Path(preflight_path).resolve()
    proof_source = Path(proof_path).resolve()
    preflight = _read_json(preflight_source)
    proof = _read_json(proof_source)
    validate_pi_preflight(preflight)
    validate_pi_hardware_proof(proof)
    if proof.get("preflight_sha256") != _sha256(preflight_source):
        raise PiSilError("Pi hardware proof does not match the preflight file")
    if proof.get("source_commit") != preflight.get("source_commit"):
        raise PiSilError("Pi hardware proof and preflight source commits differ")
    if preflight.get("qt_platform") != expected_qt_platform:
        raise PiSilError("Pi preflight Qt platform differs from the requested platform")
    if proof.get("qt_platform") != expected_qt_platform:
        raise PiSilError("Pi hardware proof Qt platform differs from the requested platform")
    for path_field, hash_field, label in (
        ("trace_path", "trace_sha256", "hardware trace"),
        ("audit_report_path", "audit_report_sha256", "safety-audit report"),
    ):
        evidence_path = Path(str(proof.get(path_field) or "")).resolve()
        if not evidence_path.is_file():
            raise PiSilError(f"Pi {label} is missing: {evidence_path}")
        if _sha256(evidence_path) != proof.get(hash_field):
            raise PiSilError(f"Pi {label} hash does not match the proof")
    return preflight, proof


def pi_report_identity(
    preflight: Mapping[str, Any],
    proof: Mapping[str, Any],
    proof_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return compatible report environment and safety additions."""

    filesystem = dict(preflight["filesystem"])
    filesystem.pop("free_bytes", None)
    filesystem.pop("total_bytes", None)
    environment = {
        "lane": "raspberry_pi_sil",
        "pi_model": preflight["pi_model"],
        "filesystem": filesystem,
    }
    safety = {
        "sandbox_method": SANDBOX_METHOD,
        "private_dev": True,
        "root_read_only": True,
        "network_unshared": True,
        "forbidden_access_attempt_count": 0,
        "proof_sha256": _sha256(proof_path),
        "trace_sha256": proof["trace_sha256"],
    }
    return environment, safety


def _iter_report_references(report_set: Mapping[str, Any]) -> Iterable[Path]:
    runs = report_set["runs"]
    for reference in list(runs["warmups"]) + list(runs["measured"]):
        yield Path(str(reference["path"])).resolve()


def _archive_sources(
    repo_root: Path,
    report_set_path: Path,
    proof_path: Path,
    trace_path: Path,
) -> tuple[list[Path], list[Path]]:
    previous_cwd = Path.cwd()
    try:
        os.chdir(repo_root)
        report_set = load_report_set(report_set_path)
    finally:
        os.chdir(previous_cwd)
    roots = [report_set_path.parent, proof_path.parent]
    roots.extend(path.parent for path in _iter_report_references(report_set))
    roots = sorted(set(path.resolve() for path in roots), key=str)
    allowed = (repo_root / "verification_reports" / "virtual_workflows").resolve()
    for root in roots:
        _require_beneath(root, allowed, "artifact root")
    _require_beneath(trace_path, allowed, "hardware trace")
    files: set[Path] = {proof_path.resolve(), trace_path.resolve()}
    for root in roots:
        for path in root.rglob("*"):
            if path.is_symlink():
                raise PiSilError(f"artifact bundle refuses symlink: {path}")
            if path.is_file():
                files.add(path.resolve())
    return sorted(files, key=str), roots


def build_pi_artifact_bundle(
    repo_root: str | Path,
    report_set_path: str | Path,
    proof_path: str | Path,
    trace_path: str | Path,
    output_path: str | Path,
) -> tuple[Path, Path]:
    root = Path(repo_root).resolve()
    report_set_source = Path(report_set_path).resolve()
    proof_source = Path(proof_path).resolve()
    trace_source = Path(trace_path).resolve()
    output = Path(output_path).resolve()
    allowed = (root / "verification_reports" / "virtual_workflows").resolve()
    _require_beneath(output, allowed, "artifact bundle")
    files, cleanup_roots = _archive_sources(
        root, report_set_source, proof_source, trace_source
    )
    entries = []
    for source in files:
        relative = source.relative_to(root).as_posix()
        entries.append(
            {
                "path": relative,
                "size_bytes": source.stat().st_size,
                "sha256": _sha256(source),
            }
        )
    manifest = {
        "schema_name": PI_ARTIFACT_MANIFEST_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "repo_root": str(root),
        "report_set_path": report_set_source.relative_to(root).as_posix(),
        "proof_path": proof_source.relative_to(root).as_posix(),
        "trace_path": trace_source.relative_to(root).as_posix(),
        "files": entries,
        "cleanup_roots": [
            path.relative_to(root).as_posix() for path in cleanup_roots
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise PiSilError(f"refusing to overwrite artifact bundle: {output}")
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for source, entry in zip(files, entries):
            archive.write(source, entry["path"])
        archive.writestr(
            "pi_sil_artifact_manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
    sidecar = _write_json_atomic(f"{output}.manifest.json", manifest)
    _write_json_atomic(
        f"{output}.sha256.json",
        {"path": output.name, "sha256": _sha256(output)},
    )
    return output, sidecar


def _safe_archive_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PiSilError(f"unsafe artifact archive path: {value}")
    return path


def _manifest_from_archive(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read("pi_sil_artifact_manifest.json")
        payload = json.loads(raw.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiSilError("artifact archive has no valid manifest") from exc
    if not isinstance(payload, dict):
        raise PiSilError("artifact manifest must be an object")
    if payload.get("schema_name") != PI_ARTIFACT_MANIFEST_SCHEMA:
        raise PiSilError("unsupported artifact manifest schema")
    if payload.get("schema_version") != PI_SIL_SCHEMA_VERSION:
        raise PiSilError("unsupported artifact manifest version")
    return payload


def extract_and_validate_pi_artifact_bundle(
    archive_path: str | Path,
    destination_repo_root: str | Path,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(archive_path).resolve()
    destination = Path(destination_repo_root).resolve()
    with zipfile.ZipFile(source, "r") as archive:
        manifest = _manifest_from_archive(archive)
        if manifest_path is not None:
            sidecar = _read_json(manifest_path)
            if sidecar != manifest:
                raise PiSilError(
                    "artifact archive manifest does not match its retrieved sidecar"
                )
        expected = {
            str(entry["path"]): entry
            for entry in manifest.get("files", [])
            if isinstance(entry, Mapping)
        }
        names = {
            info.filename
            for info in archive.infolist()
            if info.filename != "pi_sil_artifact_manifest.json"
        }
        if names != set(expected):
            raise PiSilError("artifact archive entries do not match its manifest")
        for info in archive.infolist():
            if info.filename == "pi_sil_artifact_manifest.json":
                continue
            relative = _safe_archive_path(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise PiSilError(f"artifact archive contains symlink: {info.filename}")
            target = destination.joinpath(*relative.parts).resolve()
            _require_beneath(target, destination, "artifact extraction target")
            if target.exists():
                raise PiSilError(f"refusing to overwrite local artifact: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(info.filename)
            entry = expected[info.filename]
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != int(entry["size_bytes"]) or digest != entry["sha256"]:
                raise PiSilError(f"artifact hash/size mismatch: {info.filename}")
            target.write_bytes(data)

    report_set_path = destination / str(manifest["report_set_path"])
    previous_cwd = Path.cwd()
    try:
        os.chdir(destination)
        load_report_set(report_set_path)
    finally:
        os.chdir(previous_cwd)
    proof = _read_json(destination / str(manifest["proof_path"]))
    validate_pi_hardware_proof(proof)
    extracted_trace = destination / str(manifest["trace_path"])
    if _sha256(extracted_trace) != proof.get("trace_sha256"):
        raise PiSilError("extracted hardware trace does not match the proof")
    manifest_hashes = {
        str(entry.get("sha256"))
        for entry in manifest.get("files", [])
        if isinstance(entry, Mapping)
    }
    for required_hash, label in (
        (proof.get("preflight_sha256"), "preflight"),
        (proof.get("audit_report_sha256"), "safety-audit report"),
    ):
        if required_hash not in manifest_hashes:
            raise PiSilError(f"artifact bundle is missing the proved {label}")
    return manifest


def cleanup_manifest_paths(
    manifest_path: str | Path,
    repo_root: str | Path,
    output_root: str | Path,
) -> list[Path]:
    """Remove only exact generated roots from a validated sidecar manifest."""

    manifest = _read_json(manifest_path)
    if manifest.get("schema_name") != PI_ARTIFACT_MANIFEST_SCHEMA:
        raise PiSilError("cleanup manifest schema is invalid")
    if manifest.get("schema_version") != PI_SIL_SCHEMA_VERSION:
        raise PiSilError("cleanup manifest version is invalid")
    root = Path(repo_root).resolve()
    allowed = Path(output_root).resolve()
    _require_beneath(allowed, root, "cleanup output root")
    removed: list[Path] = []
    candidates = sorted(
        {
            (root / str(relative)).resolve()
            for relative in manifest.get("cleanup_roots", [])
        },
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for candidate in candidates:
        _require_beneath(candidate, allowed, "cleanup target")
        if candidate == allowed:
            raise PiSilError("refusing to remove the Pi SIL output root")
        if candidate.exists():
            shutil.rmtree(candidate)
            removed.append(candidate)
    return removed


def install_candidate_baseline(
    source_path: str | Path,
    destination_path: str | Path,
) -> Path:
    """Validate and install a retrieved candidate baseline without overwrite."""

    payload = load_baseline_summary(source_path)
    if payload.get("threshold_maturity") != "candidate":
        raise PiSilError("Pi SIL may only install a candidate-maturity baseline")
    return write_baseline_summary(destination_path, payload, replace=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    preflight.add_argument("--output-root", type=Path, required=True)
    preflight.add_argument(
        "--qt-platform", choices=("offscreen", "minimal"), default="offscreen"
    )
    preflight.add_argument("--output", type=Path, required=True)

    trace = subparsers.add_parser("validate-trace")
    trace.add_argument("--preflight", type=Path, required=True)
    trace.add_argument("--trace", type=Path, required=True)
    trace.add_argument("--audit-report", type=Path, required=True)
    trace.add_argument("--output", type=Path, required=True)

    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    bundle.add_argument("--report-set", type=Path, required=True)
    bundle.add_argument("--proof", type=Path, required=True)
    bundle.add_argument("--trace", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--destination", type=Path, default=REPO_ROOT)
    extract.add_argument("--manifest", type=Path)

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--manifest", type=Path, required=True)
    cleanup.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    cleanup.add_argument("--output-root", type=Path, required=True)

    install = subparsers.add_parser("install-baseline")
    install.add_argument("--source", type=Path, required=True)
    install.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = run_pi_preflight(
                args.repo_root,
                args.output_root,
                qt_platform=args.qt_platform,
            )
            path = write_pi_preflight(args.output, result)
            print(f"Pi SIL preflight: {path}")
        elif args.command == "validate-trace":
            proof = validate_pi_hardware_trace(
                args.preflight, args.trace, args.audit_report
            )
            path = write_pi_hardware_proof(args.output, proof)
            print(f"Pi SIL hardware proof: {path}")
        elif args.command == "bundle":
            archive, manifest = build_pi_artifact_bundle(
                args.repo_root,
                args.report_set,
                args.proof,
                args.trace,
                args.output,
            )
            print(f"Pi SIL artifact bundle: {archive}")
            print(f"Pi SIL artifact manifest: {manifest}")
        elif args.command == "extract":
            manifest = extract_and_validate_pi_artifact_bundle(
                args.archive, args.destination, args.manifest
            )
            print(
                "Pi SIL report set: "
                f"{Path(args.destination).resolve() / manifest['report_set_path']}"
            )
        elif args.command == "cleanup":
            removed = cleanup_manifest_paths(
                args.manifest, args.repo_root, args.output_root
            )
            for path in removed:
                print(f"Removed remote Pi SIL artifact root: {path}")
        elif args.command == "install-baseline":
            path = install_candidate_baseline(args.source, args.destination)
            print(f"Installed Pi SIL candidate baseline: {path}")
        return 0
    except Exception as exc:
        print(f"Pi SIL error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "FORBIDDEN_DEVICE_PATTERNS",
    "PI_ARTIFACT_MANIFEST_SCHEMA",
    "PI_HARDWARE_PROOF_SCHEMA",
    "PI_PREFLIGHT_SCHEMA",
    "PI_SIL_SCHEMA_VERSION",
    "SANDBOX_METHOD",
    "PiSilArtifactManifest",
    "PiSilError",
    "PiSilHardwareProof",
    "PiSilPreflightResult",
    "build_pi_artifact_bundle",
    "cleanup_manifest_paths",
    "extract_and_validate_pi_artifact_bundle",
    "install_candidate_baseline",
    "load_and_validate_pi_evidence",
    "pi_report_identity",
    "run_pi_preflight",
    "validate_pi_hardware_proof",
    "validate_pi_hardware_trace",
    "validate_pi_preflight",
    "write_pi_hardware_proof",
    "write_pi_preflight",
]
