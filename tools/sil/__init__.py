"""Interactive software-in-the-loop session support."""

from .calibration_application import SyntheticCalibrationApplicationAdapter
from .manual_refuel import (
    SIMULATED_MANUAL_REFUEL_OUTCOMES,
    SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION,
    SIMULATED_MANUAL_REFUEL_SOURCE,
    SimulatedManualRefuelOutcomeAdapter,
)

from .state_recorder import (
    EVENT_SCHEMA_ID,
    SNAPSHOT_SCHEMA_ID,
    STATE_SCHEMA_VERSION,
    StateRecorder,
    StateRecorderConfigV1,
    StateRecorderError,
)
from .synthetic_calibration import (
    CALIBRATION_REQUEST_SCHEMA_ID,
    CALIBRATION_RESULT_SCHEMA_ID,
    CALIBRATION_SCHEMA_VERSION,
    SYNTHETIC_CALIBRATION_PROVIDER_VERSION,
    CalibrationApplicationError,
    CalibrationContractError,
    CalibrationGenerationRequestV1,
    CalibrationGenerationResultV1,
    SyntheticCalibrationProfileV1,
    SyntheticCalibrationProvider,
)

__all__ = [
    "SyntheticCalibrationApplicationAdapter",
    "SIMULATED_MANUAL_REFUEL_OUTCOMES",
    "SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION",
    "SIMULATED_MANUAL_REFUEL_SOURCE",
    "SimulatedManualRefuelOutcomeAdapter",
    "EVENT_SCHEMA_ID",
    "SNAPSHOT_SCHEMA_ID",
    "STATE_SCHEMA_VERSION",
    "StateRecorder",
    "StateRecorderConfigV1",
    "StateRecorderError",
    "CALIBRATION_REQUEST_SCHEMA_ID",
    "CALIBRATION_RESULT_SCHEMA_ID",
    "CALIBRATION_SCHEMA_VERSION",
    "SYNTHETIC_CALIBRATION_PROVIDER_VERSION",
    "CalibrationApplicationError",
    "CalibrationContractError",
    "CalibrationGenerationRequestV1",
    "CalibrationGenerationResultV1",
    "SyntheticCalibrationProfileV1",
    "SyntheticCalibrationProvider",
]
