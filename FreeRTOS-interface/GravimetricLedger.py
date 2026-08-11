"""Pure application-session accounting for gravimetric ejection provenance."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping


EJECTION_COMMAND_TYPES = frozenset({"DISPENSE", "DISPENSE_PRINT"})


class EjectionCommandLifecycle(Enum):
    QUEUED = "queued"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ImagingEjectionLifecycle(Enum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class EjectionCommandEvent:
    transport_epoch: int
    command_number: int
    command_type: str
    requested_droplet_count: int
    lifecycle: EjectionCommandLifecycle
    monotonic_ns: int

    def __post_init__(self):
        if self.transport_epoch < 0 or self.command_number < 0:
            raise ValueError("ejection event identifiers must be nonnegative")
        if self.requested_droplet_count < 1:
            raise ValueError("requested droplet count must be positive")
        if self.monotonic_ns < 0:
            raise ValueError("monotonic timestamp must be nonnegative")
        normalized = str(self.command_type or "").strip().upper()
        if normalized not in EJECTION_COMMAND_TYPES:
            raise ValueError(f"unsupported ejection command type: {self.command_type}")
        object.__setattr__(self, "command_type", normalized)
        if not isinstance(self.lifecycle, EjectionCommandLifecycle):
            raise TypeError("lifecycle must be EjectionCommandLifecycle")


@dataclass(frozen=True)
class ImagingEjectionEvent:
    transport_epoch: int
    capture_generation: int
    request_id: str | None
    attempt_index: int
    requested_droplet_count: int | None
    lifecycle: ImagingEjectionLifecycle
    monotonic_ns: int
    detail: str = ""

    def __post_init__(self):
        if self.transport_epoch < 0 or self.capture_generation < 0:
            raise ValueError("imaging ejection identifiers must be nonnegative")
        if self.attempt_index < 1:
            raise ValueError("imaging attempt index must be positive")
        if (
            self.requested_droplet_count is not None
            and self.requested_droplet_count < 0
        ):
            raise ValueError("imaging droplet count must be nonnegative or unknown")
        if self.monotonic_ns < 0:
            raise ValueError("monotonic timestamp must be nonnegative")
        if not isinstance(self.lifecycle, ImagingEjectionLifecycle):
            raise TypeError("lifecycle must be ImagingEjectionLifecycle")
        object.__setattr__(
            self,
            "request_id",
            None if self.request_id is None else str(self.request_id),
        )
        object.__setattr__(self, "detail", str(self.detail or ""))


@dataclass(frozen=True)
class EjectionLedgerSnapshot:
    attempt_generation: int
    completed_droplet_total: int
    uncertainty_generation: int
    command_attempt_generation: int = 0
    imaging_attempt_generation: int = 0
    serial_completed_droplet_total: int = 0
    imaging_acknowledged_droplet_total: int = 0

    def __post_init__(self):
        if min(
            self.attempt_generation,
            self.completed_droplet_total,
            self.uncertainty_generation,
            self.command_attempt_generation,
            self.imaging_attempt_generation,
            self.serial_completed_droplet_total,
            self.imaging_acknowledged_droplet_total,
        ) < 0:
            raise ValueError("ledger counters must be nonnegative")
        if self.completed_droplet_total != (
            self.serial_completed_droplet_total
            + self.imaging_acknowledged_droplet_total
        ):
            raise ValueError("combined completed total must equal its source totals")
        if self.attempt_generation != (
            self.command_attempt_generation + self.imaging_attempt_generation
        ):
            raise ValueError("combined attempt generation must equal its source totals")


@dataclass(frozen=True)
class ReusableMassBaseline:
    ending_mass_mg: str
    ending_mass_capture: Mapping[str, object]
    source_session_id: str
    ledger_snapshot: EjectionLedgerSnapshot
    created_monotonic_ns: int
    valid: bool = True
    invalidation_reason: str = ""

    def __post_init__(self):
        if not str(self.ending_mass_mg or "").strip():
            raise ValueError("ending mass must not be empty")
        if not str(self.source_session_id or "").strip():
            raise ValueError("source session id must not be empty")
        if self.created_monotonic_ns < 0:
            raise ValueError("creation timestamp must be nonnegative")
        if not isinstance(self.ledger_snapshot, EjectionLedgerSnapshot):
            raise TypeError("ledger_snapshot must be EjectionLedgerSnapshot")
        object.__setattr__(
            self,
            "ending_mass_capture",
            MappingProxyType(dict(self.ending_mass_capture or {})),
        )

    def invalidated(self, reason: str) -> "ReusableMassBaseline":
        return replace(
            self,
            valid=False,
            invalidation_reason=str(reason or "baseline invalidated"),
        )


class GravimetricEjectionLedger:
    """Deduplicates serial/GPIO ejection lifecycles and tracks uncertainty."""

    def __init__(self):
        self._attempt_generation = 0
        self._command_attempt_generation = 0
        self._imaging_attempt_generation = 0
        self._serial_completed_droplet_total = 0
        self._imaging_acknowledged_droplet_total = 0
        self._uncertainty_generation = 0
        self._commands: dict[tuple[int, int], dict[str, object]] = {}
        self._imaging_attempts: dict[tuple[int, int, str, int], dict[str, object]] = {}

    def snapshot(self) -> EjectionLedgerSnapshot:
        return EjectionLedgerSnapshot(
            attempt_generation=self._attempt_generation,
            completed_droplet_total=(
                self._serial_completed_droplet_total
                + self._imaging_acknowledged_droplet_total
            ),
            uncertainty_generation=self._uncertainty_generation,
            command_attempt_generation=self._command_attempt_generation,
            imaging_attempt_generation=self._imaging_attempt_generation,
            serial_completed_droplet_total=self._serial_completed_droplet_total,
            imaging_acknowledged_droplet_total=(
                self._imaging_acknowledged_droplet_total
            ),
        )

    def record(
        self,
        event: EjectionCommandEvent | ImagingEjectionEvent,
    ) -> EjectionLedgerSnapshot:
        if isinstance(event, EjectionCommandEvent):
            return self._record_command(event)
        if isinstance(event, ImagingEjectionEvent):
            return self._record_imaging(event)
        raise TypeError("event must be an ejection event")

    def _record_command(self, event: EjectionCommandEvent) -> EjectionLedgerSnapshot:
        key = (event.transport_epoch, event.command_number)
        state = self._commands.get(key)
        if state is None:
            state = {
                "count": event.requested_droplet_count,
                "queued": False,
                "accepted": False,
                "executing": False,
                "completed": False,
                "cancelled": False,
            }
            self._commands[key] = state
        elif int(state["count"]) != event.requested_droplet_count:
            self.mark_uncertain("conflicting ejection command identity")
            return self.snapshot()

        lifecycle = event.lifecycle
        if lifecycle is EjectionCommandLifecycle.QUEUED and not state["queued"]:
            state["queued"] = True
            self._attempt_generation += 1
            self._command_attempt_generation += 1
        elif lifecycle is EjectionCommandLifecycle.ACCEPTED:
            state["accepted"] = True
        elif lifecycle is EjectionCommandLifecycle.EXECUTING:
            state["accepted"] = True
            state["executing"] = True
        elif lifecycle is EjectionCommandLifecycle.COMPLETED and not state["completed"]:
            if not state["queued"]:
                state["queued"] = True
                self._attempt_generation += 1
                self._command_attempt_generation += 1
            state["accepted"] = True
            state["executing"] = True
            state["completed"] = True
            self._serial_completed_droplet_total += int(state["count"])
        elif lifecycle is EjectionCommandLifecycle.CANCELLED and not state["cancelled"]:
            state["cancelled"] = True
            if (state["accepted"] or state["executing"]) and not state["completed"]:
                self._uncertainty_generation += 1
        return self.snapshot()

    def _record_imaging(self, event: ImagingEjectionEvent) -> EjectionLedgerSnapshot:
        key = (
            event.transport_epoch,
            event.capture_generation,
            str(event.request_id or ""),
            event.attempt_index,
        )
        state = self._imaging_attempts.get(key)
        if state is None:
            state = {
                "count": event.requested_droplet_count,
                "triggered": False,
                "acknowledged": False,
                "uncertain": False,
            }
            self._imaging_attempts[key] = state
        elif state["count"] != event.requested_droplet_count:
            if not state["uncertain"]:
                state["uncertain"] = True
                self._uncertainty_generation += 1
            return self.snapshot()

        count = state["count"]
        if count == 0:
            return self.snapshot()

        lifecycle = event.lifecycle
        if lifecycle is ImagingEjectionLifecycle.TRIGGERED and not state["triggered"]:
            state["triggered"] = True
            self._attempt_generation += 1
            self._imaging_attempt_generation += 1
            if count is None and not state["uncertain"]:
                state["uncertain"] = True
                self._uncertainty_generation += 1
        elif lifecycle is ImagingEjectionLifecycle.ACKNOWLEDGED:
            if not state["triggered"]:
                state["triggered"] = True
                self._attempt_generation += 1
                self._imaging_attempt_generation += 1
            if count is None:
                if not state["uncertain"]:
                    state["uncertain"] = True
                    self._uncertainty_generation += 1
            elif not state["acknowledged"]:
                state["acknowledged"] = True
                self._imaging_acknowledged_droplet_total += int(count)
        elif lifecycle is ImagingEjectionLifecycle.UNCERTAIN:
            if not state["triggered"]:
                state["triggered"] = True
                self._attempt_generation += 1
                self._imaging_attempt_generation += 1
            if not state["uncertain"]:
                state["uncertain"] = True
                self._uncertainty_generation += 1
        return self.snapshot()

    def mark_uncertain(self, _reason: str = "") -> EjectionLedgerSnapshot:
        self._uncertainty_generation += 1
        return self.snapshot()

    def begin_transport_epoch(self, _reason: str = "") -> EjectionLedgerSnapshot:
        unresolved_commands = any(
            (state["accepted"] or state["executing"]) and not state["completed"]
            for state in self._commands.values()
        )
        unresolved_imaging = any(
            state["triggered"] and not state["acknowledged"] and state["count"] != 0
            for state in self._imaging_attempts.values()
        )
        if unresolved_commands or unresolved_imaging:
            self._uncertainty_generation += 1
        return self.snapshot()

    @staticmethod
    def reusable_since(
        baseline: EjectionLedgerSnapshot,
        current: EjectionLedgerSnapshot,
    ) -> bool:
        return (
            current.attempt_generation == baseline.attempt_generation
            and current.uncertainty_generation == baseline.uncertainty_generation
        )
