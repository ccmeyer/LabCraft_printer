from __future__ import annotations

from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from ApplicationComposition import SIMULATION_RUNTIME_CONTEXT
from CalibrationClasses.Model import (
    CalibrationManager,
    TransientCharacterizationCandidate,
)
from CalibrationClasses.View import (
    CharacterizationSummaryProxyModel,
    CharacterizationSummaryTableModel,
    DropletImagingDialog,
)
from tools.sil.synthetic_calibration import (
    CalibrationGenerationRequestV1,
    SyntheticCalibrationProvider,
)


def _result():
    request = CalibrationGenerationRequestV1(
        seed=4,
        profile_id="nominal_droplet",
        virtual_run_id="ui-run",
        printer_head_id="head-1",
        stock_id="stock-1",
        factor_name="Factor A",
        option_name=None,
        is_fill=False,
        requested_mode="droplet",
        nominal_volume_nL=10.0,
        volume_variation_fraction=0.05,
        pressure_bounds_psi=(1.2, 1.2),
        pulse_width_bounds_us=(1400, 1400),
    )
    return SyntheticCalibrationProvider().generate(request)


def _candidate(result=None):
    result = result or _result()
    return TransientCharacterizationCandidate(
        candidate_id=result.result_fingerprint,
        source_kind="sil_synthetic_calibration",
        summary_row=result.to_application_summary_row(),
        request_fingerprint=result.request_fingerprint,
        result_fingerprint=result.result_fingerprint,
        printer_head_id=result.printer_head_id,
        stock_id=result.stock_id,
        factor_name=result.factor_name,
        option_name=result.option_name,
        is_fill=result.is_fill,
        printing_mode=result.applied_printing_mode,
        requested_printing_mode=result.original_printing_mode,
    )


def _stream_result():
    request = CalibrationGenerationRequestV1(
        seed=4,
        profile_id="droplet_to_stream",
        virtual_run_id="ui-stream-run",
        printer_head_id="head-1",
        stock_id="stock-1",
        factor_name="Factor A",
        option_name=None,
        is_fill=False,
        requested_mode="droplet",
        nominal_volume_nL=25.0,
        volume_variation_fraction=0.6,
        pressure_bounds_psi=(1.2, 1.2),
        pulse_width_bounds_us=(1400, 1400),
    )
    return SyntheticCalibrationProvider().generate(request)


def _manager():
    context = {
        "printer_head_id": "head-1",
        "stock_id": "stock-1",
        "factor_name": "Factor A",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": 10.0,
    }
    head = SimpleNamespace(serial="head-1")
    experiment = SimpleNamespace(
        _resolve_applied_imaging_context=lambda **_kwargs: dict(context),
    )
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: head),
        experiment_model=experiment,
    )
    manager = CalibrationManager(model)
    manager.ensure_loaded = lambda: None
    manager.data = {"runs": []}
    model.calibration_manager = manager
    return manager, context


def test_transient_surface_requires_exact_identity_and_never_persists_rows():
    manager, context = _manager()
    candidate = _candidate()

    manager.set_transient_characterization_candidate(candidate)
    rows = manager.get_characterization_summary_rows()

    assert len(rows) == 1
    assert rows[0]["phase_label"] == "Synthetic"
    assert rows[0]["source_filter_key"] == "synthetic"
    assert manager.validate_characterization_candidate_for_application(rows[0])["ok"]
    assert manager.data == {"runs": []}

    context["printer_head_id"] = "different-head"
    assert manager.get_characterization_summary_rows() == []
    validation = manager.validate_characterization_candidate_for_application(rows[0])
    assert validation["ok"] is False
    assert validation["code"] == "identity_mismatch"


def test_transient_surface_rejects_altered_fingerprints():
    manager, _context = _manager()
    result = _result()
    row = result.to_application_summary_row()
    row["synthetic_result_fingerprint"] = "0" * 64
    candidate = TransientCharacterizationCandidate(
        candidate_id=result.result_fingerprint,
        source_kind="sil_synthetic_calibration",
        summary_row=row,
        request_fingerprint=result.request_fingerprint,
        result_fingerprint=result.result_fingerprint,
        printer_head_id=result.printer_head_id,
        stock_id=result.stock_id,
        factor_name=result.factor_name,
        option_name=None,
        is_fill=False,
        printing_mode="droplet",
    )

    try:
        manager.set_transient_characterization_candidate(candidate)
    except ValueError as exc:
        assert "result fingerprint" in str(exc)
    else:
        raise AssertionError("altered transient fingerprint was accepted")


def test_transient_surface_accepts_mode_switch_against_requested_context():
    manager, context = _manager()
    result = _stream_result()
    candidate = _candidate(result)

    manager.set_transient_characterization_candidate(candidate)
    row = manager.get_characterization_summary_rows()[0]

    assert row["printing_mode"] == "stream"
    assert row["original_printing_mode"] == "droplet"
    assert row["applied_printing_mode"] == "stream"
    assert manager.validate_characterization_candidate_for_application(row)["ok"]

    context["printing_mode"] = "stream"
    validation = manager.validate_characterization_candidate_for_application(row)
    assert validation["code"] == "identity_mismatch"


def test_summary_model_visibly_marks_and_filters_synthetic_rows(qapp):
    row = _result().to_application_summary_row()
    row.update({"phase_label": "Synthetic", "source_filter_key": "synthetic"})
    model = CharacterizationSummaryTableModel()
    proxy = CharacterizationSummaryProxyModel()
    proxy.setSourceModel(model)
    model.set_rows([row])

    proxy.setSourceFilter("synthetic")
    assert proxy.rowCount() == 1
    source_index = model.index(0, model.column_index("phase_label"))
    assert source_index.data(QtCore.Qt.ItemDataRole.DisplayRole) == "Synthetic"
    assert "Synthetic SIL result" in source_index.data(QtCore.Qt.ItemDataRole.ToolTipRole)
    assert source_index.data(QtCore.Qt.ItemDataRole.BackgroundRole) is not None


def test_presentation_mode_rejects_noncanonical_runtime_before_camera_start(qapp):
    calls = []
    main_window = SimpleNamespace(color_dict={}, runtime_context=object())
    model = SimpleNamespace(droplet_camera_model=object(), refuel_camera_model=None)
    controller = SimpleNamespace(start_droplet_camera=lambda: calls.append("camera"))

    try:
        DropletImagingDialog(
            main_window,
            model,
            controller,
            result_presentation_only=True,
        )
    except RuntimeError as exc:
        assert "canonical simulation runtime" in str(exc)
    else:
        raise AssertionError("non-simulation result presentation was accepted")
    assert calls == []
    assert SIMULATION_RUNTIME_CONTEXT.is_simulation is True


def test_presentation_mode_opens_and_closes_without_camera_lifecycle(
    monkeypatch,
    qapp,
    tmp_path,
):
    manager, context = _manager()
    model = manager.model
    manager._emit_readiness = lambda: None
    stream_candidate = _candidate(_stream_result())
    manager.set_transient_characterization_candidate(stream_candidate)
    model.droplet_camera_model = SimpleNamespace(
        flash_duration=1000,
        flash_delay=2000,
        num_droplets=1,
        exposure_time=5000,
        droplet_image_updated=SignalStub(),
        flash_signal=SignalStub(),
    )
    model.refuel_camera_model = None
    model.machine_model = SimpleNamespace(
        get_print_pressure_bounds=lambda: (0.1, 5.0),
        get_print_pulse_width=lambda: 1400,
        get_current_print_pressure=lambda: 1.2,
    )
    calls = []

    def forbidden(name):
        return lambda *args, **kwargs: calls.append(name)

    controller = SimpleNamespace(
        start_droplet_camera=forbidden("start_droplet_camera"),
        stop_droplet_camera=forbidden("stop_droplet_camera"),
        start_read_camera=forbidden("start_read_camera"),
        stop_read_camera=forbidden("stop_read_camera"),
        set_droplet_capture_profile=forbidden("set_droplet_capture_profile"),
        set_command_dispatch_interval=forbidden("set_command_dispatch_interval"),
        disable_print_profile=forbidden("disable_print_profile"),
        get_array_run_state=lambda: "idle",
        machine=SimpleNamespace(check_if_all_completed=lambda: True),
    )
    main_window = SimpleNamespace(
        color_dict={},
        runtime_context=SIMULATION_RUNTIME_CONTEXT,
    )
    monkeypatch.setattr(
        DropletImagingDialog,
        "refresh_calibration_memory_recommendation",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "CalibrationClasses.View.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )

    dialog = DropletImagingDialog(
        main_window,
        model,
        controller,
        result_presentation_only=True,
        transient_candidate_id=stream_candidate.candidate_id,
    )
    dialog.show()
    qapp.processEvents()

    assert dialog.synthetic_calibration_banner.isVisible()
    assert dialog.synthetic_calibration_mode_label.isVisible()
    assert "Droplet → Stream" in dialog.synthetic_calibration_mode_label.text()
    assert "Stream" in dialog.windowTitle()
    assert dialog.summary_table_proxy_model.rowCount() == 1
    assert dialog.control_panel_scroll.isHidden()
    assert dialog.analysis_panel.isHidden()
    dialog.close()
    qapp.processEvents()
    assert calls == []
