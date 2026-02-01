# hardware/profile.py
from dataclasses import dataclass

@dataclass(frozen=True)
class HardwareProfile:
    name: str
    pressure_channels: int           # 2 for current, 1 for legacy
    has_log_channel: bool            # current True, legacy False
    has_droplet_camera: bool         # current True, legacy False
    has_refuel_camera: bool          # current True, legacy False
    has_mass_calibration: bool       # legacy True, current optional

    @property
    def has_refuel_pressure(self) -> bool:
        return self.pressure_channels >= 2

CURRENT_PROFILE = HardwareProfile(
    name="current",
    pressure_channels=2,
    has_log_channel=True,
    has_droplet_camera=True,
    has_refuel_camera=True,
    has_mass_calibration=False,   # keep your current workflow unchanged
)

LEGACY_PROFILE = HardwareProfile(
    name="legacy",
    pressure_channels=1,
    has_log_channel=False,
    has_droplet_camera=False,
    has_refuel_camera=False,
    has_mass_calibration=True,
)

def get_profile(name: str) -> HardwareProfile:
    n = (name or "").strip().lower()
    if n in ("legacy", "v1", "single"):
        return LEGACY_PROFILE
    return CURRENT_PROFILE