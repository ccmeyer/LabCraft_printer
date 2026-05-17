import csv
import json
from pathlib import Path

import pytest

from tools.qualification import campaign_cli
from tools.qualification.campaign import CampaignError, load_campaign, run_campaign
from tools.qualification.runner import QualificationRunResult


def _identity_path(tmp_path: Path) -> Path:
    return tmp_path / "local" / "machine_identity.json"


def _fake_result(tmp_path: Path, manifest_ref: str, *, status: str = "pass", warnings=None, index: int = 1):
    run_dir = tmp_path / "suite_runs" / f"{index:02d}_{manifest_ref}"
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_path = run_dir / "raw_selftest.json"
    report_path = run_dir / "report.json"
    summary_path = run_dir / "summary.csv"
    report = {
        "schema_version": "qualification_report_v1",
        "manifest": {"manifest_id": manifest_ref, "name": manifest_ref, "profile": "FULL"},
        "machine": {"machine_id": "LC-TEST"},
        "run": {
            "run_dir": str(run_dir),
            "raw_selftest_path": str(raw_path),
            "report_path": str(report_path),
            "summary_csv_path": str(summary_path),
        },
        "overall_status": status,
        "warnings": list(warnings or []),
    }
    raw_path.write_text("{}", encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary_path.write_text("header\n", encoding="utf-8")
    return QualificationRunResult(
        returncode=0 if status == "pass" else 3,
        run_dir=run_dir,
        raw_selftest_path=raw_path,
        report_path=report_path,
        summary_csv_path=summary_path,
        report=report,
    )


def test_load_builtin_machine_full_campaign():
    campaign = load_campaign("machine_full_qualification_v1")

    assert campaign.campaign_id == "machine_full_qualification_v1"
    assert campaign.requires_operator_prompts is True
    assert [step.manifest_id for step in campaign.steps] == [
        "motion_envelope_v1",
        "pressure_regulator_v1",
        "valve_characterization_v1",
        "gripper_seal_stress_v1",
    ]
    assert [step.fixture_id for step in campaign.steps] == [
        "motion_full_envelope_v1",
        "pressure_closed_loop_v1",
        "valve_closed_loop_pulse_matrix_v1",
        "dummy_blocked_head_motion_v1",
    ]
    assert [step.timeout_ms for step in campaign.steps] == [420000, 420000, 420000, 900000]


def test_load_builtin_gripper_stress_campaign():
    campaign = load_campaign("gripper_seal_stress_campaign_v1")

    assert campaign.campaign_id == "gripper_seal_stress_campaign_v1"
    assert campaign.name == "Gripper Seal Stress Qualification"
    assert campaign.requires_operator_prompts is True
    assert [step.manifest_id for step in campaign.steps] == ["gripper_seal_stress_v1"]
    assert [step.fixture_id for step in campaign.steps] == ["dummy_blocked_head_motion_v1"]
    assert [step.timeout_ms for step in campaign.steps] == [900000]


def test_load_campaign_rejects_unknown_campaign():
    with pytest.raises(CampaignError, match="not found"):
        load_campaign("does_not_exist")


def test_load_campaign_rejects_unknown_child_manifest(tmp_path):
    path = tmp_path / "bad_campaign.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "qualification_campaign_v1",
                "campaign_id": "bad",
                "name": "Bad",
                "steps": [{"manifest": "not_a_manifest", "fixture": "fixture", "timeout_ms": 1}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CampaignError, match="not_a_manifest"):
        load_campaign(path)


def test_run_campaign_runs_steps_in_order_and_writes_parent_artifacts(tmp_path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return _fake_result(tmp_path, kwargs["manifest_ref"], index=len(calls))

    result = run_campaign(
        campaign_ref="machine_full_qualification_v1",
        port="COM9",
        baud=57600,
        machine_id="LC-TEST",
        identity_path=_identity_path(tmp_path),
        campaign_output_root=tmp_path / "campaigns",
        suite_output_root=tmp_path / "qualification",
        operator_prompts=True,
        progress_jsonl=True,
        qualification_runner=fake_runner,
    )

    assert result.returncode == 0
    assert result.report["overall_status"] == "pass"
    assert result.report_path.exists()
    assert result.summary_csv_path.exists()
    assert [call["manifest_ref"] for call in calls] == [
        "motion_envelope_v1",
        "pressure_regulator_v1",
        "valve_characterization_v1",
        "gripper_seal_stress_v1",
    ]
    assert [call["fixture_id"] for call in calls] == [
        "motion_full_envelope_v1",
        "pressure_closed_loop_v1",
        "valve_closed_loop_pulse_matrix_v1",
        "dummy_blocked_head_motion_v1",
    ]
    assert [call["timeout_ms"] for call in calls] == [420000, 420000, 420000, 900000]
    assert all(call["operator_prompts"] is True for call in calls)
    assert all(call["progress_jsonl"] is True for call in calls)
    assert all(call["output_root"] == tmp_path / "qualification" for call in calls)
    rows = list(csv.DictReader(result.summary_csv_path.open(newline="", encoding="utf-8")))
    assert [row["manifest_id"] for row in rows] == [step["manifest_id"] for step in result.report["steps"]]


def test_run_gripper_stress_campaign_invokes_only_gripper_suite(tmp_path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return _fake_result(tmp_path, kwargs["manifest_ref"], index=len(calls))

    result = run_campaign(
        campaign_ref="gripper_seal_stress_campaign_v1",
        machine_id="LC-TEST",
        identity_path=_identity_path(tmp_path),
        campaign_output_root=tmp_path / "campaigns",
        suite_output_root=tmp_path / "qualification",
        operator_prompts=True,
        qualification_runner=fake_runner,
    )

    assert result.returncode == 0
    assert [call["manifest_ref"] for call in calls] == ["gripper_seal_stress_v1"]
    assert [call["fixture_id"] for call in calls] == ["dummy_blocked_head_motion_v1"]
    assert [call["timeout_ms"] for call in calls] == [900000]


def test_run_campaign_requires_operator_prompts_before_launching_hardware(tmp_path):
    def fake_runner(**_kwargs):
        raise AssertionError("operator prompt prevalidation should prevent suite launch")

    result = run_campaign(
        campaign_ref="machine_full_qualification_v1",
        machine_id="LC-TEST",
        identity_path=_identity_path(tmp_path),
        campaign_output_root=tmp_path / "campaigns",
        suite_output_root=tmp_path / "qualification",
        operator_prompts=False,
        qualification_runner=fake_runner,
    )

    assert result.returncode == 3
    assert result.report["overall_status"] == "fail"
    assert [step["status"] for step in result.report["steps"]] == ["skipped", "skipped", "skipped", "skipped"]
    assert {step["message"] for step in result.report["steps"]} == {"operator_prompts_required"}


def test_run_campaign_stops_after_first_failed_suite_by_default(tmp_path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        status = "fail" if len(calls) == 2 else "pass"
        return _fake_result(tmp_path, kwargs["manifest_ref"], status=status, index=len(calls))

    result = run_campaign(
        campaign_ref="machine_full_qualification_v1",
        machine_id="LC-TEST",
        identity_path=_identity_path(tmp_path),
        campaign_output_root=tmp_path / "campaigns",
        suite_output_root=tmp_path / "qualification",
        operator_prompts=True,
        qualification_runner=fake_runner,
    )

    assert result.returncode == 3
    assert len(calls) == 2
    assert [step["status"] for step in result.report["steps"]] == ["pass", "fail", "skipped", "skipped"]


def test_run_campaign_continue_on_failure_runs_all_steps(tmp_path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        status = "fail" if len(calls) == 2 else "pass"
        return _fake_result(tmp_path, kwargs["manifest_ref"], status=status, index=len(calls))

    result = run_campaign(
        campaign_ref="machine_full_qualification_v1",
        machine_id="LC-TEST",
        identity_path=_identity_path(tmp_path),
        campaign_output_root=tmp_path / "campaigns",
        suite_output_root=tmp_path / "qualification",
        operator_prompts=True,
        continue_on_failure=True,
        qualification_runner=fake_runner,
    )

    assert result.returncode == 3
    assert len(calls) == 4
    assert [step["status"] for step in result.report["steps"]] == ["pass", "fail", "pass", "pass"]


def test_run_campaign_child_warnings_do_not_fail_campaign(tmp_path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return _fake_result(
            tmp_path,
            kwargs["manifest_ref"],
            warnings=[{"message": "candidate warning"}] if len(calls) == 1 else [],
            index=len(calls),
        )

    result = run_campaign(
        campaign_ref="machine_full_qualification_v1",
        machine_id="LC-TEST",
        identity_path=_identity_path(tmp_path),
        campaign_output_root=tmp_path / "campaigns",
        suite_output_root=tmp_path / "qualification",
        operator_prompts=True,
        qualification_runner=fake_runner,
    )

    assert result.returncode == 0
    assert result.report["overall_status"] == "pass"
    assert result.report["summary"]["warnings"] == 1
    assert result.report["warnings"][0]["manifest_id"] == "motion_envelope_v1"


def test_campaign_cli_dry_run_prints_queue_without_invocation(capsys):
    def fake_runner(**_kwargs):
        raise AssertionError("dry-run should not invoke suites")

    rc = campaign_cli.main(["--campaign", "machine_full_qualification_v1", "--dry-run"], qualification_runner=fake_runner)

    captured = capsys.readouterr()
    assert rc == 0
    assert "Full Machine Qualification" in captured.out
    assert "motion_envelope_v1" in captured.out
    assert "gripper_seal_stress_v1" in captured.out


def test_campaign_cli_dry_run_prints_gripper_only_queue(capsys):
    def fake_runner(**_kwargs):
        raise AssertionError("dry-run should not invoke suites")

    rc = campaign_cli.main(["--campaign", "gripper_seal_stress_campaign_v1", "--operator-prompts", "--dry-run"], qualification_runner=fake_runner)

    captured = capsys.readouterr()
    assert rc == 0
    assert "Gripper Seal Stress Qualification" in captured.out
    assert "gripper_seal_stress_v1" in captured.out
    assert "motion_envelope_v1" not in captured.out


def test_campaign_cli_returns_success_and_failure_codes(tmp_path):
    def passing_runner(**kwargs):
        return _fake_result(tmp_path, kwargs["manifest_ref"])

    success = campaign_cli.main(
        [
            "--campaign",
            "machine_full_qualification_v1",
            "--machine-id",
            "LC-TEST",
            "--identity-path",
            str(_identity_path(tmp_path / "pass")),
            "--campaign-output-root",
            str(tmp_path / "campaigns_pass"),
            "--suite-output-root",
            str(tmp_path / "qualification_pass"),
            "--operator-prompts",
        ],
        qualification_runner=passing_runner,
    )

    def failing_runner(**kwargs):
        return _fake_result(tmp_path, kwargs["manifest_ref"], status="fail")

    failure = campaign_cli.main(
        [
            "--campaign",
            "machine_full_qualification_v1",
            "--machine-id",
            "LC-TEST",
            "--identity-path",
            str(_identity_path(tmp_path / "fail")),
            "--campaign-output-root",
            str(tmp_path / "campaigns_fail"),
            "--suite-output-root",
            str(tmp_path / "qualification_fail"),
            "--operator-prompts",
        ],
        qualification_runner=failing_runner,
    )

    assert success == 0
    assert failure == 3
