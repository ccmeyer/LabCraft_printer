import json
from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

import View
from QualificationReports import discover_report_entries, load_report
from QualificationView import MachineQualificationWindow


def _sample_report(run_dir: Path):
    return {
        "schema_version": "qualification_report_v1",
        "manifest": {
            "manifest_id": "factory_acceptance_v3",
            "name": "Factory Acceptance v3",
            "profile": "FULL",
        },
        "machine": {
            "machine_id": "LC-TEST",
            "machine_uuid": "uuid",
            "assigned_at": "2026-05-15T00:00:00Z",
        },
        "run": {
            "run_dir": str(run_dir),
            "raw_selftest_path": str(run_dir / "raw_selftest.json"),
            "report_path": str(run_dir / "report.json"),
            "summary_csv_path": str(run_dir / "summary.csv"),
            "fixture_id": "",
        },
        "overall_status": "pass",
        "run_id": 123,
        "profile": "FULL",
        "started_at": "2026-05-15T00:00:00Z",
        "finished_at": "2026-05-15T00:00:10Z",
        "results": [
            {
                "test_id": 2007,
                "name": "motion_home_repeatability_factory",
                "pass": True,
                "metrics": {"x_span": 6, "y_span": 5, "ret_err": 0},
                "timestamp": "2026-05-15T00:00:04Z",
            },
            {
                "test_id": 2201,
                "name": "pressure_hold_leak_factory",
                "pass": True,
                "metrics": {"slope_raw_min": 1164, "ready_miss": 0, "timeout": 0},
                "timestamp": "2026-05-15T00:00:10Z",
            },
        ],
        "host_checks": [
            {"name": "hello_ack", "pass": True, "details": {"seq8": 1}},
        ],
        "analysis": {
            "items": [
                {
                    "item_kind": "firmware_result",
                    "test_id": 2007,
                    "name": "motion_home_repeatability_factory",
                    "category": "motion",
                    "status": "pass",
                    "failure_domain": "none",
                    "message": "Raw firmware result passed.",
                },
                {
                    "item_kind": "firmware_result",
                    "test_id": 2201,
                    "name": "pressure_hold_leak_factory",
                    "category": "pressure",
                    "status": "pass",
                    "failure_domain": "none",
                    "message": "Raw firmware result passed.",
                },
                {
                    "item_kind": "host_check",
                    "name": "hello_ack",
                    "status": "pass",
                    "failure_domain": "none",
                    "message": "Host check passed.",
                },
            ],
            "metric_evaluations": [],
        },
        "warnings": [],
    }


def _write_sample_report(root: Path):
    run_dir = root / "qualification" / "LC-TEST" / "20260515T000000Z"
    run_dir.mkdir(parents=True)
    report = _sample_report(run_dir)
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (run_dir / "raw_selftest.json").write_text("{}", encoding="utf-8")
    (run_dir / "summary.csv").write_text("header\n", encoding="utf-8")
    return run_dir / "report.json"


class _ReportController:
    def __init__(self, root: Path):
        self.root = root

    def list_qualification_reports(self):
        return discover_report_entries(self.root)

    def load_qualification_report(self, report_path):
        return load_report(report_path)

    def qualification_timing_estimates(self):
        from QualificationTiming import build_timing_model

        return build_timing_model(self.root)


def test_machine_qualification_window_loads_report_into_subsystem_tabs(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    qapp.processEvents()

    assert window.report_list.count() == 1
    assert window.summary_labels["machine"].text() == "LC-TEST"
    assert window.result_tables["All"].rowCount() == 3
    assert window.result_tables["Motion"].rowCount() == 1
    assert window.result_tables["Pressure"].rowCount() == 1
    assert window.result_tables["Host Checks"].rowCount() == 1
    assert window.artifacts_table.rowCount() >= 4

    window.close()


def _suite_row(window, manifest_id):
    for idx, entry in enumerate(window._suite_entries):
        if entry.manifest_id == manifest_id:
            return idx
    raise AssertionError(f"Suite not found: {manifest_id}")


def _campaign_row(window, campaign_id):
    for idx, entry in enumerate(window._campaign_entries):
        if entry.campaign_id == campaign_id:
            return idx
    raise AssertionError(f"Campaign not found: {campaign_id}")


def _plan_row_for_test(window, test_id):
    for row in range(window.test_plan_table.rowCount()):
        item = window.test_plan_table.item(row, 2)
        if item is not None and item.text() == str(test_id):
            return row
    raise AssertionError(f"Test row not found: {test_id}")


def test_machine_qualification_window_has_run_and_review_tabs(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))

    assert window.main_tabs.tabText(0) == "Run Qualification"
    assert window.main_tabs.tabText(1) == "Review Results"
    assert window.campaign_list.count() >= 1
    assert [entry.campaign_id for entry in window._campaign_entries[:2]] == [
        "machine_full_qualification_v1",
        "gripper_seal_stress_campaign_v1",
    ]
    assert window.suite_list.count() >= 5
    assert window.minimumWidth() >= 1280
    assert window.minimumHeight() >= 820

    window.close()


def test_run_tab_lists_campaigns_and_populates_campaign_plan(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))

    window.campaign_list.setCurrentRow(_campaign_row(window, "machine_full_qualification_v1"))
    qapp.processEvents()

    assert window._selected_run_kind == "campaign"
    assert window.campaign_queue_table.isHidden() is False
    assert window.campaign_queue_table.rowCount() == 4
    assert "motion_envelope_v1" in window.campaign_queue_table.item(0, 2).text()
    assert "pressure_regulator_v1" in window.campaign_queue_table.item(1, 2).text()
    assert (1, 2012) in window._plan_row_by_key
    assert (2, 2210) in window._plan_row_by_key
    assert (3, 2473) in window._plan_row_by_key
    assert (4, 2510) in window._plan_row_by_key
    row = window._plan_row_by_key[(3, 2473)]
    assert window.test_plan_table.item(row, 1).text() == "valve_characterization_v1"

    window.close()


class _CampaignStartController(_ReportController):
    def __init__(self, root: Path):
        super().__init__(root)
        self.started_config = None

    def qualification_campaign_output_root(self):
        return self.root / "qualification_campaigns"

    def qualification_output_root(self):
        return self.root / "qualification"

    def start_qualification_run(self, config):
        self.started_config = dict(config)
        return True


def test_campaign_start_config_includes_campaign_fields(tmp_path, qapp):
    _write_sample_report(tmp_path)
    controller = _CampaignStartController(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, controller)

    window.campaign_list.setCurrentRow(_campaign_row(window, "machine_full_qualification_v1"))
    window.continue_on_failure_check.setChecked(True)
    window._confirm_qualification_start = lambda _config: True
    window._on_start_clicked()

    assert controller.started_config["run_kind"] == "campaign"
    assert controller.started_config["campaign_id"] == "machine_full_qualification_v1"
    assert str(controller.started_config["campaign_output_root"]).endswith("qualification_campaigns")
    assert str(controller.started_config["suite_output_root"]).endswith("qualification")
    assert controller.started_config["continue_on_failure"] is True
    assert window.campaign_queue_table.item(0, 0).text() == "In progress"

    window._set_run_busy(False)
    window.close()


def test_run_tab_populates_selected_suite_test_plan(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    window.suite_list.setCurrentRow(_suite_row(window, "factory_acceptance_v3"))
    qapp.processEvents()

    row = _plan_row_for_test(window, 2007)

    assert window.test_plan_table.item(row, 0).text() == "Not run"
    assert window.test_plan_table.item(row, 3).text() == "Motion"
    assert window.test_plan_table.item(row, 4).text() == "Motion home repeatability"
    assert window.test_plan_table.item(row, 5).text() == "00:04"
    assert "x_span" in window.test_plan_table.item(row, 8).text()

    window.close()


def test_run_tab_marks_first_row_in_progress_after_queueing(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    window.suite_list.setCurrentRow(_suite_row(window, "factory_acceptance_v3"))

    window._set_all_plan_status("Queued")
    window._mark_next_queued_in_progress()

    assert window.test_plan_table.item(0, 0).text() == "In progress"

    window.close()


def test_selftest_result_event_updates_row_and_advances_next_queued(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    window.suite_list.setCurrentRow(_suite_row(window, "factory_acceptance_v3"))
    first_id = int(window.test_plan_table.item(0, 2).text())

    window._set_all_plan_status("Queued")
    window._mark_next_queued_in_progress()
    window._on_selftest_event(
        {
            "schema": "selftest_event_v1",
            "event": "selftest_result",
            "test_id": first_id,
            "name": "first",
            "pass": True,
        }
    )

    assert window.test_plan_table.item(0, 0).text() == "Passed"
    assert window.test_plan_table.item(1, 0).text() == "In progress"

    window.close()


def test_campaign_events_update_queue_and_scoped_test_rows(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    window.campaign_list.setCurrentRow(_campaign_row(window, "machine_full_qualification_v1"))
    qapp.processEvents()

    window._set_all_campaign_status("Queued")
    window._set_all_plan_status("Queued")
    window._on_campaign_event(
        {
            "event": "campaign_step_started",
            "step": {"index": 1, "manifest_id": "motion_envelope_v1"},
        }
    )

    row_2012 = window._plan_row_by_key[(1, 2012)]
    assert window.campaign_queue_table.item(0, 0).text() == "In progress"
    assert window.test_plan_table.item(row_2012, 0).text() == "In progress"

    window._on_selftest_event(
        {
            "schema": "selftest_event_v1",
            "event": "selftest_result",
            "campaign_step_index": 1,
            "test_id": 2012,
            "name": "motion_xy_long_reverse_travel_factory",
            "pass": True,
        }
    )

    assert window.test_plan_table.item(row_2012, 0).text() == "Passed"

    child_report = {
        "schema_version": "qualification_report_v1",
        "results": [
            {"test_id": 2012, "name": "motion_xy_long_reverse_travel_factory", "pass": True, "metrics": {}},
            {"test_id": 2013, "name": "motion_xy_diagonal_travel_factory", "pass": True, "metrics": {}},
        ],
        "analysis": {
            "items": [
                {"item_kind": "firmware_result", "test_id": 2012, "status": "pass"},
                {"item_kind": "firmware_result", "test_id": 2013, "status": "warning"},
            ],
            "metric_evaluations": [],
        },
        "warnings": [{"test_id": 2013, "message": "candidate warning"}],
    }
    window._on_campaign_event(
        {
            "event": "campaign_step_finished",
            "step": {"index": 1, "manifest_id": "motion_envelope_v1"},
            "step_result": {"index": 1, "status": "pass", "warning_count": 1, "report_path": "motion/report.json"},
            "report": child_report,
        }
    )

    assert window.campaign_queue_table.item(0, 0).text() == "Warning"
    assert window.test_plan_table.item(window._plan_row_by_key[(1, 2013)], 0).text() == "Warning"

    window.close()


def test_run_tab_updates_elapsed_and_remaining_time_during_run(tmp_path, qapp):
    _write_sample_report(tmp_path)
    clock = [100.0]
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path), monotonic_fn=lambda: clock[0])
    window.suite_list.setCurrentRow(_suite_row(window, "factory_acceptance_v3"))
    qapp.processEvents()

    window._set_all_plan_status("Queued")
    window._begin_run_timing()
    window._mark_next_queued_in_progress()
    clock[0] = 103.2
    window._update_timing_display()

    assert window.elapsed_time_label.text() == "Elapsed: 00:03"
    assert window.test_plan_table.item(0, 6).text() == "00:03"
    assert "Expected remaining:" in window.remaining_time_label.text()

    first_id = int(window.test_plan_table.item(0, 2).text())
    window._on_selftest_event(
        {
            "schema": "selftest_event_v1",
            "event": "selftest_result",
            "test_id": first_id,
            "name": "first",
            "pass": True,
        }
    )

    assert window.test_plan_table.item(0, 6).text() == "00:03"
    assert window.test_plan_table.item(1, 0).text() == "In progress"

    window.close()


def test_selftest_progress_event_updates_status_label(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))

    window._on_selftest_event({"event": "selftest_progress", "stage": "sweep_combo"})

    assert window.run_status_label.text() == "sweep_combo"
    assert "Progress: sweep_combo" in window.run_log.toPlainText()

    window.close()


def test_gripper_suite_requires_explicit_fixture_selection(tmp_path, qapp):
    _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    window.suite_list.setCurrentRow(_suite_row(window, "gripper_seal_v1"))
    qapp.processEvents()

    assert window.start_button.isEnabled() is False

    window.fixture_combo.setCurrentText("dummy_blocked_head_v1")
    qapp.processEvents()

    assert window.start_button.isEnabled() is True

    window.close()


def test_finished_run_colors_plan_rows_and_selects_new_report(tmp_path, qapp):
    report_path = _write_sample_report(tmp_path)
    main_window = QtWidgets.QWidget()
    main_window.popup_message = lambda *_args: None
    window = MachineQualificationWindow(main_window, _ReportController(tmp_path))
    window.suite_list.setCurrentRow(_suite_row(window, "factory_acceptance_v3"))
    qapp.processEvents()

    window._on_qualification_finished(
        True,
        "done",
        {"report": _sample_report(report_path.parent), "report_path": str(report_path)},
    )

    row = _plan_row_for_test(window, 2007)
    status_item = window.test_plan_table.item(row, 0)

    assert status_item.text() == "Passed"
    assert status_item.background().color().name() == "#1f4f32"
    assert window.report_list.currentItem().text() == "2026-05-15 00:00:00"
    assert str(report_path) in window.report_list.currentItem().toolTip()
    assert "LC-TEST" in window.report_list.currentItem().toolTip()

    window.close()


class _MachineModel(QtCore.QObject):
    speeds_changed = QtCore.Signal(object)
    accelerations_changed = QtCore.Signal(object)

    def get_current_speeds(self):
        return (1000, 1000, 1000)

    def get_current_accelerations(self):
        return (1000, 1000, 1000)


class _Machine(QtCore.QObject):
    log_stats_updated = QtCore.Signal(object)
    log_message_received = QtCore.Signal(str)


class _Controller(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.machine = _Machine()
        self.set_axis_maxspeed_calls = []
        self.set_axis_accel_calls = []

    def set_axis_maxspeed(self, axis, value):
        self.set_axis_maxspeed_calls.append((axis, value))

    def set_axis_accel(self, axis, value):
        self.set_axis_accel_calls.append((axis, value))


def test_firmware_tab_exposes_machine_qualification_button(qapp):
    main_window = QtWidgets.QWidget()
    main_window.color_dict = {"darker_gray": "#222222"}
    main_window.popup_message = lambda *_args: None
    main_window.popup_yes_no = lambda *_args: QtWidgets.QMessageBox.No
    main_window._is_yes_response = lambda _response: False
    model = SimpleNamespace(machine_model=_MachineModel())
    controller = _Controller()

    tab = View.SpeedProfilesTab(main_window, model, controller, {"darker_gray": "#222222"})
    button = tab.findChild(QtWidgets.QPushButton, "machineQualificationButton")

    assert button is not None
    assert button.text() == "Machine Qualification..."

    tab.close()
