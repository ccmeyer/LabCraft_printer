"""Pure pulse-aware synthetic ejection response for hardware-isolated SIL."""

from __future__ import annotations

from dataclasses import dataclass
import math


PULSE_EJECTION_RESPONSE_MODEL_ID = "labcraft.sil_pulse_ejection_response"
PULSE_EJECTION_RESPONSE_MODEL_VERSION = 1

DROPLET_PULSE_WIDTH_RANGE_US = (1300, 1800)
STREAM_PULSE_WIDTH_RANGE_US = (2500, 10000)
DROPLET_DEFAULT_PULSE_WIDTH_US = DROPLET_PULSE_WIDTH_RANGE_US[0]
STREAM_DEFAULT_PULSE_WIDTH_US = STREAM_PULSE_WIDTH_RANGE_US[0]


class SyntheticEjectionResponseError(ValueError):
    """Raised when a pulse width cannot produce a supported synthetic response."""


@dataclass(frozen=True)
class PulseAwareSyntheticEjectionModelV1:
    """Versioned deterministic response with no claim of physical accuracy."""

    model_id: str = PULSE_EJECTION_RESPONSE_MODEL_ID
    model_version: int = PULSE_EJECTION_RESPONSE_MODEL_VERSION

    @staticmethod
    def normalize_mode(mode: object) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized not in {"droplet", "stream"}:
            raise SyntheticEjectionResponseError(
                "printing mode must be droplet or stream"
            )
        return normalized

    def pulse_width_range_us(self, mode: object) -> tuple[int, int]:
        normalized = self.normalize_mode(mode)
        return (
            DROPLET_PULSE_WIDTH_RANGE_US
            if normalized == "droplet"
            else STREAM_PULSE_WIDTH_RANGE_US
        )

    def default_pulse_width_us(self, mode: object) -> int:
        return self.pulse_width_range_us(mode)[0]

    def supports(self, mode: object, pulse_width_us: object) -> bool:
        try:
            if isinstance(pulse_width_us, bool):
                return False
            pulse = int(pulse_width_us)
            if float(pulse_width_us) != pulse:
                return False
            low, high = self.pulse_width_range_us(mode)
        except (TypeError, ValueError, SyntheticEjectionResponseError):
            return False
        return low <= pulse <= high

    def predict_volume_nl(self, mode: object, pulse_width_us: object) -> float:
        normalized = self.normalize_mode(mode)
        if isinstance(pulse_width_us, bool):
            raise SyntheticEjectionResponseError("pulse width must be an integer")
        try:
            numeric = float(pulse_width_us)
            pulse = int(pulse_width_us)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SyntheticEjectionResponseError(
                "pulse width must be an integer"
            ) from exc
        if not math.isfinite(numeric) or numeric != pulse:
            raise SyntheticEjectionResponseError("pulse width must be an integer")
        low, high = self.pulse_width_range_us(normalized)
        if not low <= pulse <= high:
            raise SyntheticEjectionResponseError(
                f"{normalized} pulse width must be between {low} and {high} us"
            )
        if normalized == "droplet":
            volume = 9.0 + (pulse - 1300) * 9.0 / 500.0
        else:
            volume = 60.0 + (pulse - 2500) * 190.0 / 7500.0
        return round(volume, 9)
