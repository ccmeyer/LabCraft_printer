from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QPushButton, QSpinBox

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.View as calibration_view
from CalibrationClasses.View import DropletImagingDialog


class _RecommendationManager:
    def __init__(self, preview):
        self.preview = dict(preview or {})
        self.preview_requests = []
        self.records = []
        self.memory_enabled = True

    def clear_calibration_memory_ui_recommendation_state(self):
        return None

    def get_calibration_memory_enabled(self):
        return bool(self.memory_enabled)

    def set_calibration_memory_enabled(self, enabled):
        self.memory_enabled = bool(enabled)
        return True

    def preview_calibration_memory_recommendation(self, **kwargs):
        self.preview_requests.append(dict(kwargs))
        preview = dict(self.preview)
        preview.setdefault("memory_enabled", bool(self.memory_enabled))
        return preview

    def record_calibration_memory_ui_interaction(self, action, preview, *, extra=None):
        payload = {
            "action": str(action),
            "preview": dict(preview or {}),
            "extra": dict(extra or {}),
        }
        self.records.append(payload)
        return payload


def _make_preview(
    *,
    aggregation_level="exact_pair",
    manual_apply_allowed=True,
    manual_apply_reason="qualified",
    candidate_found=True,
    memory_enabled=True,
):
    prior = None
    seed_values = {}
    if candidate_found:
        prior = {
            "aggregation_level": aggregation_level,
            "pulse_width_us": 1500,
            "recommended_pressure_psi": 1.62,
            "stable_single_droplet_band_psi": [1.52, 1.70],
            "emergence_time_us": 4300,
            "expected_mean_volume_nL": 9.95,
            "expected_cv_pct": 4.1,
            "contributing_runs": 4,
            "source_run_ids": ["run-a", "run-b", "run-c", "run-d"],
            "recommendation_confidence_adjusted": 0.84,
            "pulse_match_type": "exact",
        }
        seed_values = {
            "start_pressure_psi": 1.62,
            "seed_source": "recommended_pressure_psi",
        }
    return {
        "memory_enabled": bool(memory_enabled),
        "capture_level": "compact",
        "mode": "advisory",
        "candidate_found": bool(candidate_found),
        "prior": prior,
        "qualification": {
            "qualified": bool(manual_apply_allowed),
            "reason": manual_apply_reason,
        },
        "seed_values": seed_values,
        "manual_apply_allowed": bool(manual_apply_allowed),
        "manual_apply_reason": manual_apply_reason,
        "target_pulse_width_us": 1400,
        "target_volume_nl": 10.0,
    }


def _make_dialog_stub(preview, qapp):
    manager = _RecommendationManager(preview)
    dialog = SimpleNamespace()
    dialog.model = SimpleNamespace(calibration_manager=manager)
    dialog.hw_lo = 0.10
    dialog.hw_hi = 5.00
    dialog.stageLabel = QLabel("Status: Idle")
    dialog.memory_recommendation_status_label = QLabel("")
    dialog.memory_recommendation_seed_label = QLabel("")
    dialog.memory_recommendation_expected_label = QLabel("")
    dialog.memory_recommendation_mode_label = QLabel("")
    dialog.memory_recommendation_refresh_btn = QPushButton("Refresh Recommendation")
    dialog.memory_recommendation_apply_btn = QPushButton("Use Recommended Seed")
    dialog.memory_recommendation_ignore_btn = QPushButton("Keep Manual Start")
    dialog.print_pulse_width_spinbox = QSpinBox()
    dialog.print_pulse_width_spinbox.setRange(0, 5000)
    dialog.print_pulse_width_spinbox.setValue(1400)
    dialog.start_pressure_spin = QDoubleSpinBox()
    dialog.start_pressure_spin.setRange(0.10, 5.00)
    dialog.start_pressure_spin.setDecimals(2)
    dialog.start_pressure_spin.setValue(0.80)
    dialog._memory_recommendation_preview = None
    dialog._memory_recommendation_logged_fingerprint = None
    dialog._memory_recommendation_refresh_active = False
    dialog.print_pulse_width_changes = []
    dialog.start_pressure_changes = []
    dialog._bridge_get_calibration_manager = lambda: manager
    dialog._get_calibration_memory_target_volume_nL = lambda: 10.0
    dialog.handle_print_pulse_width_change = lambda value: dialog.print_pulse_width_changes.append(value)
    dialog.set_start_pressure = lambda value: dialog.start_pressure_changes.append(value)
    dialog.isVisible = lambda: True

    dialog._calibration_memory_source_label = DropletImagingDialog._calibration_memory_source_label
    dialog._calibration_memory_mode_description = DropletImagingDialog._calibration_memory_mode_description
    dialog._format_pressure_band_psi = DropletImagingDialog._format_pressure_band_psi
    dialog._calibration_memory_preview_fingerprint = DropletImagingDialog._calibration_memory_preview_fingerprint
    dialog._render_calibration_memory_recommendation = (
        DropletImagingDialog._render_calibration_memory_recommendation.__get__(dialog, DropletImagingDialog)
    )
    dialog.refresh_calibration_memory_recommendation = (
        DropletImagingDialog.refresh_calibration_memory_recommendation.__get__(dialog, DropletImagingDialog)
    )
    dialog.apply_calibration_memory_recommendation = (
        DropletImagingDialog.apply_calibration_memory_recommendation.__get__(dialog, DropletImagingDialog)
    )
    dialog.ignore_calibration_memory_recommendation = (
        DropletImagingDialog.ignore_calibration_memory_recommendation.__get__(dialog, DropletImagingDialog)
    )
    return dialog, manager


def _bind_real_target_volume_helpers(dialog):
    dialog._bridge_get_current_reagent_name = (
        DropletImagingDialog._bridge_get_current_reagent_name.__get__(dialog, DropletImagingDialog)
    )
    dialog._bridge_get_current_design_droplet_volume_nL = (
        DropletImagingDialog._bridge_get_current_design_droplet_volume_nL.__get__(dialog, DropletImagingDialog)
    )
    dialog._get_calibration_memory_target_volume_nL = (
        DropletImagingDialog._get_calibration_memory_target_volume_nL.__get__(dialog, DropletImagingDialog)
    )
    return dialog


def test_recommendation_panel_shows_exact_pair_prior(qapp):
    dialog, manager = _make_dialog_stub(_make_preview(), qapp)

    preview = dialog.refresh_calibration_memory_recommendation()

    assert preview["candidate_found"] is True
    assert "Exact pair" in dialog.memory_recommendation_status_label.text()
    assert "confidence 0.84" in dialog.memory_recommendation_status_label.text()
    assert "PW 1500 us" in dialog.memory_recommendation_seed_label.text()
    assert "start 1.620 psi" in dialog.memory_recommendation_seed_label.text()
    assert "volume 9.950 nL" in dialog.memory_recommendation_expected_label.text()
    assert dialog.memory_recommendation_apply_btn.isEnabled() is True
    assert dialog.memory_recommendation_ignore_btn.isEnabled() is True
    assert manager.records[0]["action"] == "shown"
    assert manager.preview_requests[0]["target_pulse_width_us"] == 1400
    assert manager.preview_requests[0]["target_volume_nl"] == pytest.approx(10.0)


def test_recommendation_panel_shows_no_prior_state_without_changing_controls(qapp):
    dialog, manager = _make_dialog_stub(_make_preview(candidate_found=False), qapp)

    dialog.refresh_calibration_memory_recommendation()

    assert "No prior found" in dialog.memory_recommendation_status_label.text()
    assert dialog.memory_recommendation_apply_btn.isEnabled() is False
    assert dialog.memory_recommendation_ignore_btn.isEnabled() is False
    assert dialog.print_pulse_width_spinbox.value() == 1400
    assert dialog.start_pressure_spin.value() == pytest.approx(0.80)
    assert dialog.print_pulse_width_changes == []
    assert dialog.start_pressure_changes == []
    assert manager.records == []


def test_recommendation_panel_shows_disabled_state_when_memory_is_off(qapp):
    dialog, manager = _make_dialog_stub(
        _make_preview(candidate_found=False, manual_apply_allowed=False, manual_apply_reason="memory_disabled", memory_enabled=False),
        qapp,
    )
    dialog.enable_calibration_memory_checkbox = QPushButton()
    dialog.enable_calibration_memory_checkbox.setCheckable(True)

    dialog.refresh_calibration_memory_recommendation()

    assert "disabled" in dialog.memory_recommendation_status_label.text().lower()
    assert dialog.memory_recommendation_apply_btn.isEnabled() is False
    assert dialog.memory_recommendation_ignore_btn.isEnabled() is False
    assert "disabled" in dialog.memory_recommendation_mode_label.text().lower()
    assert manager.records == []


def test_reference_only_grouped_prior_disables_apply_and_surfaces_reason(qapp):
    dialog, _manager = _make_dialog_stub(
        _make_preview(
            aggregation_level="head_type_only",
            manual_apply_allowed=False,
            manual_apply_reason="aggregation_level_not_allowed",
        ),
        qapp,
    )

    dialog.refresh_calibration_memory_recommendation()

    assert "Reference prior" in dialog.memory_recommendation_status_label.text()
    assert "Head-type fallback" in dialog.memory_recommendation_status_label.text()
    assert dialog.memory_recommendation_apply_btn.isEnabled() is False
    assert "aggregation_level_not_allowed" in dialog.memory_recommendation_expected_label.text()


def test_apply_recommendation_updates_start_controls_only_on_user_action(qapp):
    dialog, manager = _make_dialog_stub(_make_preview(), qapp)
    dialog.refresh_calibration_memory_recommendation()

    assert dialog.print_pulse_width_changes == []
    assert dialog.start_pressure_changes == []

    dialog.apply_calibration_memory_recommendation()

    assert dialog.print_pulse_width_spinbox.value() == 1500
    assert dialog.start_pressure_spin.value() == pytest.approx(1.62)
    assert dialog.print_pulse_width_changes == [1500]
    assert dialog.start_pressure_changes == [pytest.approx(1.62)]
    assert manager.records[-1]["action"] == "applied"
    assert "Loaded recommended seed" in dialog.stageLabel.text()


def test_ignore_recommendation_logs_manual_choice(qapp):
    dialog, manager = _make_dialog_stub(_make_preview(), qapp)
    dialog.refresh_calibration_memory_recommendation()

    dialog.ignore_calibration_memory_recommendation()

    assert manager.records[-1]["action"] == "ignored"
    assert manager.records[-1]["extra"]["reason"] == "user_kept_manual_start"
    assert "Keeping manual calibration start values" in dialog.stageLabel.text()


def test_design_droplet_volume_getter_is_side_effect_free_for_design_reagent(qapp):
    dialog, manager = _make_dialog_stub(_make_preview(candidate_found=False), qapp)
    dialog.model.experiment_model = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 10.0},
        get_fill_reagent_name=lambda: "Water",
        find_option_by_reagent_name=lambda reagent: (
            (("glycerol", None), SimpleNamespace(droplet_nL=12.5))
            if reagent == "50% Glycerol"
            else None
        ),
    )
    dialog.model.rack_model = SimpleNamespace(get_gripper_printer_head=lambda: None)
    manager._safe_get_stock_solution = lambda: "50% Glycerol"
    _bind_real_target_volume_helpers(dialog)
    dialog.refresh_calibration_memory_recommendation = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("design droplet-volume getter should not trigger recommendation refresh")
    )

    target = dialog._bridge_get_current_design_droplet_volume_nL()

    assert target == pytest.approx(12.5)


def test_refresh_recommendation_uses_real_design_droplet_volume_without_recursing(qapp):
    dialog, manager = _make_dialog_stub(_make_preview(), qapp)
    dialog.model.experiment_model = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 10.0},
        get_fill_reagent_name=lambda: "Water",
        find_option_by_reagent_name=lambda reagent: (
            (("glycerol", None), SimpleNamespace(droplet_nL=12.5))
            if reagent == "50% Glycerol"
            else None
        ),
    )
    dialog.model.rack_model = SimpleNamespace(get_gripper_printer_head=lambda: None)
    manager._safe_get_stock_solution = lambda: "50% Glycerol"
    _bind_real_target_volume_helpers(dialog)

    preview = dialog.refresh_calibration_memory_recommendation()

    assert preview["candidate_found"] is True
    assert manager.preview_requests[0]["target_volume_nl"] == pytest.approx(12.5)


def test_refresh_recommendation_reentrancy_guard_returns_cached_preview(qapp):
    dialog, _manager = _make_dialog_stub(_make_preview(candidate_found=False), qapp)
    dialog._memory_recommendation_preview = {"candidate_found": False, "prior": None}
    dialog._memory_recommendation_refresh_active = True

    preview = dialog.refresh_calibration_memory_recommendation()

    assert preview == {"candidate_found": False, "prior": None}


def test_apply_previewed_droplet_volume_refreshes_recommendation(monkeypatch, qapp):
    refresh_calls = []
    applied = []
    dialog = SimpleNamespace()
    dialog._bridge_preview_payload = {
        "factor_name": "glycerol",
        "option_name": None,
        "new_droplet_nL": 12.0,
        "n_stocks": 1,
    }
    dialog.model = SimpleNamespace(
        experiment_model=SimpleNamespace(
            get_plan_for_key=lambda _key: {"stocks": [{"droplet_volume_nL": 10.0}]},
            apply_droplet_volume_for_option=lambda *args, **kwargs: applied.append((args, kwargs)),
        )
    )
    dialog._bridge_clear_preview = lambda: None
    dialog._bridge_refresh_design_labels = lambda: None
    dialog.refresh_calibration_memory_recommendation = lambda: refresh_calls.append(True)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)
    dialog._apply_previewed_droplet_volume = (
        DropletImagingDialog._apply_previewed_droplet_volume.__get__(dialog, DropletImagingDialog)
    )

    dialog._apply_previewed_droplet_volume()

    assert applied
    assert refresh_calls == [True]


def _build_real_dialog_for_layout(monkeypatch, qapp, *, reset_quick_controls=True, main_window=None):
    if reset_quick_controls:
        monkeypatch.setattr(DropletImagingDialog, "_quick_controls_expanded_default", False, raising=False)
        if main_window is not None and hasattr(main_window, "_droplet_imaging_quick_controls_expanded"):
            delattr(main_window, "_droplet_imaging_quick_controls_expanded")
    for method_name in (
        "setup_shortcuts",
        "start_droplet_camera",
        "set_exposure_time",
        "set_flash_delay",
        "set_flash_duration",
        "set_imaging_droplets",
        "set_start_pressure",
        "set_num_pressure_tests",
        "populate_summary_table",
    ):
        monkeypatch.setattr(DropletImagingDialog, method_name, lambda self, *args, **kwargs: None)

    droplet_camera_model = SimpleNamespace(
        flash_duration=1000,
        flash_delay=2000,
        num_droplets=1,
        exposure_time=5000,
        droplet_image_updated=SignalStub(),
        flash_signal=SignalStub(),
    )
    calibration_manager = SimpleNamespace(
        analyzedImageUpdated=SignalStub(),
        onlineStreamDebugUpdated=SignalStub(),
        calibrationStageChanged=SignalStub(),
        calibrationCompleted=SignalStub(),
        calibrationQueueCompleted=SignalStub(),
        calibrationError=SignalStub(),
        position_diff_dict_signal=SignalStub(),
        characterizationSummaryUpdated=SignalStub(),
        readinessChanged=SignalStub(),
        clear_calibration_memory_ui_recommendation_state=lambda: None,
        get_record_mode_enabled=lambda: True,
        get_calibration_memory_enabled=lambda: True,
        _emit_readiness=lambda: None,
    )
    machine_model = SimpleNamespace(
        get_print_pressure_bounds=lambda: (0.10, 5.00),
        get_print_pulse_width=lambda: 1400,
        get_current_print_pressure=lambda: 0.80,
    )
    model = SimpleNamespace(
        droplet_camera_model=droplet_camera_model,
        calibration_manager=calibration_manager,
        machine_model=machine_model,
    )
    controller = SimpleNamespace(start_read_camera=lambda: None)
    if main_window is None:
        main_window = SimpleNamespace(color_dict={})
    dialog = DropletImagingDialog(main_window, model, controller)
    return dialog


def test_real_dialog_uses_three_column_layout_with_controls_left_and_results_right(monkeypatch, qapp):
    dialog = _build_real_dialog_for_layout(monkeypatch, qapp)

    assert dialog.width() == 1600
    assert dialog.layout.count() == 3
    assert dialog.layout.itemAt(0).widget() is dialog.control_panel
    assert dialog.layout.itemAt(1).widget() is dialog.analysis_panel
    assert dialog.layout.itemAt(2).widget() is dialog.info_panel
    assert dialog.recommendation_group.parentWidget() is dialog.info_panel
    assert dialog.summary_group.parentWidget() is dialog.info_panel
    assert dialog.bridge_group.parentWidget() is dialog.info_panel
    assert dialog.machine_position_group.parentWidget() is dialog.info_panel
    assert dialog.status_group.parentWidget() is dialog.info_panel
    assert dialog.control_panel.layout().itemAt(0).widget() is dialog.acquisition_controls_section
    assert dialog.calibration_tabs.parentWidget() is dialog.control_panel
    assert dialog.run_options_group.parentWidget() is dialog.control_panel
    assert dialog.control_panel.layout().itemAt(1).widget() is dialog.calibration_tabs
    assert dialog.control_panel.layout().itemAt(2).widget() is dialog.run_options_group
    assert dialog.debug_scroll.parentWidget() is dialog.debug_tab
    assert dialog.debug_scroll.widget() is dialog.debug_tab_content
    assert dialog.manual_group.parentWidget() is dialog.debug_tab_content
    assert dialog.stream_capture_group.parentWidget() is dialog.debug_tab_content
    assert dialog.record_calibration_checkbox.parentWidget() is dialog.run_options_group
    assert dialog.enable_calibration_memory_checkbox.parentWidget() is dialog.run_options_group
    assert dialog.calibration_tabs.count() == 3
    assert [dialog.calibration_tabs.tabText(idx) for idx in range(dialog.calibration_tabs.count())] == [
        "Droplet",
        "Stream",
        "Debug / Specialty",
    ]
    assert dialog.calibration_tabs.currentIndex() == 0
    assert dialog.droplet_tab.layout().contentsMargins().top() > 0
    assert dialog.stream_tab.layout().contentsMargins().top() > 0
    assert dialog.debug_tab_content.layout().contentsMargins().top() > 0
    assert dialog.droplet_tab.isAncestorOf(dialog.start_pressure_spin) is True
    assert dialog.droplet_tab.isAncestorOf(dialog.num_pressure_tests_spin) is True
    assert dialog.stream_tab.isAncestorOf(dialog.start_pressure_spin) is False
    assert dialog.stream_tab.isAncestorOf(dialog.num_pressure_tests_spin) is False
    assert dialog.stream_tab.isAncestorOf(dialog.calibrate_online_stream_button) is True
    assert dialog.droplet_tab.isAncestorOf(dialog.calibrate_online_stream_button) is False
    assert dialog.acquisition_controls_section.isAncestorOf(dialog.flash_delay_spinbox) is True
    assert dialog.acquisition_controls_section.isAncestorOf(dialog.print_pulse_width_spinbox) is True
    assert dialog.acquisition_controls_section.isAncestorOf(dialog.flash_button) is True
    assert dialog.debug_tab.isAncestorOf(dialog.flash_button) is False
    assert dialog.debug_tab.isAncestorOf(dialog.flash_duration_spinbox) is True
    assert dialog.debug_tab.isAncestorOf(dialog.calibrate_timecourse_button) is True
    assert dialog.debug_tab.isAncestorOf(dialog.stream_capture_group) is True
    assert dialog.droplet_tab.isAncestorOf(dialog.calib_group) is False
    assert dialog.stream_tab.isAncestorOf(dialog.stream_calib_group) is False
    droplet_header = dialog.droplet_tab.layout().itemAt(0).widget()
    stream_header = dialog.stream_tab.layout().itemAt(0).widget()
    assert droplet_header.layout().count() == 3
    assert stream_header.layout().count() == 3
    assert dialog.info_panel.sizePolicy().horizontalPolicy() == calibration_view.QtWidgets.QSizePolicy.Fixed
    assert dialog.control_panel.sizePolicy().horizontalPolicy() == calibration_view.QtWidgets.QSizePolicy.Fixed
    assert dialog.analysis_panel.sizePolicy().horizontalPolicy() == calibration_view.QtWidgets.QSizePolicy.Expanding
    assert dialog.analysis_panel.minimumWidth() >= 560
    assert dialog.control_panel.maximumWidth() <= 460
    assert dialog.info_panel.maximumWidth() <= 460
    assert dialog.flash_button.minimumHeight() >= 32
    assert dialog.calibrate_all_button.minimumHeight() >= 32
    assert dialog.memory_recommendation_apply_btn.minimumHeight() >= 32
    assert dialog.load_selected_button.minimumHeight() >= 32
    assert not hasattr(dialog, "calibrate_prebreakup_button")
    assert not hasattr(dialog, "acquire_prebreakup_dataset_button")
    assert not hasattr(dialog, "prebreakup_step_spin")
    assert not hasattr(dialog, "prebreakup_dataset_plan_edit")

    dialog.deleteLater()


def test_real_dialog_quick_controls_start_collapsed_and_remember_last_state(monkeypatch, qapp):
    main_window = SimpleNamespace(color_dict={})
    dialog = _build_real_dialog_for_layout(monkeypatch, qapp, main_window=main_window)

    assert dialog.acquisition_controls_toggle.isChecked() is False
    assert dialog.acquisition_controls_content.isHidden() is True

    dialog.acquisition_controls_toggle.click()
    qapp.processEvents()

    assert dialog.acquisition_controls_toggle.isChecked() is True
    assert dialog.acquisition_controls_content.isHidden() is False
    assert getattr(main_window, "_droplet_imaging_quick_controls_expanded") is True

    dialog.deleteLater()
    qapp.processEvents()

    reopened = _build_real_dialog_for_layout(
        monkeypatch,
        qapp,
        reset_quick_controls=False,
        main_window=main_window,
    )

    assert reopened.acquisition_controls_toggle.isChecked() is True
    assert reopened.acquisition_controls_content.isHidden() is False

    reopened.deleteLater()


def test_real_dialog_creates_duplicate_shared_buttons_for_droplet_and_stream_tabs(monkeypatch, qapp):
    dialog = _build_real_dialog_for_layout(monkeypatch, qapp)

    assert dialog.droplet_tab.isAncestorOf(dialog.prime_head_button) is True
    assert dialog.stream_tab.isAncestorOf(dialog.prime_head_stream_button) is True
    assert dialog.droplet_tab.isAncestorOf(dialog.calibrate_nozzle_button) is True
    assert dialog.stream_tab.isAncestorOf(dialog.calibrate_nozzle_stream_button) is True
    assert dialog.droplet_tab.isAncestorOf(dialog.calibrate_focus_button) is True
    assert dialog.stream_tab.isAncestorOf(dialog.calibrate_focus_stream_button) is True
    assert dialog.droplet_tab.isAncestorOf(dialog.calibrate_emergence_button) is True
    assert dialog.stream_tab.isAncestorOf(dialog.calibrate_emergence_stream_button) is True
    assert dialog.prime_head_button.text() == dialog.prime_head_stream_button.text()
    assert dialog.calibrate_nozzle_button.text() == dialog.calibrate_nozzle_stream_button.text()
    assert dialog.calibrate_focus_button.text() == dialog.calibrate_focus_stream_button.text()
    assert dialog.calibrate_emergence_button.text() == dialog.calibrate_emergence_stream_button.text()

    dialog.deleteLater()
