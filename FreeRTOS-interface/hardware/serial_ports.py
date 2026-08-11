"""Read-only serial-port identity helpers shared by hardware integrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping


MCU_LOG_EXPECTED_VID_PID = "10c4:ea60"
# An empty preference means: discover the sole CP2102 by exact USB identity.
DEFAULT_CURRENT_MCU_LOG_PORT = ""


class SerialPortValidationReason(str, Enum):
    INVALID_PATH = "invalid_path"
    DEVICE_NOT_FOUND = "device_not_found"
    METADATA_UNAVAILABLE = "metadata_unavailable"
    IDENTITY_MISMATCH = "identity_mismatch"
    CONFLICTING_IDENTITY = "conflicting_identity"
    NO_IDENTITY_MATCH = "no_identity_match"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"


class SerialPortSelectionMethod(str, Enum):
    EXPLICIT_PATH = "explicit_path"
    PREFERRED_PATH = "preferred_path"
    UNIQUE_IDENTITY = "unique_identity"
    UNIQUE_IDENTITY_FALLBACK = "unique_identity_fallback"


class SerialPortValidationError(RuntimeError):
    """Typed failure raised before a serial device is opened."""

    def __init__(
        self,
        reason: SerialPortValidationReason,
        detail: str,
        *,
        requested_path: str | None = None,
        expected_vid_pid: str | None = None,
        observed_vid_pid: str | None = None,
    ):
        super().__init__(str(detail))
        self.reason = reason
        self.detail = str(detail)
        self.requested_path = requested_path
        self.expected_vid_pid = expected_vid_pid
        self.observed_vid_pid = observed_vid_pid


@dataclass(frozen=True)
class SerialPortIdentity:
    requested_path: str
    system_device: str
    by_id_paths: tuple[str, ...]
    vid: str | None
    pid: str | None
    vid_pid: str | None
    description: str | None
    manufacturer: str | None
    product: str | None
    serial_number: str | None
    selection_method: SerialPortSelectionMethod = (
        SerialPortSelectionMethod.EXPLICIT_PATH
    )

    def __post_init__(self):
        if not self.requested_path or not self.system_device:
            raise ValueError("serial port paths must not be empty")
        if not isinstance(self.by_id_paths, tuple):
            raise TypeError("by_id_paths must be a tuple")
        if not isinstance(self.selection_method, SerialPortSelectionMethod):
            raise TypeError("selection_method must be SerialPortSelectionMethod")


def normalized_usb_id(value) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            return f"{int(value, 16):04x}"
        return f"{int(value):04x}"
    except (TypeError, ValueError):
        return None


def normalized_vid_pid(value: str) -> str:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError("expected VID:PID must use hhhh:hhhh format")
    vid = normalized_usb_id(parts[0])
    pid = normalized_usb_id(parts[1])
    if vid is None or pid is None:
        raise ValueError("expected VID:PID must use hexadecimal identifiers")
    return f"{vid}:{pid}"


def resolved_serial_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def serial_by_id_aliases(
    root: Path = Path("/dev/serial/by-id"),
    *,
    path_resolver: Callable[[str], str] = resolved_serial_path,
) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, list[str]] = {}
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return {}
    for entry in entries:
        try:
            resolved = path_resolver(str(entry))
        except OSError:
            continue
        aliases.setdefault(resolved, []).append(str(entry))
    return {key: tuple(values) for key, values in aliases.items()}


def resolve_explicit_usb_serial_port(
    requested_path: str,
    *,
    expected_vid_pid: str,
    port_infos: Iterable[object] | None = None,
    comports_fn: Callable[[], Iterable[object]] | None = None,
    path_resolver: Callable[[str], str] = resolved_serial_path,
    aliases_by_device: Mapping[str, tuple[str, ...]] | None = None,
) -> SerialPortIdentity:
    """Resolve and validate one caller-selected USB serial device without opening it."""

    explicit_path = str(requested_path or "").strip()
    if not explicit_path:
        raise SerialPortValidationError(
            SerialPortValidationReason.INVALID_PATH,
            "An explicit serial device path is required.",
            requested_path=explicit_path or None,
        )
    expected = normalized_vid_pid(expected_vid_pid)
    resolved_requested = path_resolver(explicit_path)
    if port_infos is None:
        if comports_fn is None:
            from serial.tools.list_ports import comports

            comports_fn = comports
        port_infos = tuple(comports_fn())
    else:
        port_infos = tuple(port_infos)

    matches = []
    for info in port_infos:
        device = str(getattr(info, "device", "") or "").strip()
        if device and path_resolver(device) == resolved_requested:
            matches.append(info)

    if not matches:
        raise SerialPortValidationError(
            SerialPortValidationReason.DEVICE_NOT_FOUND,
            f"Configured serial device {explicit_path!r} is not currently available.",
            requested_path=explicit_path,
            expected_vid_pid=expected,
        )
    if len(matches) != 1:
        raise SerialPortValidationError(
            SerialPortValidationReason.CONFLICTING_IDENTITY,
            f"Configured serial device {explicit_path!r} matched multiple port records.",
            requested_path=explicit_path,
            expected_vid_pid=expected,
        )

    info = matches[0]
    vid = normalized_usb_id(getattr(info, "vid", None))
    pid = normalized_usb_id(getattr(info, "pid", None))
    if vid is None or pid is None:
        raise SerialPortValidationError(
            SerialPortValidationReason.METADATA_UNAVAILABLE,
            f"USB identity metadata is unavailable for {explicit_path!r}.",
            requested_path=explicit_path,
            expected_vid_pid=expected,
        )
    observed = f"{vid}:{pid}"
    if observed != expected:
        raise SerialPortValidationError(
            SerialPortValidationReason.IDENTITY_MISMATCH,
            (
                f"Configured serial device {explicit_path!r} has USB identity "
                f"{observed}; expected {expected}."
            ),
            requested_path=explicit_path,
            expected_vid_pid=expected,
            observed_vid_pid=observed,
        )

    system_device = str(getattr(info, "device", "") or "").strip()
    if aliases_by_device is None:
        aliases_by_device = serial_by_id_aliases(path_resolver=path_resolver)
    aliases = tuple(aliases_by_device.get(resolved_requested, ()))
    if explicit_path.startswith("/dev/serial/by-id/") and explicit_path not in aliases:
        aliases = tuple(sorted((*aliases, explicit_path), key=str.casefold))
    return SerialPortIdentity(
        requested_path=explicit_path,
        system_device=system_device,
        by_id_paths=aliases,
        vid=vid,
        pid=pid,
        vid_pid=observed,
        description=str(getattr(info, "description", "") or "") or None,
        manufacturer=str(getattr(info, "manufacturer", "") or "") or None,
        product=str(getattr(info, "product", "") or "") or None,
        serial_number=str(getattr(info, "serial_number", "") or "") or None,
    )


def _identity_candidate_summary(port_infos: Iterable[object]) -> str:
    values = []
    for info in port_infos:
        device = str(getattr(info, "device", "") or "").strip() or "<unknown>"
        vid = normalized_usb_id(getattr(info, "vid", None))
        pid = normalized_usb_id(getattr(info, "pid", None))
        vid_pid = f"{vid}:{pid}" if vid and pid else "metadata-unavailable"
        serial_number = str(getattr(info, "serial_number", "") or "").strip()
        suffix = f", serial={serial_number}" if serial_number else ""
        values.append(f"{device} [{vid_pid}{suffix}]")
    return ", ".join(values) if values else "none"


def _preferred_connection_path(
    system_device: str,
    aliases_by_device: Mapping[str, tuple[str, ...]],
    *,
    path_resolver: Callable[[str], str],
) -> tuple[str, tuple[str, ...]]:
    resolved_device = path_resolver(system_device)
    aliases = tuple(
        sorted(aliases_by_device.get(resolved_device, ()), key=str.casefold)
    )
    return (aliases[0] if aliases else system_device), aliases


def resolve_preferred_usb_serial_port(
    preferred_path: str | None,
    *,
    expected_vid_pid: str,
    port_infos: Iterable[object] | None = None,
    comports_fn: Callable[[], Iterable[object]] | None = None,
    path_resolver: Callable[[str], str] = resolved_serial_path,
    aliases_by_device: Mapping[str, tuple[str, ...]] | None = None,
) -> SerialPortIdentity:
    """Select a preferred USB serial device or the sole exact identity match.

    Selection is read-only.  Product strings, enumeration order, and fuzzy
    matching never determine which device is opened.
    """

    if preferred_path is not None and not isinstance(preferred_path, str):
        raise SerialPortValidationError(
            SerialPortValidationReason.INVALID_PATH,
            "The preferred serial device path must be a string or None.",
            requested_path=None,
            expected_vid_pid=normalized_vid_pid(expected_vid_pid),
        )
    preferred = str(preferred_path or "").strip()
    expected = normalized_vid_pid(expected_vid_pid)
    if port_infos is None:
        if comports_fn is None:
            from serial.tools.list_ports import comports

            comports_fn = comports
        infos = tuple(comports_fn())
    else:
        infos = tuple(port_infos)
    if aliases_by_device is None:
        aliases_by_device = serial_by_id_aliases(path_resolver=path_resolver)

    preferred_failed = False
    if preferred:
        try:
            explicit = resolve_explicit_usb_serial_port(
                preferred,
                expected_vid_pid=expected,
                port_infos=infos,
                path_resolver=path_resolver,
                aliases_by_device=aliases_by_device,
            )
        except SerialPortValidationError:
            preferred_failed = True
        else:
            selected_path, aliases = _preferred_connection_path(
                explicit.system_device,
                aliases_by_device,
                path_resolver=path_resolver,
            )
            return SerialPortIdentity(
                requested_path=selected_path,
                system_device=explicit.system_device,
                by_id_paths=aliases,
                vid=explicit.vid,
                pid=explicit.pid,
                vid_pid=explicit.vid_pid,
                description=explicit.description,
                manufacturer=explicit.manufacturer,
                product=explicit.product,
                serial_number=explicit.serial_number,
                selection_method=SerialPortSelectionMethod.PREFERRED_PATH,
            )

    candidates_by_device: dict[str, object] = {}
    for info in infos:
        device = str(getattr(info, "device", "") or "").strip()
        if not device:
            continue
        vid = normalized_usb_id(getattr(info, "vid", None))
        pid = normalized_usb_id(getattr(info, "pid", None))
        if vid is None or pid is None or f"{vid}:{pid}" != expected:
            continue
        candidates_by_device.setdefault(path_resolver(device), info)

    candidates = tuple(candidates_by_device.values())
    if not candidates:
        raise SerialPortValidationError(
            SerialPortValidationReason.NO_IDENTITY_MATCH,
            (
                f"No attached serial device has required USB identity {expected}. "
                f"Discovered devices: {_identity_candidate_summary(infos)}."
            ),
            requested_path=preferred or None,
            expected_vid_pid=expected,
        )
    if len(candidates) > 1:
        raise SerialPortValidationError(
            SerialPortValidationReason.AMBIGUOUS_IDENTITY,
            (
                f"Multiple attached serial devices have USB identity {expected}; "
                "configure MACHINE_LOG_PORT to select one explicitly. "
                f"Matching devices: {_identity_candidate_summary(candidates)}."
            ),
            requested_path=preferred or None,
            expected_vid_pid=expected,
        )

    info = candidates[0]
    system_device = str(getattr(info, "device", "") or "").strip()
    selected_path, aliases = _preferred_connection_path(
        system_device,
        aliases_by_device,
        path_resolver=path_resolver,
    )
    vid = normalized_usb_id(getattr(info, "vid", None))
    pid = normalized_usb_id(getattr(info, "pid", None))
    return SerialPortIdentity(
        requested_path=selected_path,
        system_device=system_device,
        by_id_paths=aliases,
        vid=vid,
        pid=pid,
        vid_pid=f"{vid}:{pid}",
        description=str(getattr(info, "description", "") or "") or None,
        manufacturer=str(getattr(info, "manufacturer", "") or "") or None,
        product=str(getattr(info, "product", "") or "") or None,
        serial_number=str(getattr(info, "serial_number", "") or "") or None,
        selection_method=(
            SerialPortSelectionMethod.UNIQUE_IDENTITY_FALLBACK
            if preferred_failed
            else SerialPortSelectionMethod.UNIQUE_IDENTITY
        ),
    )


__all__ = [
    "DEFAULT_CURRENT_MCU_LOG_PORT",
    "MCU_LOG_EXPECTED_VID_PID",
    "SerialPortIdentity",
    "SerialPortSelectionMethod",
    "SerialPortValidationError",
    "SerialPortValidationReason",
    "normalized_usb_id",
    "normalized_vid_pid",
    "resolve_explicit_usb_serial_port",
    "resolve_preferred_usb_serial_port",
    "resolved_serial_path",
    "serial_by_id_aliases",
]
