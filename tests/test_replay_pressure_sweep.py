from types import SimpleNamespace

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationProcessRecorder
from tools.replay_calibration_run import replay_run


def _dummy_model(tmp_path):
    exp = SimpleNamespace(
        experiment_dir_path=str(tmp_path),
        calibration_file_path=str(tmp_path / "calibration.json"),
    )
    return SimpleNamespace(experiment_model=exp)


def test_replay_pressure_sweep_summarizes_invalid_reasons_and_decisions(tmp_path):
    rec = CalibrationProcessRecorder(_dummy_model(tmp_path))
    run_dir = rec.start_run("PressureSweepCharacterizationProcess", "pressure_sweep_characterization")

    rec.append_event("decision", {"decision": "center_recenter_move"})
    rec.append_event("capture_saved", {"capture_role": "background"})
    rec.append_event("capture_saved", {"capture_role": "droplet"})
    rec.append_event("background_refreshed", {"status": "ok"})

    rec.append_analysis(
        {
            "kind": "calibration_data_updated",
            "payload": {
                "result": {
                    "pressures": [
                        {
                            "pressure": 0.901,
                            "delay_us": 13150,
                            "valid": False,
                            "invalid_reason": "recentre_limit_centerfirst",
                            "accepted_replicates": 0,
                            "captured_replicates": 0,
                        }
                    ]
                }
            },
        }
    )
    rec.append_analysis(
        {
            "kind": "calibration_data_updated",
            "payload": {
                "result": {
                    "pressures": [
                        {
                            "pressure": 0.880,
                            "delay_us": 13750,
                            "valid": True,
                            "accepted_replicates": 20,
                            "captured_replicates": 20,
                        }
                    ]
                }
            },
        }
    )
    rec.finalize_run("completed")

    report = replay_run(run_dir)
    assert report["supported"] is True
    assert report["mode"] == "pressure_sweep_summary"
    assert report["summary"]["total"] == 2
    assert report["summary"]["valid_pressures"] == 1
    assert report["summary"]["invalid_pressures"] == 1
    assert report["invalid_reason_counts"]["recentre_limit_centerfirst"] == 1
    assert report["decision_counts"]["center_recenter_move"] == 1
    assert report["summary"]["background_captures"] == 1
    assert report["summary"]["droplet_captures"] == 1
