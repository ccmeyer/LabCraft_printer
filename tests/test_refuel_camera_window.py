from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tempfile

import numpy as np
from PySide6.QtGui import QCloseEvent

import CalibrationClasses.View as CalibrationView
from CalibrationClasses.Model import RefuelCameraModel
from CalibrationClasses.View import RefuelCameraWindow


def _make_dialog(
    qapp,
    *,
    start_side_effect=None,
    capture_return=None,
    run_burst_return=True,
    machine=None,
):
    model = SimpleNamespace(
        machine_model=SimpleNamespace(
            step_size=1,
            increase_step_size=lambda: None,
            decrease_step_size=lambda: None,
        ),
        calibration_manager=SimpleNamespace(
            _build_recorder_meta=lambda: {},
        ),
        experiment_model=SimpleNamespace(experiment_dir_path=tempfile.mkdtemp()),
        refuel_camera_model=RefuelCameraModel(),
    )
    controller = SimpleNamespace(
        set_relative_coordinates=Mock(),
        set_relative_refuel_pressure=Mock(),
        set_relative_print_pressure=Mock(),
        refuel_only=Mock(),
        print_only=Mock(),
        print_droplets=Mock(),
        start_refuel_camera=Mock(side_effect=start_side_effect),
        capture_refuel_image=Mock(return_value=capture_return),
        capture_refuel_image_with_context=Mock(
            return_value=(capture_return, {"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 10.0})
        ),
        get_refuel_capture_context=Mock(return_value={"location": "camera", "monotonic_s": 9.0}),
        run_refuel_balance_burst=Mock(return_value=run_burst_return),
        stop_refuel_camera=Mock(),
        disable_print_profile=Mock(),
        machine=machine,
    )
    main_window = SimpleNamespace(color_dict={"dark_gray": "#202020"})
    dialog = RefuelCameraWindow(main_window, model, controller)
    return dialog, model, controller


def test_refuel_camera_window_close_event_stops_camera_and_disables_print_profile(qapp):
    dialog, _model, controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    dialog.timer.start(500)
    assert dialog.timer.isActive()

    event = QCloseEvent()
    dialog.closeEvent(event)

    assert not dialog.timer.isActive()
    controller.stop_refuel_camera.assert_called_once_with()
    controller.disable_print_profile.assert_called_once_with()
    assert event.isAccepted()


def test_refuel_camera_window_save_frame_creates_output_directory(monkeypatch, qapp, tmp_path):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.original_image = np.zeros((8, 8, 3), dtype=np.uint8)
    dialog._save_dir = tmp_path / "refuel_camera_frames"
    written = {}

    def _fake_imwrite(path, image):
        written["path"] = Path(path)
        written["shape"] = image.shape
        return True

    monkeypatch.setattr(CalibrationView.cv2, "imwrite", _fake_imwrite)

    dialog.save_frame()

    assert dialog._save_dir.exists()
    assert written["path"].parent == dialog._save_dir
    assert written["shape"] == (8, 8, 3)


def test_refuel_camera_window_none_capture_disables_session_without_crashing(monkeypatch, qapp):
    warning = Mock()
    monkeypatch.setattr(CalibrationView.QtWidgets.QMessageBox, "warning", warning)
    dialog, model, controller = _make_dialog(qapp, capture_return=None)

    dialog.timer.start(500)
    dialog.capturing = True
    dialog.capture_button.setText("Stop Capturing Images")

    dialog.capture_image()

    assert dialog.capturing is False
    assert not dialog.timer.isActive()
    assert dialog.capture_button.isEnabled() is False
    assert dialog.image_label.text() == "Camera did not return a frame."
    assert model.refuel_camera_model.get_level_log() == []
    controller.capture_refuel_image.assert_called_once_with()
    warning.assert_called_once()


def test_refuel_camera_window_start_failure_shows_warning_and_stays_idle(monkeypatch, qapp):
    warning = Mock()
    monkeypatch.setattr(CalibrationView.QtWidgets.QMessageBox, "warning", warning)

    dialog, _model, controller = _make_dialog(
        qapp,
        start_side_effect=RuntimeError("camera offline"),
        capture_return=None,
    )

    assert dialog.capture_button.isEnabled() is False
    assert dialog.image_label.text() == "camera offline"
    controller.start_refuel_camera.assert_called_once_with()
    warning.assert_called_once()


def test_refuel_camera_window_lock_target_disables_analysis_controls_and_reset_reenables(qapp):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.current_level = 88.0
    model.refuel_camera_model.last_meniscus_row = 21

    dialog.lock_current_target()

    assert dialog.target_level_label.text() == "Target Level: 88.0"
    assert dialog.offset_spinbox.isEnabled() is False
    assert dialog.width_spinbox.isEnabled() is False
    assert dialog.threshold_spinbox.isEnabled() is False

    dialog.reset_session()

    assert dialog.offset_spinbox.isEnabled() is True
    assert dialog.width_spinbox.isEnabled() is True
    assert dialog.threshold_spinbox.isEnabled() is True


def test_refuel_camera_window_start_burst_auto_starts_capture_and_waits_for_samples(qapp):
    dialog, model, controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.current_level = 90.0
    model.refuel_camera_model.last_meniscus_row = 25
    dialog.lock_current_target()

    dialog.start_burst_test()

    assert dialog.capturing is True
    assert dialog.timer.isActive() is True
    controller.run_refuel_balance_burst.assert_not_called()
    assert "Waiting for 5 valid baseline samples." in dialog.burst_status_label.text()


def test_refuel_camera_window_burst_controls_disable_while_burst_active(qapp):
    dialog, model, controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.current_level = 100.0
    model.refuel_camera_model.last_meniscus_row = 20
    dialog.lock_current_target()
    model.refuel_camera_model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 101.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 99.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 100.0, "phase": "live"},
    ]
    dialog.capturing = True

    dialog.start_burst_test()

    controller.run_refuel_balance_burst.assert_called_once()
    assert dialog.burst_button.isEnabled() is False
    assert dialog.baseline_samples_spinbox.isEnabled() is False
    assert dialog.post_samples_spinbox.isEnabled() is False


def test_refuel_camera_window_chart_uses_elapsed_time_and_target_overlay(qapp):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 3.5, "monotonic_s": 4.5, "level_px": 102.0, "phase": "live"},
    ]
    model.refuel_camera_model.target_level_px = 101.0
    model.refuel_camera_model.tolerance_px = 5.0

    dialog.update_level_chart()

    assert dialog.level_series.count() == 2
    assert dialog.target_series.count() == 2
    assert dialog.upper_band_series.count() == 2
    assert dialog.lower_band_series.count() == 2
    assert dialog.axisX.max() >= 3.5


def test_refuel_camera_window_dataset_session_and_single_capture(qapp):
    dialog, model, controller = _make_dialog(
        qapp,
        capture_return=np.zeros((32, 24, 3), dtype=np.uint8),
    )

    dialog.start_dataset_session()
    dialog.start_dataset_scene()
    dialog.capture_dataset_single()

    assert model.refuel_camera_model.is_dataset_session_active() is True
    assert model.refuel_camera_model.get_dataset_current_scene() is not None
    assert len(model.refuel_camera_model.get_dataset_frame_records()) == 1
    assert controller.capture_refuel_image_with_context.called
    assert "Captured frame_" in dialog.dataset_status_label.text()
    assert dialog.dataset_session_path_label.text() != "-"


def test_refuel_camera_window_reject_last_dataset_capture(monkeypatch, qapp):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((16, 16, 3), dtype=np.uint8),
    )
    dialog.start_dataset_session()
    dialog.start_dataset_scene()
    dialog.capture_dataset_single()
    monkeypatch.setattr(
        CalibrationView.QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("bad frame", True),
    )

    dialog.reject_last_dataset_capture()

    assert model.refuel_camera_model.get_dataset_frame_records(accepted_only=True) == []
    assert "rejected" in dialog.dataset_status_label.text().lower()
