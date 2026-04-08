from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import DropletImagingDialog


def _make_run(run_id, *, stock="Water", sweep_entries=None, search_entries=None):
    steps = {
        "pressure_sweep_characterization": [],
        "droplet_search": [],
    }

    for entry in sweep_entries or []:
        steps["pressure_sweep_characterization"].append(
            {
                "timestamp": entry.get("timestamp"),
                "settings": {"print_width": entry.get("pw_us")},
                "result": {
                    "pressures": [
                        {
                            "pressure": entry.get("pressure_psi"),
                            "mean_volume": entry.get("mean_nL"),
                            "cv_volume_percent": entry.get("cv_pct"),
                            "valid": entry.get("valid", True),
                            "invalid_reason": entry.get("invalid_reason"),
                        }
                    ]
                },
            }
        )

    for entry in search_entries or []:
        steps["droplet_search"].append(
            {
                "timestamp": entry.get("timestamp"),
                "settings": {
                    "print_width": entry.get("pw_us"),
                    "print_pressure": entry.get("pressure_psi"),
                },
                "result": {
                    "pressure": entry.get("pressure_psi"),
                    "mean_volume": entry.get("mean_nL"),
                    "cv_volume_percent": entry.get("cv_pct"),
                    "valid": entry.get("valid", True),
                    "invalid_reason": entry.get("invalid_reason"),
                    "print_pulse_width_us": entry.get("pw_us"),
                },
            }
        )

    return {
        "run_id": run_id,
        "stock_solution": stock,
        "steps": steps,
    }


def _build_model_and_manager(tmp_path, runs, *, current_stock="Water", active_run_id=None):
    experiment_model = SimpleNamespace(
        calibration_file_path=str(tmp_path / "calibration.json"),
        get_calibration_file_path=lambda: str(tmp_path / "calibration.json"),
    )
    printer_head = SimpleNamespace(get_stock_solution=lambda: current_stock, serial="head-1")
    rack_model = SimpleNamespace(get_gripper_printer_head=lambda: printer_head)
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        experiment_model=experiment_model,
        rack_model=rack_model,
    )
    manager = CalibrationManager(model)
    manager.ensure_loaded = lambda: None
    manager._emit_readiness = lambda: None
    manager.data = {"runs": list(runs)}
    manager._run_id = active_run_id
    model.calibration_manager = manager
    return model, manager


def _build_dialog(monkeypatch, qapp, tmp_path, runs, *, current_stock="Water", active_run_id=None):
    for method_name in (
        "setup_shortcuts",
        "start_droplet_camera",
        "set_exposure_time",
        "set_flash_delay",
        "set_flash_duration",
        "set_imaging_droplets",
        "set_start_pressure",
        "set_num_pressure_tests",
        "refresh_calibration_memory_recommendation",
        "_refresh_manual_control_lock_state",
    ):
        monkeypatch.setattr(DropletImagingDialog, method_name, lambda self, *args, **kwargs: None)

    model, manager = _build_model_and_manager(
        tmp_path,
        runs,
        current_stock=current_stock,
        active_run_id=active_run_id,
    )
    model.droplet_camera_model = SimpleNamespace(
        flash_duration=1000,
        flash_delay=2000,
        num_droplets=1,
        exposure_time=5000,
        droplet_image_updated=SignalStub(),
        flash_signal=SignalStub(),
    )
    model.machine_model = SimpleNamespace(
        get_print_pressure_bounds=lambda: (0.10, 5.00),
        get_print_pulse_width=lambda: 1400,
        get_current_print_pressure=lambda: 0.80,
    )

    controller = SimpleNamespace(start_read_camera=lambda: None)
    main_window = SimpleNamespace(color_dict={})
    dialog = DropletImagingDialog(main_window, model, controller)
    qapp.processEvents()
    return dialog, manager


def _visible_summary_rows(dialog):
    rows = []
    proxy = dialog.summary_table_proxy_model
    for row in range(proxy.rowCount()):
        source_index = proxy.mapToSource(proxy.index(row, 0))
        rows.append(dialog.summary_table_model.raw_row_at(source_index.row()))
    return rows


def _select_visible_row(dialog, row):
    dialog.summary_table.selectRow(row)


def test_pressure_sweep_summary_rows_enrich_metadata_and_format_timestamps(tmp_path):
    runs = [
        _make_run(
            "run_a",
            sweep_entries=[
                {
                    "timestamp": "2026-03-17T11:00:00Z",
                    "pw_us": 1400,
                    "pressure_psi": 1.20,
                    "mean_nL": 9.8,
                    "cv_pct": 4.2,
                    "valid": True,
                }
            ],
        ),
        _make_run(
            "run_b",
            search_entries=[
                {
                    "timestamp": "bad-ts",
                    "pw_us": 1500,
                    "pressure_psi": 1.55,
                    "mean_nL": 10.4,
                    "cv_pct": 6.1,
                    "valid": False,
                    "invalid_reason": "ratio_limit",
                }
            ],
        ),
        _make_run(
            "run_c",
            sweep_entries=[
                {
                    "timestamp": None,
                    "pw_us": 1600,
                    "pressure_psi": 1.80,
                    "mean_nL": 11.0,
                    "cv_pct": 3.5,
                    "valid": True,
                }
            ],
        ),
    ]
    _model, manager = _build_model_and_manager(tmp_path, runs, active_run_id="run_b")

    rows = manager.get_pressure_sweep_summary_rows()
    by_run = {row["run_id"]: row for row in rows}

    assert by_run["run_a"]["phase"] == "sweep"
    assert by_run["run_a"]["phase_label"] == "Sweep"
    assert by_run["run_a"]["timestamp_display"] == "2026-03-17 11:00:00"
    assert by_run["run_b"]["phase"] == "search"
    assert by_run["run_b"]["phase_label"] == "Search"
    assert by_run["run_b"]["timestamp_display"] == "bad-ts"
    assert by_run["run_b"]["invalid_reason"] == "ratio_limit"
    assert by_run["run_b"]["is_focus_run"] is True
    assert by_run["run_c"]["timestamp_display"] == "Unknown"


def test_pressure_sweep_focus_run_id_prefers_active_then_newest_matching_run(tmp_path):
    runs = [
        _make_run("run_old", sweep_entries=[{"timestamp": "2026-03-17T10:00:00Z", "pw_us": 1400, "pressure_psi": 1.0, "mean_nL": 8.0, "cv_pct": 5.0}]),
        _make_run("run_new", sweep_entries=[{"timestamp": "2026-03-18T10:00:00Z", "pw_us": 1500, "pressure_psi": 1.5, "mean_nL": 9.5, "cv_pct": 4.0}]),
    ]
    _model, manager = _build_model_and_manager(tmp_path, runs, active_run_id="run_old")

    assert manager.get_pressure_sweep_summary_focus_run_id() == "run_old"

    manager._run_id = None

    assert manager.get_pressure_sweep_summary_focus_run_id() == "run_new"


def test_results_table_defaults_to_focus_run_and_filters_update_count(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_old",
            sweep_entries=[
                {"timestamp": "2026-03-17T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.00, "mean_nL": 8.0, "cv_pct": 5.0, "valid": True}
            ],
        ),
        _make_run(
            "run_new",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
                {"timestamp": "2026-03-18T09:05:00Z", "pw_us": 1400, "pressure_psi": 1.10, "mean_nL": 9.7, "cv_pct": 7.5, "valid": False, "invalid_reason": "stability_limit"},
            ],
            search_entries=[
                {"timestamp": "2026-03-18T09:10:00Z", "pw_us": 1500, "pressure_psi": 1.50, "mean_nL": 11.5, "cv_pct": 6.0, "valid": False, "invalid_reason": "ratio_limit"},
                {"timestamp": "2026-03-18T09:11:00Z", "pw_us": 1500, "pressure_psi": 1.60, "mean_nL": 12.0, "cv_pct": 3.0, "valid": True},
            ],
        ),
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs)

    assert dialog.summary_current_run_checkbox.isChecked() is True
    assert dialog.summary_table_proxy_model.rowCount() == 4
    assert dialog.summary_count_label.text() == "Showing 4 of 5 results"

    dialog.summary_valid_only_checkbox.setChecked(True)
    qapp.processEvents()
    assert dialog.summary_table_proxy_model.rowCount() == 2
    assert dialog.summary_count_label.text() == "Showing 2 of 5 results"

    dialog.summary_valid_only_checkbox.setChecked(False)
    dialog.summary_source_combo.setCurrentIndex(dialog.summary_source_combo.findData("search"))
    qapp.processEvents()
    assert dialog.summary_table_proxy_model.rowCount() == 2
    assert all(row["phase"] == "search" for row in _visible_summary_rows(dialog))

    dialog.deleteLater()


def test_results_table_sorts_numeric_columns_and_selection_payload_survives_proxy_changes(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
                {"timestamp": "2026-03-18T09:02:00Z", "pw_us": 1450, "pressure_psi": 1.35, "mean_nL": 10.8, "cv_pct": 5.5, "valid": True},
            ],
            search_entries=[
                {"timestamp": "2026-03-18T09:10:00Z", "pw_us": 1500, "pressure_psi": 1.50, "mean_nL": 11.5, "cv_pct": 6.0, "valid": False, "invalid_reason": "ratio_limit"},
                {"timestamp": "2026-03-18T09:11:00Z", "pw_us": 1500, "pressure_psi": 1.60, "mean_nL": 12.0, "cv_pct": 3.0, "valid": True},
            ],
        )
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs, active_run_id="run_focus")

    pressure_col = dialog.summary_table_model.column_index("pressure_psi")
    mean_col = dialog.summary_table_model.column_index("mean_nL")
    cv_col = dialog.summary_table_model.column_index("cv_pct")

    dialog._apply_summary_sort(pressure_col, Qt.DescendingOrder)
    qapp.processEvents()
    assert _visible_summary_rows(dialog)[0]["pressure_psi"] == pytest.approx(1.60)

    dialog._apply_summary_sort(mean_col, Qt.DescendingOrder)
    dialog.summary_valid_only_checkbox.setChecked(True)
    qapp.processEvents()
    _select_visible_row(dialog, 0)
    qapp.processEvents()
    _, raw = dialog._selected_summary_row()
    assert raw["mean_nL"] == pytest.approx(12.0)
    selected_mean, source = dialog._preferred_char_mean_nL()
    assert selected_mean == pytest.approx(12.0)
    assert source == "selected"

    dialog._apply_summary_sort(cv_col, Qt.AscendingOrder)
    qapp.processEvents()
    assert _visible_summary_rows(dialog)[0]["cv_pct"] == pytest.approx(3.0)
    assert dialog.bridge_preview_btn.text() == "Preview from selected row"

    dialog.deleteLater()


def test_results_detail_strip_and_load_button_reflect_selected_row(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": None, "mean_nL": 7.0, "cv_pct": 8.0, "valid": False, "invalid_reason": "missing_pressure"},
                {"timestamp": "2026-03-18T09:01:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
            search_entries=[
                {"timestamp": "2026-03-18T09:10:00Z", "pw_us": 1500, "pressure_psi": 1.50, "mean_nL": 11.5, "cv_pct": 6.0, "valid": False, "invalid_reason": "ratio_limit"},
            ],
        )
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs, active_run_id="run_focus")

    rows = _visible_summary_rows(dialog)
    missing_pressure_row = next(idx for idx, row in enumerate(rows) if row["pressure_psi"] is None)
    _select_visible_row(dialog, missing_pressure_row)
    qapp.processEvents()

    assert "Recorded" in dialog.summary_detail_meta_label.text()
    assert "Invalid: missing_pressure" in dialog.summary_detail_status_label.text()
    assert dialog.load_selected_button.isEnabled() is False

    flagged_search_row = next(idx for idx, row in enumerate(_visible_summary_rows(dialog)) if row["phase"] == "search")
    _select_visible_row(dialog, flagged_search_row)
    qapp.processEvents()

    assert "Source Search" in dialog.summary_detail_meta_label.text()
    assert "Invalid: ratio_limit" in dialog.summary_detail_status_label.text()
    assert dialog.load_selected_button.isEnabled() is True

    dialog.deleteLater()


def test_results_history_dialog_is_browse_only_and_defaults_to_all_rows(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_old",
            sweep_entries=[
                {"timestamp": "2026-03-17T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.00, "mean_nL": 8.0, "cv_pct": 5.0, "valid": True}
            ],
        ),
        _make_run(
            "run_new",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True}
            ],
            search_entries=[
                {"timestamp": "2026-03-18T09:10:00Z", "pw_us": 1500, "pressure_psi": 1.50, "mean_nL": 11.5, "cv_pct": 6.0, "valid": False, "invalid_reason": "ratio_limit"},
            ],
        ),
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs)

    history = dialog.open_characterization_history_dialog()
    qapp.processEvents()

    assert history.history_current_run_only_checkbox.isChecked() is False
    assert history.history_table_proxy_model.rowCount() == 3
    assert history.history_table_model.column_index("timestamp_display") >= 0
    assert history.history_showing_label.text() == "Showing 3 of 3 results"
    assert not hasattr(history, "load_selected_button")

    history.close()
    dialog.deleteLater()
