from types import SimpleNamespace

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager


def _manager_stub():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._run_idx = 0
    mgr._run_id = "run-1"
    mgr.data = {"runs": [{"steps": {"trajectory": [], "online_stream_calibration": []}}]}
    mgr.model = SimpleNamespace(
        experiment_model=SimpleNamespace(get_calibration_file_path=lambda: "unused")
    )
    mgr.characterizationSummaryUpdated = Recorder()
    mgr._save_atomic = lambda: None
    mgr.get_current_settings = lambda: {}
    mgr._safe_get_stock_solution = lambda: "stock-a"
    mgr._safe_get_printer_head_id = lambda: "head-a"
    return mgr


def test_latest_step_list_reads_legacy_trajectory_key_when_canonical_missing():
    mgr = _manager_stub()
    mgr.data["runs"][0]["steps"] = {
        "trajectory": [],
        "trajectory_calibration": [{"result": {"legacy": True}}],
    }

    legacy_lookup = CalibrationManager._latest_step_list(mgr, "trajectory_calibration")
    canonical_lookup = CalibrationManager._latest_step_list(mgr, "trajectory")

    assert legacy_lookup and legacy_lookup[0]["result"]["legacy"] is True
    assert canonical_lookup and canonical_lookup[0]["result"]["legacy"] is True


def test_data_update_stores_trajectory_under_canonical_phase_key():
    mgr = _manager_stub()
    mgr.activeCalibration = SimpleNamespace(phase_name="trajectory_calibration")

    CalibrationManager.onCalibrationDataUpdated(
        mgr,
        {"measurements": [], "result": {"ok": 1}},
    )

    steps = mgr.data["runs"][0]["steps"]
    assert len(steps["trajectory"]) == 1
    assert steps["trajectory"][0]["phase"] == "trajectory"
    assert steps.get("trajectory_calibration", []) == []


def test_data_update_stores_online_stream_under_canonical_phase_key():
    mgr = _manager_stub()
    mgr.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")

    CalibrationManager.onCalibrationDataUpdated(
        mgr,
        {"measurements": [], "result": {"ok": 1}},
    )

    steps = mgr.data["runs"][0]["steps"]
    assert len(steps["online_stream_calibration"]) == 1
    assert steps["online_stream_calibration"][0]["phase"] == "online_stream_calibration"
    assert len(mgr.characterizationSummaryUpdated.calls) == 1


def test_data_update_stores_recheck_under_canonical_phase_key_and_refreshes_summary():
    mgr = _manager_stub()
    mgr.activeCalibration = SimpleNamespace(phase_name="droplet_recheck_characterization")

    CalibrationManager.onCalibrationDataUpdated(
        mgr,
        {"measurements": [], "result": {"pressures": [{"pressure": 1.2}]}},
    )

    steps = mgr.data["runs"][0]["steps"]
    assert len(steps["droplet_recheck"]) == 1
    assert steps["droplet_recheck"][0]["phase"] == "droplet_recheck"
    assert len(mgr.characterizationSummaryUpdated.calls) == 1
