import re
from pathlib import Path

import Machine_FreeRTOS as mfr


def _firmware_cmd_map():
    text = Path("firmware/Core/Inc/Orchestrator.h").read_text(encoding="utf-8")
    pairs = re.findall(r"\b(CMD_[A-Z0-9_]+)\s*=\s*0[xX]([0-9A-Fa-f]+)", text)
    return {name: int(hexv, 16) for name, hexv in pairs}


def test_shared_command_codes_match_firmware_header():
    fw = _firmware_cmd_map()
    shared = {
        "RELATIVE_X": "CMD_MOVE_X",
        "RELATIVE_Y": "CMD_MOVE_Y",
        "RELATIVE_Z": "CMD_MOVE_Z",
        "ABSOLUTE_X": "CMD_ABS_X",
        "ABSOLUTE_Y": "CMD_ABS_Y",
        "ABSOLUTE_Z": "CMD_ABS_Z",
        "ABSOLUTE_XY": "CMD_ABS_XY",
        "OPEN_GRIPPER": "CMD_GRIPPER_OPEN",
        "CLOSE_GRIPPER": "CMD_GRIPPER_CLOSE",
        "GRIPPER_OFF": "CMD_GRIPPER_OFF",
        "DISPENSE": "CMD_DISPENSE",
        "DISPENSE_PRINT": "CMD_DISPENSE_PRINT",
        "DISPENSE_REFUEL": "CMD_DISPENSE_REFUEL",
        "SET_AXIS_MAXSPEED": "CMD_SET_AXIS_MAXSPEED",
        "SET_AXIS_ACCEL": "CMD_SET_AXIS_ACCEL",
        "HOME_XY": "CMD_HOME_XY",
        "HOME_PR_BOTH": "CMD_HOME_PR_BOTH",
        "WAIT": "CMD_WAIT",
        "ENABLE_PRINT_PROFILE": "CMD_ENABLE_PRINT_PROFILE",
        "DISABLE_PRINT_PROFILE": "CMD_DISABLE_PRINT_PROFILE",
    }

    for py_name, fw_name in shared.items():
        assert mfr.CMD_MAP[py_name] == fw[fw_name], f"Mismatch: {py_name} vs {fw_name}"


def test_ack_and_control_codes_match_firmware_header():
    fw = _firmware_cmd_map()
    assert mfr.HELLO == fw["CMD_HELLO"]
    assert mfr.HELLO_ACK == fw["CMD_HELLO_ACK"]
    assert mfr.GOODBYE == fw["CMD_GOODBYE"]
    assert mfr.BYE_ACK == fw["CMD_BYE_ACK"]
    assert mfr.CLEAR_QUEUE == fw["CMD_CLEAR"]
    assert mfr.CLEAR_ACK == fw["CMD_CLEAR_ACK"]
    assert mfr.BYE_DONE == fw["CMD_BYE_DONE"]
    assert mfr.RESET_REPORT == fw["CMD_RESET_REPORT"]
