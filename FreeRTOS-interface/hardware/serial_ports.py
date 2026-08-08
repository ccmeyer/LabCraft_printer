"""Read-only serial-port identity helpers shared by hardware integrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping


MCU_LOG_EXPECTED_VID_PID = "10c4:ea60"
DEFAULT_CURRENT_MCU_LOG_PORT = (
    "/dev/serial/by-id/"
    "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
)


class SerialPortValidationReason(str, Enum):
    INVALID_PATH = "invalid_path"
    DEVICE_NOT_FOUND = "device_not_found"
    METADATA_UNAVAILABLE = "metadata_unavailable"
    IDENTITY_MISMATCH = "identity_mismatch"
    CONFLICTING_IDENTITY = "conflicting_identity"


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

    def __post_init__(self):
        if not self.requested_path or not self.system_device:
            raise ValueError("serial port paths must not be empty")
        if not isinstance(self.by_id_paths, tuple):
            raise TypeError("by_id_paths must be a tuple")


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


__all__ = [
    "DEFAULT_CURRENT_MCU_LOG_PORT",
    "MCU_LOG_EXPECTED_VID_PID",
    "SerialPortIdentity",
    "SerialPortValidationError",
    "SerialPortValidationReason",
    "normalized_usb_id",
    "normalized_vid_pid",
    "resolve_explicit_usb_serial_port",
    "resolved_serial_path",
    "serial_by_id_aliases",
]
