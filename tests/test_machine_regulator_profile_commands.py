from types import SimpleNamespace

import Machine_FreeRTOS as mfr


VALID_RECOVERY = {
    "active_ticks": 2,
    "base_boost_hz": 300,
    "pulse_coeff_hz_per_us": 1,
    "pressure_coeff_hz_per_raw": 0,
    "max_boost_hz": 1500,
    "recovery_floor_hz": 0,
    "recovery_exit_error_raw": 3,
    "max_extend_ticks": 0,
    "allow_extend_while_undershoot": False,
    "boost_only_when_undershoot": True,
    "linear_decay": True,
}


def _machine(test_profile):
    return mfr.Machine(SimpleNamespace(), profile=test_profile)


def test_recovery_helper_queues_three_chunks_with_commit_on_final(qapp, test_profile):
    machine = _machine(test_profile)
    callback = object()
    kwargs = {"done": True}

    commands = machine.set_regulator_recovery_profile(
        "print",
        dict(VALID_RECOVERY),
        handler=callback,
        kwargs=kwargs,
        manual=True,
    )

    assert len(commands) == 3
    assert [cmd.command_type for cmd in commands] == ["SET_REG_RECOVERY_PROFILE"] * 3
    assert [cmd.command_code for cmd in commands] == [0x68, 0x68, 0x68]
    assert [cmd.param1 for cmd in commands] == [
        0x00000000,
        0x00000100,
        0x00010200,
    ]
    assert commands[0].param2 == (300 << 16) | 2
    assert commands[0].param3 == (0 << 16) | 1
    assert commands[1].param2 == (0 << 16) | 1500
    assert commands[1].param3 == (0 << 16) | 3
    assert commands[2].param2 == 0x6
    assert commands[2].param3 == 0
    assert commands[0].handler is None
    assert commands[1].handler is None
    assert commands[2].handler is callback
    assert commands[2].kwargs == kwargs
    assert list(machine.command_queue.queue)[-3:] == commands


def test_slew_ready_and_restore_helpers_pack_fields(qapp, test_profile):
    machine = _machine(test_profile)

    slew = machine.set_regulator_slew_profile(
        "refuel",
        {
            "max_hz_delta_up_per_loop": 1200,
            "max_hz_delta_down_per_loop": 450,
            "recovery_bypass_slew_ticks": 3,
        },
    )
    ready = machine.set_regulator_ready_profile(
        "print",
        {
            "ready_tol_raw": 4,
            "consecutive_samples": 2,
        },
    )
    restore = machine.restore_regulator_profile(["print", "refuel"], source="defaults")

    assert (slew.command_type, slew.command_code, slew.param1, slew.param2, slew.param3) == (
        "SET_REG_SLEW_PROFILE",
        0x69,
        1,
        (450 << 16) | 1200,
        3,
    )
    assert (ready.command_type, ready.command_code, ready.param1, ready.param2, ready.param3) == (
        "SET_REG_READY_PROFILE",
        0x6A,
        0,
        4,
        2,
    )
    assert (restore.command_type, restore.command_code, restore.param1, restore.param2, restore.param3) == (
        "RESTORE_REG_PROFILE",
        0x6B,
        0x3,
        1,
        0,
    )


def test_invalid_regulator_profile_inputs_do_not_queue(qapp, test_profile):
    machine = _machine(test_profile)

    invalid_recovery = dict(VALID_RECOVERY)
    invalid_recovery["active_ticks"] = 21
    assert machine.set_regulator_recovery_profile("print", invalid_recovery) is False
    assert len(machine.command_queue.queue) == 0

    missing_slew = {
        "max_hz_delta_up_per_loop": 1200,
        "max_hz_delta_down_per_loop": 450,
    }
    assert machine.set_regulator_slew_profile("print", missing_slew) is False
    assert len(machine.command_queue.queue) == 0

    bool_ready = {
        "ready_tol_raw": True,
        "consecutive_samples": 1,
    }
    assert machine.set_regulator_ready_profile("print", bool_ready) is False
    assert len(machine.command_queue.queue) == 0

    assert machine.restore_regulator_profile("both", source="flash") is False
    assert len(machine.command_queue.queue) == 0

    assert machine.set_regulator_ready_profile("unknown", {"ready_tol_raw": 4, "consecutive_samples": 1}) is False
    assert len(machine.command_queue.queue) == 0


def test_restore_helper_accepts_single_channel_and_mask(qapp, test_profile):
    machine = _machine(test_profile)

    print_restore = machine.restore_regulator_profile("print")
    mask_restore = machine.restore_regulator_profile(0x2)

    assert print_restore.param1 == 0x1
    assert print_restore.param2 == 0
    assert mask_restore.param1 == 0x2
    assert mask_restore.param2 == 0
