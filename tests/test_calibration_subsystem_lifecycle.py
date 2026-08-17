from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import ApplicationComposition
from CalibrationClasses.Model import CalibrationManager
from Model import Model
import View
from hardware.profile import CURRENT_PROFILE
from tests.calibration_test_utils import SignalStub
from tests.test_droplet_imaging_refuel_panel import _build_droplet_dialog
from tests.test_pressure_plotbox_buttons import (
    _FakeMachineModel,
    _SignalStub,
    _make_controller,
    _make_main_window,
    _make_model,
)


def test_primary_dialog_is_constructed_once_and_reused_for_ten_sessions(
    monkeypatch, qapp
):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(_FakeMachineModel(), events, printer_head=object())
    model.calibration_manager = object()
    model.droplet_camera_model = object()
    model.refuel_camera_model = object()
    controller = _make_controller(events)
    box = View.PressurePlotBox(main_window, model, controller)

    class _ReusableDialog:
        construction_count = 0

        def __init__(self, *_args, **_kwargs):
            type(self).construction_count += 1
            self.finished = _SignalStub()
            self.sessionDeactivated = _SignalStub()
            self.camera_free_mode = False
            self._active = False
            self.activation_modes = []

        def activate_session(self, mode="calibration"):
            assert not self._active
            self._active = True
            self.activation_modes.append(mode)

        def deactivate_session(self, reason="closed"):
            if not self._active:
                return False
            self._active = False
            self.sessionDeactivated.emit(reason)
            return True

        def session_is_active(self):
            return self._active

        def hide(self):
            pass

    monkeypatch.setattr(
        View.CalibrationClasses, "DropletImagingDialog", _ReusableDialog
    )
    identities = (
        id(model.calibration_manager),
        id(model.droplet_camera_model),
        id(model.refuel_camera_model),
    )

    dialogs = []
    for cycle in range(10):
        mode = "optics" if cycle in {3, 7} else "calibration"
        dialog = box._activate_primary_droplet_imager_dialog(mode=mode)
        dialogs.append(dialog)
        assert box._droplet_imager_dialog_state == "active"
        assert dialog.deactivate_session(reason=f"cycle_{cycle}") is True
        assert box._droplet_imager_dialog_state == "inactive"
        assert not box._calibration_profile_leases

    assert _ReusableDialog.construction_count == 1
    assert len({id(dialog) for dialog in dialogs}) == 1
    assert identities == (
        id(model.calibration_manager),
        id(model.droplet_camera_model),
        id(model.refuel_camera_model),
    )
    assert dialogs[0].activation_modes.count("optics") == 2
    assert dialogs[0].activation_modes.count("calibration") == 8
    assert controller.enable_print_profile.call_count == 10
    assert controller.disable_print_profile.call_count == 10
    controller.disconnect_droplet_camera_signals.assert_not_called()
    controller.connect_droplet_camera_signals.assert_not_called()
    model.reload_droplet_model.assert_not_called()


def test_dialog_external_callbacks_exist_only_during_active_session(
    monkeypatch, qapp
):
    status_calls = []
    dialog, _refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
        status_calls=status_calls,
    )
    manager = dialog.model.calibration_manager

    for cycle in range(10):
        before = len(status_calls)
        manager.calibrationStageChanged.emit(f"cycle-{cycle}", "blue")
        assert len(status_calls) == before + 1
        assert dialog.deactivate_session(reason=f"cycle_{cycle}") is True
        hidden_count = len(status_calls)
        manager.calibrationStageChanged.emit("hidden", "red")
        assert len(status_calls) == hidden_count
        if cycle < 9:
            assert dialog.activate_session() is True

    assert controller.start_droplet_camera.call_count == 10
    assert controller.stop_droplet_camera.call_count == 10
    assert dialog._session_signal_connections == []


def _manager_model(tmp_path):
    return SimpleNamespace(
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(tmp_path),
            calibration_file_path=str(tmp_path / "calibration.json"),
        ),
        machine_state_updated=SignalStub(),
    )


def test_experiment_transition_resets_volatile_state_but_preserves_policy(tmp_path):
    manager = CalibrationManager(_manager_model(tmp_path))
    first = tmp_path / "one" / "calibration.json"
    second = tmp_path / "two" / "calibration.json"
    manager.update_calibration_file_path(str(first))
    manager.background_image = object()
    manager.nozzle_center = (10, 20)
    manager.droplet_trajectory_vector = (1, 2)
    manager._completed_canonical_session_cache = {"pressure": [{"value": 1}]}
    manager._in_progress_characterization_rows = {"row": {"value": 1}}
    manager._transient_characterization_candidate = {"candidate": object()}

    manager.update_calibration_file_path(str(second))

    assert manager.background_image is None
    assert manager.nozzle_center is None
    assert manager.droplet_trajectory_vector is None
    assert manager._completed_canonical_session_cache == {}
    assert manager._in_progress_characterization_rows == {}
    assert manager._transient_characterization_candidate is None
    assert manager.get_capture_retention_policy() == "full"
    assert manager.calibration_file_path == str(second)
    assert manager._calibration_recordings_root.startswith(str(second.parent))


def test_experiment_transition_is_rejected_while_calibration_is_active(tmp_path):
    manager = CalibrationManager(_manager_model(tmp_path))
    first = tmp_path / "one" / "calibration.json"
    manager.update_calibration_file_path(str(first))
    manager.activeCalibration = object()

    with pytest.raises(RuntimeError, match="Cannot change experiments"):
        manager.update_calibration_file_path(
            str(tmp_path / "two" / "calibration.json")
        )

    assert manager.calibration_file_path == str(first)


def test_model_calibration_shutdown_is_idempotent_and_ordered():
    calls = []
    metadata_signal = SimpleNamespace(
        disconnect=lambda _slot: calls.append("disconnect_metadata")
    )
    manager = SimpleNamespace(
        is_idle=lambda: True,
        shutdown=lambda: calls.append("manager_shutdown"),
    )
    model = SimpleNamespace(
        _calibration_subsystem_shutdown=False,
        calibration_manager=manager,
        record_image_metadata=object(),
        droplet_camera_model=SimpleNamespace(
            record_metadata_signal=metadata_signal,
            shutdown=lambda: calls.append("droplet_shutdown"),
        ),
        refuel_camera_model=SimpleNamespace(
            shutdown=lambda: calls.append("refuel_shutdown")
        ),
    )

    assert Model.shutdown_calibration_subsystem(model) is True
    assert Model.shutdown_calibration_subsystem(model) is False
    assert calls == [
        "disconnect_metadata",
        "droplet_shutdown",
        "refuel_shutdown",
        "manager_shutdown",
    ]


@pytest.mark.parametrize("with_balance", [False, True])
def test_application_components_close_always_invokes_calibration_cleanup(
    with_balance, qapp
):
    shutdown_ui = Mock(return_value=True)
    shutdown_model = Mock(return_value=True)
    pressure_box = SimpleNamespace(
        calibration_session_is_idle=lambda: True,
        shutdown_calibration_ui=shutdown_ui,
    )
    view = SimpleNamespace(
        pressure_box=pressure_box,
        findChildren=lambda _type: [],
        blockSignals=lambda _blocked: None,
        hide=lambda: None,
        deleteLater=lambda: None,
        connection_widget=None,
        _close_disconnect_timer=None,
    )
    balance_service = None
    if with_balance:
        balance_service = SimpleNamespace(
            close=Mock(
                return_value=SimpleNamespace(accepted=True, detail="closed")
            ),
            deleteLater=lambda: None,
        )
    model = SimpleNamespace(
        shutdown_calibration_subsystem=shutdown_model,
        deleteLater=lambda: None,
    )
    components = ApplicationComposition.ApplicationComponents(
        model=model,
        machine=SimpleNamespace(deleteLater=lambda: None),
        controller=SimpleNamespace(
            deleteLater=lambda: None,
            _seq_timer=None,
            pending_capture_guard_timer=None,
        ),
        view=view,
        balance_service=balance_service,
    )

    assert components.close() is True
    assert components.close() is True
    shutdown_ui.assert_called_once_with()
    shutdown_model.assert_called_once_with()
    if balance_service is not None:
        balance_service.close.assert_called_once_with()
