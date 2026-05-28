from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tempfile

import numpy as np
from PySide6.QtGui import QCloseEvent

import CalibrationClasses.View as CalibrationView
from CalibrationClasses.Model import ImageAnalysisThread, RefuelCameraModel
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


def test_refuel_camera_window_is_dataset_first_ui(qapp):
    dialog, _model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )

    assert dialog.save_button.text() == "Save Snapshot"
    assert dialog.snapshot_folder_label.text() == str(dialog._save_dir)
    assert "training data" in dialog.capture_help_label.text().lower()
    assert not hasattr(dialog, "set_target_button")
    assert not hasattr(dialog, "burst_button")
    assert not hasattr(dialog, "summary_baseline_label")
    assert not hasattr(dialog, "level_chart_view")


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


def test_refuel_camera_window_live_capture_sets_diagnostic_active_flag(qapp):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )

    dialog.toggle_capture()
    assert model.refuel_camera_model.is_refuel_diagnostic_capture_active() is True

    dialog.toggle_capture()
    assert model.refuel_camera_model.is_refuel_diagnostic_capture_active() is False


def test_refuel_camera_window_save_frame_creates_output_directory_and_uses_raw_image(monkeypatch, qapp, tmp_path):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.raw_capture_image = np.zeros((10, 16, 3), dtype=np.uint8)
    model.refuel_camera_model.annotated_image = np.zeros((6, 6, 3), dtype=np.uint8)
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
    assert written["shape"] == (10, 16, 3)
    assert dialog.last_snapshot_label.text() == str(written["path"].resolve())


def test_refuel_camera_window_preview_preserves_aspect_ratio(qapp):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.raw_capture_image = np.zeros((30, 40, 3), dtype=np.uint8)
    model.refuel_camera_model.annotated_image = None

    dialog.show()
    qapp.processEvents()
    dialog.update_refuel_ui()
    qapp.processEvents()

    pixmap = dialog.image_label.pixmap()
    assert pixmap is not None
    assert dialog.image_label.hasScaledContents() is False
    assert abs((pixmap.width() / pixmap.height()) - (30 / 40)) < 0.05
    assert pixmap.width() <= dialog.image_label.width()
    assert pixmap.height() <= dialog.image_label.height()


def test_refuel_camera_window_preview_prefers_annotated_frame(qapp):
    raw = np.zeros((30, 40, 3), dtype=np.uint8)
    annotated = np.zeros((480, 640, 3), dtype=np.uint8)

    preview = RefuelCameraWindow._prepare_refuel_preview_image(raw, annotated)

    assert preview is annotated
    assert preview.shape == (480, 640, 3)


def test_refuel_camera_window_detector_annotation_matches_rotated_raw_aspect(qapp):
    raw = np.zeros((50, 80, 3), dtype=np.uint8)
    working = RefuelCameraModel._build_analysis_working_frame(raw)
    thread = ImageAnalysisThread(
        working,
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )
    thread.analyze_image()

    preview = RefuelCameraWindow._prepare_refuel_preview_image(raw, thread.annotated_image)

    rotated_raw = CalibrationView.cv2.rotate(raw, CalibrationView.cv2.ROTATE_90_COUNTERCLOCKWISE)
    assert preview is thread.annotated_image
    assert abs((preview.shape[1] / preview.shape[0]) - (rotated_raw.shape[1] / rotated_raw.shape[0])) < 0.01


def test_refuel_camera_window_preview_rotates_raw_frame_without_annotation(qapp):
    raw = np.zeros((30, 40, 3), dtype=np.uint8)

    preview = RefuelCameraWindow._prepare_refuel_preview_image(raw, None)

    assert preview.shape == (40, 30, 3)


def test_refuel_camera_window_update_refuel_ui_displays_annotated_preview(qapp):
    dialog, model, _controller = _make_dialog(
        qapp,
        capture_return=np.zeros((8, 8, 3), dtype=np.uint8),
    )
    model.refuel_camera_model.raw_capture_image = np.zeros((20, 30, 3), dtype=np.uint8)
    model.refuel_camera_model.annotated_image = np.zeros((80, 120, 3), dtype=np.uint8)

    dialog.show()
    qapp.processEvents()
    dialog.update_refuel_ui()
    qapp.processEvents()

    pixmap = dialog.image_label.pixmap()
    assert pixmap is not None
    assert abs((pixmap.width() / pixmap.height()) - (120 / 80)) < 0.05


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
    assert "scene_" in dialog.dataset_scene_label.text()


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
