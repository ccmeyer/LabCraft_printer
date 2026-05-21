from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.View as calibration_view
from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import DropletImagingDialog


DARK_BLUE = "#063f99"
DARK_RED = "#8a0303"


def _assert_plain_colored_surface(style, color):
    assert f"background-color: {color}" in style
    assert "color: white" in style
    assert "border:" not in style
    assert "font-weight" not in style


def _make_run(run_id, *, stock="Water", sweep_entries=None, search_entries=None, stream_entries=None):
    steps = {
        "pressure_sweep_characterization": [],
        "droplet_search": [],
        "online_stream_calibration": [],
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

    for entry in stream_entries or []:
        tail_phase = {
            "status": entry.get("tail_phase_status", "captured"),
        }
        if entry.get("termination_reason") is not None:
            tail_phase["termination_reason"] = entry.get("termination_reason")
        steps["online_stream_calibration"].append(
            {
                "timestamp": entry.get("timestamp"),
                "settings": {
                    "print_width": entry.get("pw_us"),
                    "print_pressure": entry.get("pressure_psi"),
                },
                "result": {
                    "condition": {
                        "print_pressure_psi": entry.get("pressure_psi"),
                        "print_pulse_width_us": entry.get("pw_us"),
                    },
                    "flow_phase": {
                        "fit_status": entry.get("flow_fit_status"),
                    },
                    "tail_phase": tail_phase,
                    "predicted_stream_duration_us": entry.get("predicted_stream_duration_us"),
                    "predicted_volume_nl": entry.get(
                        "predicted_volume_nl",
                        entry.get("mean_nL"),
                    ),
                    "warnings": list(entry.get("warnings") or []),
                },
            }
        )

    return {
        "run_id": run_id,
        "stock_solution": stock,
        "steps": steps,
    }


def _build_experiment_model(current_stock, *, current_mode="droplet"):
    default_volume = 60.0 if str(current_mode or "").lower() == "stream" else 10.0
    state = {
        "droplet_nL": float(default_volume),
        "fill_droplet_nL": float(default_volume),
        "printing_mode": str(current_mode),
        "stock_concentration": 2.5,
        "units": "mg/mL",
        "applied_record": None,
        "metadata": {
            "fill_droplet_volume_nL": float(default_volume),
            "fill_printing_mode": str(current_mode),
        },
    }

    def _find_option_by_reagent_name(reagent):
        if not reagent:
            return None
        return (
            (str(reagent).lower(), None),
            SimpleNamespace(
                droplet_nL=float(state["droplet_nL"]),
                printing_mode=str(state["printing_mode"]),
            ),
        )

    def _find_key_for_reagent(reagent):
        if not reagent:
            raise ValueError("missing reagent")
        return (str(reagent).lower(), None)

    def _get_plan_for_key(_key):
        return {
            "n_stocks": 1,
            "stocks": [
                {
                    "stock_concentration": float(state["stock_concentration"]),
                    "units": str(state["units"]),
                    "droplet_volume_nL": float(state["droplet_nL"]),
                }
            ],
        }

    def _preview_requantized_for_option(_key, new_droplet_nL, *, quantum=0.1):
        new_droplet_nL = float(new_droplet_nL)
        return {
            "ok": True,
            "n_stocks": 1,
            "new_droplet_nL": new_droplet_nL,
            "rows": [
                {
                    "target_final": 1.0,
                    "achieved_final": 1.0,
                    "error": 0.0,
                    "drops": 1,
                    "delta_per_drop": quantum,
                    "printed_nL_new": new_droplet_nL,
                    "printed_nL_shift": new_droplet_nL - float(state["droplet_nL"]),
                    "units": str(state["units"]),
                }
            ],
        }

    def _store_applied_record(new_volume_nL, kwargs, *, is_fill=False):
        applied = dict(kwargs.get("applied_calibration") or {})
        if not applied:
            return
        state["applied_record"] = {
            "stock_id": str(current_stock),
            "printer_head_id": "head-1",
            "printing_mode": str(current_mode),
            "factor_name": "Fill" if is_fill else str(current_stock).lower(),
            "option_name": "",
            "is_fill": bool(is_fill),
            "measured_volume_nL": float(applied.get("measured_volume_nL", new_volume_nL)),
            "applied_design_volume_nL": float(new_volume_nL),
            "pw_us": applied.get("pw_us"),
            "pressure_psi": applied.get("pressure_psi"),
            "run_id": applied.get("run_id"),
            "phase": applied.get("phase"),
            "timestamp": applied.get("timestamp"),
            "source_row_fingerprint": applied.get("source_row_fingerprint"),
            "recorded_at": "2026-03-18T09:05:00Z",
        }

    def _apply_droplet_volume_for_option(_factor_name, _option_name, new_droplet_nL, **_kwargs):
        state["droplet_nL"] = float(new_droplet_nL)
        _store_applied_record(new_droplet_nL, _kwargs, is_fill=False)
        return {"new_droplet_nL": float(new_droplet_nL)}

    def _preview_fill_requantized(new_fill_droplet_nL):
        new_fill_droplet_nL = float(new_fill_droplet_nL)
        return {
            "ok": True,
            "is_fill": True,
            "rows": [
                {
                    "printed_nL_new": new_fill_droplet_nL,
                    "printed_nL_shift": new_fill_droplet_nL - float(state["fill_droplet_nL"]),
                }
            ],
            "total_drops_old": 1,
            "total_drops_new": 1,
            "total_drops_delta": 0,
            "new_fill_droplet_nL": new_fill_droplet_nL,
        }

    def _apply_fill_droplet_volume(new_fill_droplet_nL, **_kwargs):
        state["fill_droplet_nL"] = float(new_fill_droplet_nL)
        state["metadata"]["fill_droplet_volume_nL"] = float(new_fill_droplet_nL)
        _store_applied_record(new_fill_droplet_nL, _kwargs, is_fill=True)
        return {
            "new_fill_nL": float(new_fill_droplet_nL),
            "total_drops_old": 1,
            "total_drops_new": 1,
            "total_drops_delta": 0,
        }

    def _get_applied_imaging_calibration(**_kwargs):
        record = state.get("applied_record")
        return dict(record) if isinstance(record, dict) else None

    return SimpleNamespace(
        metadata=state["metadata"],
        get_fill_reagent_name=lambda: "Fill",
        find_option_by_reagent_name=_find_option_by_reagent_name,
        find_key_for_reagent=_find_key_for_reagent,
        get_plan_for_key=_get_plan_for_key,
        preview_requantized_for_option=_preview_requantized_for_option,
        apply_droplet_volume_for_option=_apply_droplet_volume_for_option,
        preview_fill_requantized=_preview_fill_requantized,
        apply_fill_droplet_volume=_apply_fill_droplet_volume,
        get_applied_imaging_calibration=_get_applied_imaging_calibration,
    )


def _build_model_and_manager(
    tmp_path,
    runs,
    *,
    current_stock="Water",
    current_mode="droplet",
    active_run_id=None,
    experiment_model=None,
):
    if experiment_model is None:
        experiment_model = _build_experiment_model(current_stock, current_mode=current_mode)
    experiment_model.calibration_file_path = str(tmp_path / "calibration.json")
    experiment_model.get_calibration_file_path = lambda: str(tmp_path / "calibration.json")
    printer_head = SimpleNamespace(
        get_stock_solution=lambda: current_stock,
        get_reagent_name=lambda: current_stock,
        get_printing_mode=lambda: current_mode,
        serial="head-1",
    )
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


def _build_dialog(
    monkeypatch,
    qapp,
    tmp_path,
    runs,
    *,
    current_stock="Water",
    current_mode="droplet",
    active_run_id=None,
    main_window=None,
    experiment_model=None,
):
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
        current_mode=current_mode,
        active_run_id=active_run_id,
        experiment_model=experiment_model,
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

    controller = SimpleNamespace(
        start_read_camera=lambda: None,
        stop_read_camera=lambda: None,
        stop_droplet_camera=lambda: None,
        set_droplet_capture_profile=lambda *args, **kwargs: None,
        set_command_dispatch_interval=lambda *args, **kwargs: None,
        disable_print_profile=lambda: None,
    )
    if main_window is None:
        main_window = SimpleNamespace(color_dict={})
    dialog = DropletImagingDialog(main_window, model, controller)
    qapp.processEvents()
    dialog._bridge_refresh_design_labels()
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


class _FakeCloseEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


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


def test_characterization_summary_rows_include_latest_stream_result_once_and_flag_invalid_streams(tmp_path):
    runs = [
        _make_run(
            "run_stream_valid",
            stream_entries=[
                {
                    "timestamp": "2026-03-18T10:00:00Z",
                    "pw_us": 1800,
                    "pressure_psi": 1.80,
                    "predicted_volume_nl": None,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "not_run",
                },
                {
                    "timestamp": "2026-03-18T10:01:00Z",
                    "pw_us": 1800,
                    "pressure_psi": 1.80,
                    "predicted_volume_nl": 72.6,
                    "predicted_stream_duration_us": 3950,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "captured",
                    "warnings": ["tail_prior_used"],
                },
            ],
        ),
        _make_run(
            "run_stream_invalid",
            stream_entries=[
                {
                    "timestamp": "2026-03-18T10:02:00Z",
                    "pw_us": 1700,
                    "pressure_psi": 1.65,
                    "predicted_volume_nl": None,
                    "flow_fit_status": "unresolved",
                    "tail_phase_status": "skipped",
                    "termination_reason": "tail_not_captured",
                }
            ],
        ),
    ]
    _model, manager = _build_model_and_manager(
        tmp_path,
        runs,
        current_mode="stream",
        active_run_id="run_stream_valid",
    )

    rows = manager.get_characterization_summary_rows()
    stream_rows = [row for row in rows if row["phase"] == "stream"]

    assert len(stream_rows) == 2
    valid_row = next(row for row in stream_rows if row["run_id"] == "run_stream_valid")
    invalid_row = next(row for row in stream_rows if row["run_id"] == "run_stream_invalid")

    assert valid_row["phase_label"] == "Stream"
    assert valid_row["printing_mode"] == "stream"
    assert valid_row["mean_nL"] == pytest.approx(72.6)
    assert valid_row["cv_pct"] is None
    assert valid_row["predicted_stream_duration_us"] == 3950
    assert valid_row["flow_fit_status"] == "ok"
    assert valid_row["tail_phase_status"] == "captured"
    assert valid_row["warnings"] == ["tail_prior_used"]
    assert valid_row["valid"] is True
    assert valid_row["is_focus_run"] is True

    assert invalid_row["valid"] is False
    assert invalid_row["invalid_reason"] == "tail_not_captured"
    assert invalid_row["mean_nL"] is None

    assert manager.get_pressure_sweep_summary_rows() == rows


def test_characterization_summary_rows_keep_multiple_terminal_stream_results_within_one_run(tmp_path):
    runs = [
        _make_run(
            "run_stream_multi",
            stream_entries=[
                {
                    "timestamp": "2026-03-18T10:00:00Z",
                    "pw_us": 1800,
                    "pressure_psi": 1.80,
                    "predicted_volume_nl": None,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "not_run",
                },
                {
                    "timestamp": "2026-03-18T10:01:00Z",
                    "pw_us": 1800,
                    "pressure_psi": 1.80,
                    "predicted_volume_nl": 72.6,
                    "predicted_stream_duration_us": 3950,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "captured",
                },
                {
                    "timestamp": "2026-03-18T10:05:00Z",
                    "pw_us": 1800,
                    "pressure_psi": 1.80,
                    "predicted_volume_nl": None,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "not_run",
                },
                {
                    "timestamp": "2026-03-18T10:06:00Z",
                    "pw_us": 1800,
                    "pressure_psi": 1.80,
                    "predicted_volume_nl": 74.1,
                    "predicted_stream_duration_us": 4010,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "captured",
                },
            ],
        ),
    ]
    _model, manager = _build_model_and_manager(
        tmp_path,
        runs,
        current_mode="stream",
        active_run_id="run_stream_multi",
    )

    rows = manager.get_characterization_summary_rows()
    stream_rows = [row for row in rows if row["phase"] == "stream"]

    assert len(stream_rows) == 2
    assert [row["timestamp"] for row in stream_rows] == [
        "2026-03-18T10:01:00Z",
        "2026-03-18T10:06:00Z",
    ]
    assert [row["mean_nL"] for row in stream_rows] == [
        pytest.approx(72.6),
        pytest.approx(74.1),
    ]
    assert all(row["run_id"] == "run_stream_multi" for row in stream_rows)
    assert all(row["tail_phase_status"] == "captured" for row in stream_rows)


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
    assert dialog.bridge_table.rowCount() == 1
    assert dialog.bridge_apply_btn.isEnabled() is True
    assert "12.000 nL" in dialog.bridge_status_label.text()
    assert dialog.bridge_table.horizontalHeaderItem(0).text() == "Target"
    assert dialog.bridge_table.horizontalHeaderItem(1).text() == "Achievable"
    assert dialog.bridge_table.horizontalHeaderItem(2).text() == "Error (%)"
    assert dialog.bridge_table.item(0, 0).text() == "1.00"
    assert dialog.bridge_table.item(0, 1).text() == "1.00"
    assert dialog.bridge_table.item(0, 2).text() == "+0.00%"
    assert dialog.bridge_table.item(0, 4).text() == "0.1"
    assert dialog.bridge_table.item(0, 5).text() == "12.00"
    assert dialog.bridge_table.item(0, 6).text() == "+2.00"

    dialog.deleteLater()


def test_bridge_table_uses_stable_geometry_for_many_design_targets(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_mg",
            sweep_entries=[
                {
                    "timestamp": "2026-04-29T18:03:00Z",
                    "pw_us": 1400,
                    "pressure_psi": 1.20,
                    "mean_nL": 9.5,
                    "cv_pct": 3.0,
                    "valid": True,
                }
            ],
        )
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs, active_run_id="run_mg")

    def _preview_eight_targets(_key, new_droplet_nL, *, quantum=0.1):
        new_droplet_nL = float(new_droplet_nL)
        rows = []
        for idx, target in enumerate((5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0), start=1):
            rows.append(
                {
                    "target_final": target,
                    "achieved_final": target,
                    "error": 0.0,
                    "drops": idx,
                    "delta_per_drop": quantum,
                    "printed_nL_new": idx * new_droplet_nL,
                    "printed_nL_shift": 0.0,
                    "units": "mM",
                }
            )
        return {
            "ok": True,
            "n_stocks": 1,
            "new_droplet_nL": new_droplet_nL,
            "rows": rows,
        }

    monkeypatch.setattr(
        dialog.model.experiment_model,
        "preview_requantized_for_option",
        _preview_eight_targets,
    )

    _select_visible_row(dialog, 0)
    qapp.processEvents()

    assert dialog.bridge_table.rowCount() == 8
    assert dialog.bridge_table.sizeAdjustPolicy() == calibration_view.QtWidgets.QAbstractScrollArea.AdjustIgnored
    assert dialog.bridge_table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert dialog.bridge_table.sizePolicy().verticalPolicy() == calibration_view.QtWidgets.QSizePolicy.Fixed
    assert dialog.bridge_table.minimumHeight() == 280
    assert dialog.bridge_table.maximumHeight() == 280

    dialog.deleteLater()


def test_stream_results_filter_and_detail_strip_show_stream_metadata(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
            stream_entries=[
                {
                    "timestamp": "2026-03-18T09:10:00Z",
                    "pw_us": 1850,
                    "pressure_psi": 1.85,
                    "predicted_volume_nl": None,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "not_run",
                },
                {
                    "timestamp": "2026-03-18T09:11:00Z",
                    "pw_us": 1850,
                    "pressure_psi": 1.85,
                    "predicted_volume_nl": 74.25,
                    "predicted_stream_duration_us": 4025,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "captured",
                    "warnings": ["tail_prior_used"],
                },
            ],
        )
    ]
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        current_mode="stream",
        active_run_id="run_focus",
    )

    assert (
        dialog.summary_table_model.headerData(
            dialog.summary_table_model.column_index("mean_nL"),
            Qt.Horizontal,
        )
        == "Volume (nL)"
    )

    dialog.summary_source_combo.setCurrentIndex(dialog.summary_source_combo.findData("stream"))
    qapp.processEvents()
    assert dialog.summary_table_proxy_model.rowCount() == 1
    assert _visible_summary_rows(dialog)[0]["phase"] == "stream"

    _select_visible_row(dialog, 0)
    qapp.processEvents()

    cv_col = dialog.summary_table_model.column_index("cv_pct")
    assert dialog.summary_table_proxy_model.index(0, cv_col).data() == ""
    assert "Predicted duration 4025 us" in dialog.summary_detail_status_label.text()
    assert "Flow fit ok" in dialog.summary_detail_status_label.text()
    assert "Tail captured" in dialog.summary_detail_status_label.text()
    assert "Warnings: tail_prior_used" in dialog.summary_detail_status_label.text()

    history = dialog.open_characterization_history_dialog()
    history.history_source_combo.setCurrentIndex(history.history_source_combo.findData("stream"))
    qapp.processEvents()
    assert history.history_table_proxy_model.rowCount() == 1
    history.close()
    dialog.deleteLater()


def test_stream_selection_enables_bridge_for_stream_mode(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            stream_entries=[
                {
                    "timestamp": "2026-03-18T09:11:00Z",
                    "pw_us": 1850,
                    "pressure_psi": 1.85,
                    "predicted_volume_nl": 74.25,
                    "predicted_stream_duration_us": 4025,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "captured",
                },
            ],
        )
    ]
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        current_mode="stream",
        active_run_id="run_focus",
    )

    _select_visible_row(dialog, 0)
    qapp.processEvents()

    assert dialog.load_selected_button.isEnabled() is True
    assert dialog.bridge_table.rowCount() == 1
    assert dialog.bridge_apply_btn.isEnabled() is True
    assert "ejection volume of 74.250 nL" in dialog.bridge_status_label.text()

    dialog.deleteLater()


def test_stream_selection_blocks_bridge_and_load_for_droplet_mode(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            stream_entries=[
                {
                    "timestamp": "2026-03-18T09:11:00Z",
                    "pw_us": 1850,
                    "pressure_psi": 1.85,
                    "predicted_volume_nl": 74.25,
                    "predicted_stream_duration_us": 4025,
                    "flow_fit_status": "ok",
                    "tail_phase_status": "captured",
                },
            ],
        )
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs, current_mode="droplet")

    _select_visible_row(dialog, 0)
    qapp.processEvents()

    assert dialog.load_selected_button.isEnabled() is False
    assert dialog.bridge_table.rowCount() == 0
    assert dialog.bridge_apply_btn.isEnabled() is False
    assert "stream mode" in dialog.bridge_status_label.text().lower()
    assert "droplet mode" in dialog.bridge_status_label.text().lower()

    dialog.deleteLater()


def test_droplet_selection_blocks_bridge_and_load_for_stream_mode(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            search_entries=[
                {
                    "timestamp": "2026-03-18T09:11:00Z",
                    "pw_us": 1500,
                    "pressure_psi": 1.55,
                    "mean_nL": 12.0,
                    "cv_pct": 3.2,
                    "valid": True,
                },
            ],
        )
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs, current_mode="stream")

    _select_visible_row(dialog, 0)
    qapp.processEvents()

    assert dialog.load_selected_button.isEnabled() is False
    assert dialog.bridge_table.rowCount() == 0
    assert dialog.bridge_apply_btn.isEnabled() is False
    assert "droplet mode" in dialog.bridge_status_label.text().lower()
    assert "stream mode" in dialog.bridge_status_label.text().lower()

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
    assert dialog.bridge_table.rowCount() == 1
    assert dialog.bridge_apply_btn.isEnabled() is True
    assert "flagged invalid" in dialog.bridge_status_label.text()

    flagged_search_row = next(idx for idx, row in enumerate(_visible_summary_rows(dialog)) if row["phase"] == "search")
    _select_visible_row(dialog, flagged_search_row)
    qapp.processEvents()

    assert "Source Search" in dialog.summary_detail_meta_label.text()
    assert "Invalid: ratio_limit" in dialog.summary_detail_status_label.text()
    assert dialog.load_selected_button.isEnabled() is True
    assert dialog.bridge_table.rowCount() == 1
    assert dialog.bridge_apply_btn.isEnabled() is True
    assert "flagged invalid" in dialog.bridge_status_label.text()

    dialog.deleteLater()


def test_bridge_requires_explicit_selection_and_starts_empty(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:01:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
        )
    ]
    dialog, _manager = _build_dialog(monkeypatch, qapp, tmp_path, runs, active_run_id="run_focus")

    assert dialog.summary_table.selectionModel().selectedRows() == []
    assert dialog.bridge_table.rowCount() == 0
    assert dialog.bridge_apply_btn.isEnabled() is False
    assert "Select a characterization result" in dialog.bridge_status_label.text()
    assert "No calibration applied" in dialog.summary_applied_calibration_banner.text()
    _assert_plain_colored_surface(dialog.summary_applied_calibration_banner.styleSheet(), DARK_RED)
    summary_layout = dialog.summary_group.layout()
    assert summary_layout.itemAt(0).widget() is dialog.summary_applied_calibration_banner
    assert summary_layout.itemAt(1).layout() is dialog.summary_toolbar
    marker_col = dialog.summary_table_model.column_index("applied_marker")
    assert dialog.summary_table_model.data(dialog.summary_table_model.index(0, marker_col), Qt.DisplayRole) == ""

    dialog.deleteLater()


def test_apply_marks_summary_row_and_persists_across_reopen(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
                {"timestamp": "2026-03-18T09:02:00Z", "pw_us": 1450, "pressure_psi": 1.35, "mean_nL": 10.8, "cv_pct": 5.5, "valid": True},
            ],
        )
    ]
    main_window = SimpleNamespace(color_dict={})
    experiment_model = _build_experiment_model("Water", current_mode="droplet")
    info_calls = []
    monkeypatch.setattr(
        DropletImagingDialog,
        "refresh_calibration_memory_recommendation",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        DropletImagingDialog,
        "_refresh_manual_control_lock_state",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "information", lambda *args, **kwargs: info_calls.append(True))
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)

    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
        main_window=main_window,
        experiment_model=experiment_model,
    )
    settings_calls = []
    _manager.changeSettingsRequested.connect(
        lambda settings, callback: settings_calls.append(dict(settings)) or (callback() if callable(callback) else None)
    )
    dialog._apply_summary_sort(dialog.summary_table_model.column_index("mean_nL"), Qt.DescendingOrder)
    qapp.processEvents()
    _select_visible_row(dialog, 0)
    qapp.processEvents()

    _, raw = dialog._selected_summary_row()
    source_row = raw["_source_row"]
    dialog._apply_previewed_droplet_volume()
    qapp.processEvents()

    bg = dialog.summary_table_model.data(dialog.summary_table_model.index(source_row, 0), Qt.BackgroundRole)
    assert bg is not None
    marker_col = dialog.summary_table_model.column_index("applied_marker")
    marker_index = dialog.summary_table_model.index(source_row, marker_col)
    assert dialog.summary_table_model.data(marker_index, Qt.DisplayRole) == "✓"
    assert dialog.summary_table_model.data(marker_index, Qt.ToolTipRole) == "Applied to design"
    applied_record = experiment_model.get_applied_imaging_calibration()
    assert tuple(applied_record["source_row_fingerprint"]) == tuple(dialog._summary_row_fingerprint(raw))
    assert "Applied: Run" in dialog.bridge_applied_calibration_label.text()
    _assert_plain_colored_surface(dialog.summary_applied_calibration_banner.styleSheet(), DARK_BLUE)
    assert dialog.bridge_apply_btn.isEnabled() is False
    assert dialog.bridge_apply_btn.text() == "Selected calibration is applied"
    assert settings_calls[-1] == {"print_pulse_width": 1450, "print_pressure": 1.35}
    assert info_calls

    dialog.summary_valid_only_checkbox.setChecked(True)
    qapp.processEvents()
    assert dialog.summary_table_model.data(dialog.summary_table_model.index(source_row, 0), Qt.BackgroundRole) is not None

    dialog.deleteLater()
    qapp.processEvents()
    if hasattr(main_window, "_droplet_imaging_applied_summary_rows"):
        delattr(main_window, "_droplet_imaging_applied_summary_rows")

    reopened, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
        main_window=main_window,
        experiment_model=experiment_model,
    )
    reopened_bg = reopened.summary_table_model.data(reopened.summary_table_model.index(source_row, 0), Qt.BackgroundRole)
    assert reopened_bg is not None
    assert reopened.summary_table_model.data(reopened.summary_table_model.index(source_row, marker_col), Qt.DisplayRole) == "✓"

    reopened.deleteLater()


def test_selecting_different_summary_row_keeps_applied_row_highlight(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
                {"timestamp": "2026-03-18T09:02:00Z", "pw_us": 1450, "pressure_psi": 1.35, "mean_nL": 10.8, "cv_pct": 5.5, "valid": True},
            ],
        )
    ]
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)
    experiment_model = _build_experiment_model("Water", current_mode="droplet")
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
        experiment_model=experiment_model,
    )
    dialog._apply_summary_sort(dialog.summary_table_model.column_index("mean_nL"), Qt.DescendingOrder)
    qapp.processEvents()
    _select_visible_row(dialog, 0)
    qapp.processEvents()
    _, applied_raw = dialog._selected_summary_row()
    applied_source_row = applied_raw["_source_row"]

    dialog._apply_previewed_droplet_volume()
    qapp.processEvents()
    assert dialog.summary_table_model.data(
        dialog.summary_table_model.index(applied_source_row, 0),
        Qt.BackgroundRole,
    ) is not None

    _select_visible_row(dialog, 1)
    qapp.processEvents()
    _, selected_raw = dialog._selected_summary_row()
    assert selected_raw["_source_row"] != applied_source_row
    assert dialog.summary_table_model.data(
        dialog.summary_table_model.index(applied_source_row, 0),
        Qt.BackgroundRole,
    ) is not None
    assert dialog.bridge_apply_btn.isEnabled() is True
    assert dialog.bridge_apply_btn.text() == "Apply selected calibration to design"
    _assert_plain_colored_surface(dialog.bridge_apply_btn.styleSheet(), DARK_BLUE)

    _select_visible_row(dialog, 0)
    qapp.processEvents()
    assert dialog.bridge_apply_btn.isEnabled() is False
    assert dialog.bridge_apply_btn.text() == "Selected calibration is applied"
    assert DARK_BLUE not in dialog.bridge_apply_btn.styleSheet()

    dialog.deleteLater()


def test_load_selected_summary_row_does_not_create_applied_record(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
        )
    ]
    experiment_model = _build_experiment_model("Water", current_mode="droplet")
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
        experiment_model=experiment_model,
    )
    _select_visible_row(dialog, 0)
    qapp.processEvents()

    dialog.load_selected_summary_row()
    qapp.processEvents()

    assert experiment_model.get_applied_imaging_calibration() is None
    marker_col = dialog.summary_table_model.column_index("applied_marker")
    assert dialog.summary_table_model.data(dialog.summary_table_model.index(0, marker_col), Qt.DisplayRole) == ""
    assert dialog.summary_table_model.data(dialog.summary_table_model.index(0, 0), Qt.BackgroundRole) is None
    assert "No calibration applied" in dialog.summary_applied_calibration_banner.text()

    dialog.deleteLater()


def test_apply_fill_calibration_sets_print_parameters(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "fill_run",
            stock="Fill",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1325, "pressure_psi": 0.95, "mean_nL": 9.5, "cv_pct": 4.0, "valid": True},
            ],
        )
    ]
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)
    experiment_model = _build_experiment_model("Fill", current_mode="droplet")
    dialog, manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        current_stock="Fill",
        active_run_id="fill_run",
        experiment_model=experiment_model,
    )
    settings_calls = []
    manager.changeSettingsRequested.connect(
        lambda settings, callback: settings_calls.append(dict(settings)) or (callback() if callable(callback) else None)
    )
    _select_visible_row(dialog, 0)
    qapp.processEvents()

    dialog._apply_previewed_droplet_volume()
    qapp.processEvents()

    assert experiment_model.get_applied_imaging_calibration()["is_fill"] is True
    assert settings_calls[-1] == {"print_pulse_width": 1325, "print_pressure": 0.95}

    dialog.deleteLater()


def test_apply_calibration_warns_when_settings_cannot_be_changed(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
        )
    ]

    class FailingSignal:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError("settings unavailable")

    warnings = []
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)
    experiment_model = _build_experiment_model("Water", current_mode="droplet")
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
        experiment_model=experiment_model,
    )
    dialog.model.calibration_manager = SimpleNamespace(changeSettingsRequested=FailingSignal())
    dialog.controller = SimpleNamespace()
    _select_visible_row(dialog, 0)
    qapp.processEvents()

    dialog._apply_previewed_droplet_volume()
    qapp.processEvents()

    assert experiment_model.get_applied_imaging_calibration() is not None
    assert any(args[1] == "Settings not changed" for args in warnings)

    dialog.deleteLater()


def test_close_without_applied_calibration_prompts_and_cancel_keeps_open(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
        )
    ]
    prompt_calls = []
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: prompt_calls.append(args) or calibration_view.QtWidgets.QMessageBox.No,
    )
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
    )
    event = _FakeCloseEvent()

    dialog.closeEvent(event)

    assert prompt_calls
    assert event.ignored is True
    assert event.accepted is False
    assert getattr(dialog, "_stream_capture_dialog_closing", False) is False

    dialog.deleteLater()


def test_close_with_applied_calibration_does_not_prompt(monkeypatch, qapp, tmp_path):
    runs = [
        _make_run(
            "run_focus",
            sweep_entries=[
                {"timestamp": "2026-03-18T09:00:00Z", "pw_us": 1400, "pressure_psi": 1.20, "mean_nL": 10.0, "cv_pct": 4.0, "valid": True},
            ],
        )
    ]
    prompt_calls = []
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(calibration_view.QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: prompt_calls.append(args) or calibration_view.QtWidgets.QMessageBox.No,
    )
    dialog, _manager = _build_dialog(
        monkeypatch,
        qapp,
        tmp_path,
        runs,
        active_run_id="run_focus",
    )
    _select_visible_row(dialog, 0)
    qapp.processEvents()
    dialog._apply_previewed_droplet_volume()
    qapp.processEvents()
    event = _FakeCloseEvent()

    dialog.closeEvent(event)

    assert prompt_calls == []
    assert event.accepted is True
    assert event.ignored is False

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
