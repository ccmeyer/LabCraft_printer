from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .artifacts import RunArtifacts, create_run_artifacts
from .identity import DEFAULT_IDENTITY_PATH, load_or_create_identity
from .manifest import QualificationManifest, load_manifest
from .report import write_json_atomic, write_qualification_artifacts
from .valve_trace_artifacts import generate_valve_trace_artifacts

DEFAULT_MANIFEST_REF = "factory_acceptance_v3"


@dataclass(frozen=True)
class SelfTestInvocation:
    command: tuple[str, ...]
    raw_report_path: Path
    manifest: QualificationManifest
    identity: dict
    artifacts: RunArtifacts


@dataclass(frozen=True)
class QualificationRunResult:
    returncode: int
    run_dir: Path
    raw_selftest_path: Path
    report_path: Path
    summary_csv_path: Path
    report: dict


SelfTestInvoker = Callable[[SelfTestInvocation], int]
OperatorPrompter = Callable[[str], None]
GripperControl = Callable[[str, str, int], int]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_selftest_invoker(invocation: SelfTestInvocation) -> int:
    completed = subprocess.run(list(invocation.command), check=False)
    return int(completed.returncode)


def default_operator_prompter(message: str) -> None:
    input(f"{message}\nPress Enter to continue...")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_prompt(interactions: list[dict], stage: str, message: str, prompter: OperatorPrompter) -> None:
    prompter(message)
    interactions.append({"stage": stage, "message": message, "confirmed_at": _now_iso()})


def _fixture_ids(manifest: QualificationManifest) -> set[str]:
    return {
        str(item.get("fixture_id") or "").strip()
        for item in manifest.fixtures
        if str(item.get("fixture_id") or "").strip()
    }


def _fixture_prompt_message(manifest: QualificationManifest, fixture_id: str | None) -> str:
    notes: list[str] = []
    for item in manifest.fixtures:
        item_fixture_id = str(item.get("fixture_id") or "").strip()
        operator_note = str(item.get("operator_note") or "").strip()
        if operator_note and (fixture_id is None or item_fixture_id == fixture_id):
            notes.append(operator_note)
    note_text = "\n".join(notes) if notes else "Confirm the required fixture and machine state are ready."
    return (
        f"Confirm qualification setup before running {manifest.name} ({manifest.manifest_id}).\n\n"
        f"Profile: {manifest.profile}\n"
        f"Fixture: {fixture_id or 'none'}\n\n"
        f"{note_text}\n\n"
        "Confirm the operator is present and the hardware envelope is clear."
    )


def default_gripper_control(action: str, port: str, baud: int) -> int:
    try:
        run_selftest = importlib.import_module("tools.run_selftest")
    except ModuleNotFoundError:
        run_selftest = importlib.import_module("run_selftest")
    serial_mod = getattr(run_selftest, "serial", None)
    if serial_mod is None:
        print("Missing dependency: pyserial (import serial failed).")
        return 3

    def read_matching_frame(ser, reader, deadline: float, predicate):
        while time.monotonic() < deadline:
            chunk = ser.read(128)
            for byte in chunk:
                frame = reader.feed(byte)
                if frame and predicate(frame):
                    return frame
        return None

    def send_hello(ser, reader, run_id: int) -> bool:
        hello_seq8 = 0x40
        ser.write(run_selftest.build_control(run_selftest.CMD_HELLO, hello_seq8, run_id))
        deadline = time.monotonic() + 1.5
        return read_matching_frame(
            ser,
            reader,
            deadline,
            lambda frame: len(frame) >= 2 and frame[0] == run_selftest.CMD_HELLO_ACK and frame[1] == hello_seq8,
        ) is not None

    def send_queue_command(ser, reader, command: int, seq8: int, seq32: int) -> bool:
        ser.write(run_selftest.build_control(command, seq8, seq32))
        deadline = time.monotonic() + 3.0

        def accepted(frame) -> bool:
            if len(frame) < 2 or frame[0] != run_selftest.CMD_QUEUE_ACK or frame[1] != seq8:
                return False
            tlv = run_selftest.parse_tlvs(frame[2:])
            ack_seq32 = run_selftest._tlv_u32(tlv, run_selftest.TAG_SEQ32)
            if ack_seq32 is not None and ack_seq32 != seq32:
                return False
            ack_result = run_selftest._tlv_u8(tlv, run_selftest.TAG_ACK_RESULT)
            return ack_result in (run_selftest.ACK_RESULT_ACCEPTED, run_selftest.ACK_RESULT_DUPLICATE)

        return read_matching_frame(ser, reader, deadline, accepted) is not None

    def send_goodbye(ser, reader, run_id: int, seq32: int) -> bool:
        goodbye_seq8 = 0x43
        ser.write(run_selftest.build_control(run_selftest.CMD_GOODBYE, goodbye_seq8, seq32))
        ack_deadline = time.monotonic() + 2.0
        got_ack = read_matching_frame(
            ser,
            reader,
            ack_deadline,
            lambda frame: len(frame) >= 2 and frame[0] == run_selftest.CMD_BYE_ACK and frame[1] == goodbye_seq8,
        ) is not None
        if not got_ack:
            return False

        done_deadline = time.monotonic() + 5.0

        def goodbye_done(frame) -> bool:
            if len(frame) < 2 or frame[0] != run_selftest.CMD_BYE_DONE or frame[1] != goodbye_seq8:
                return False
            tlv = run_selftest.parse_tlvs(frame[2:])
            observed_seq32 = run_selftest._tlv_u32(tlv, run_selftest.TAG_SEQ32)
            return observed_seq32 is None or observed_seq32 == seq32

        return read_matching_frame(ser, reader, done_deadline, goodbye_done) is not None

    command_by_action = {
        "preflight_print": 0x20,   # CMD_PRINT
        "preflight_refuel": 0x21,  # CMD_REFUEL
        "release": 0x10,  # CMD_GRIPPER_OPEN
        "off": 0x12,      # CMD_GRIPPER_OFF
    }
    seq8_by_action = {
        "preflight_print": 0x31,
        "preflight_refuel": 0x32,
        "release": 0x41,
        "off": 0x42,
    }
    settle_s_by_action = {
        "preflight_print": 0.1,
        "preflight_refuel": 0.1,
        "release": 2.0,
        "off": 0.2,
    }

    run_id = int(time.time() * 1000) & 0xFFFFFFFF
    reader = run_selftest.FrameReader()
    with serial_mod.Serial(port, int(baud), timeout=0.1) as ser:
        if not send_hello(ser, reader, run_id):
            return 3
        if action == "shutdown":
            return 0 if send_goodbye(ser, reader, run_id, 1) else 3
        command = command_by_action.get(action)
        if command is None:
            return 3
        if not send_queue_command(ser, reader, command, seq8_by_action[action], 1):
            return 3
        time.sleep(settle_s_by_action[action])
        return 0


def _build_selftest_command(
    *,
    run_selftest_path: str | Path | None,
    port: str,
    baud: int,
    profile: str,
    raw_report_path: Path,
    timeout_ms: int | None,
    progress_jsonl: bool = False,
    extra_args: tuple[str, ...] = (),
) -> tuple[str, ...]:
    script = Path(run_selftest_path) if run_selftest_path is not None else _repo_root() / "tools" / "run_selftest.py"
    command = [
        sys.executable,
        str(script),
        "--port",
        str(port),
        "--baud",
        str(int(baud)),
        "--profile",
        str(profile).upper(),
        "--out",
        str(raw_report_path),
    ]
    if timeout_ms is not None:
        command.extend(["--timeout-ms", str(int(timeout_ms))])
    if progress_jsonl:
        command.append("--progress-jsonl")
    command.extend(str(item) for item in extra_args)
    return tuple(command)


def _raw_missing_report(manifest: QualificationManifest, returncode: int) -> dict:
    return {
        "run_id": None,
        "profile": manifest.profile,
        "started_at": None,
        "finished_at": None,
        "aborted": True,
        "summary": {"total": 0, "passed": 0, "failed": 0},
        "results": [],
        "host_checks": [
            {
                "name": "selftest_invoker",
                "pass": False,
                "details": {
                    "returncode": int(returncode),
                    "error": "self-test runner did not produce raw_selftest.json",
                },
            }
        ],
    }


def _maybe_generate_valve_trace_artifacts(manifest: QualificationManifest, artifacts: RunArtifacts) -> None:
    if manifest.manifest_id not in {"valve_characterization_v1", "valve_gap_sweep_v1"}:
        return
    try:
        generate_valve_trace_artifacts(artifacts)
    except Exception as exc:
        error_dir = artifacts.plots_dir / "valve_characterization"
        error_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            error_dir / "valve_trace_artifact_error.json",
            {
                "schema_version": "valve_trace_artifact_error_v1",
                "error": str(exc),
            },
        )


def run_qualification(
    *,
    manifest_ref: str | Path = DEFAULT_MANIFEST_REF,
    port: str = "/dev/ttyAMA0",
    baud: int = 115200,
    machine_id: str | None = None,
    identity_path: str | Path = DEFAULT_IDENTITY_PATH,
    output_root: str | Path = Path("hil_reports") / "qualification",
    timeout_ms: int | None = None,
    run_selftest_path: str | Path | None = None,
    raw_report_path: str | Path | None = None,
    fixture_id: str | None = None,
    operator_prompts: bool = False,
    progress_jsonl: bool = False,
    invoker: SelfTestInvoker = default_selftest_invoker,
    prompter: OperatorPrompter = default_operator_prompter,
    gripper_control: GripperControl = default_gripper_control,
) -> QualificationRunResult:
    manifest = load_manifest(manifest_ref)
    identity = load_or_create_identity(identity_path, machine_id=machine_id)
    artifacts = create_run_artifacts(identity["machine_id"], output_root=output_root)
    interactions: list[dict] = []
    preflight_host_checks: list[dict] = []
    fixture_id = str(fixture_id or "").strip() or None
    gripper_seal_manifest = manifest.manifest_id == "gripper_seal_v1"

    if raw_report_path is not None:
        source_path = Path(raw_report_path)
        raw_selftest = json.loads(source_path.read_text(encoding="utf-8"))
        report = write_qualification_artifacts(
            raw_selftest,
            manifest,
            identity,
            artifacts,
            raw_source_path=source_path,
            selftest_returncode=0,
            fixture_id=fixture_id,
            operator_interactions=interactions,
        )
        _maybe_generate_valve_trace_artifacts(manifest, artifacts)
        qualification_returncode = 0 if report.get("overall_status") == "pass" else 3
        return QualificationRunResult(
            returncode=qualification_returncode,
            run_dir=artifacts.run_dir,
            raw_selftest_path=artifacts.raw_selftest_path,
            report_path=artifacts.report_path,
            summary_csv_path=artifacts.summary_csv_path,
            report=report,
        )

    required_fixture_ids = _fixture_ids(manifest)
    if manifest.requires_operator_prompts:
        rejection: dict | None = None
        if not operator_prompts:
            rejection = {
                "name": "operator_prompts_required",
                "pass": False,
                "details": {"manifest_id": manifest.manifest_id},
            }
        elif required_fixture_ids and fixture_id not in required_fixture_ids:
            rejection = {
                "name": "fixture_required",
                "pass": False,
                "details": {
                    "manifest_id": manifest.manifest_id,
                    "provided_fixture_id": fixture_id,
                    "allowed_fixture_ids": sorted(required_fixture_ids),
                },
            }
        if rejection is not None:
            raw_selftest = _raw_missing_report(manifest, 3)
            raw_selftest["host_checks"] = [rejection]
            write_json_atomic(artifacts.raw_selftest_path, raw_selftest)
            report = write_qualification_artifacts(
                raw_selftest,
                manifest,
                identity,
                artifacts,
                raw_source_path=artifacts.raw_selftest_path,
                selftest_returncode=3,
                fixture_id=fixture_id,
                operator_interactions=interactions,
            )
            return QualificationRunResult(
                returncode=3,
                run_dir=artifacts.run_dir,
                raw_selftest_path=artifacts.raw_selftest_path,
                report_path=artifacts.report_path,
                summary_csv_path=artifacts.summary_csv_path,
                report=report,
            )

        if not gripper_seal_manifest:
            _record_prompt(
                interactions,
                "confirm_fixture_setup",
                _fixture_prompt_message(manifest, fixture_id),
                prompter,
            )

    if manifest.requires_operator_prompts and gripper_seal_manifest:
        _record_prompt(
            interactions,
            "load_dummy_head",
            "Load the dummy blocked printer head into the gripper, support it, and confirm it is aligned.",
            prompter,
        )
        for action, check_name in (
            ("preflight_print", "gripper_valve_preflight_print"),
            ("preflight_refuel", "gripper_valve_preflight_refuel"),
        ):
            rc = int(gripper_control(action, port, int(baud)))
            preflight_host_checks.append(
                {
                    "name": check_name,
                    "pass": rc == 0,
                    "details": {"action": action, "returncode": rc},
                    "timestamp": _now_iso(),
                }
            )
        if not all(item["pass"] for item in preflight_host_checks):
            raw_selftest = _raw_missing_report(manifest, 3)
            raw_selftest["host_checks"] = preflight_host_checks
            write_json_atomic(artifacts.raw_selftest_path, raw_selftest)
            report = write_qualification_artifacts(
                raw_selftest,
                manifest,
                identity,
                artifacts,
                raw_source_path=artifacts.raw_selftest_path,
                selftest_returncode=3,
                fixture_id=fixture_id,
                operator_interactions=interactions,
            )
            return QualificationRunResult(
                returncode=3,
                run_dir=artifacts.run_dir,
                raw_selftest_path=artifacts.raw_selftest_path,
                report_path=artifacts.report_path,
                summary_csv_path=artifacts.summary_csv_path,
                report=report,
            )
        _record_prompt(
            interactions,
            "confirm_valve_clicks",
            "Confirm you heard or felt the print/refuel valve clicks.",
            prompter,
        )

    command = _build_selftest_command(
        run_selftest_path=run_selftest_path,
        port=port,
        baud=baud,
        profile=manifest.profile,
        raw_report_path=artifacts.raw_selftest_path,
        timeout_ms=timeout_ms,
        progress_jsonl=progress_jsonl,
        extra_args=manifest.selftest_args,
    )
    invocation = SelfTestInvocation(
        command=command,
        raw_report_path=artifacts.raw_selftest_path,
        manifest=manifest,
        identity=identity,
        artifacts=artifacts,
    )
    selftest_returncode = int(invoker(invocation))

    if artifacts.raw_selftest_path.exists():
        raw_selftest = json.loads(artifacts.raw_selftest_path.read_text(encoding="utf-8"))
        raw_source_path: Path | None = artifacts.raw_selftest_path
    else:
        raw_selftest = _raw_missing_report(manifest, selftest_returncode)
        write_json_atomic(artifacts.raw_selftest_path, raw_selftest)
        raw_source_path = artifacts.raw_selftest_path

    if manifest.requires_operator_prompts and gripper_seal_manifest:
        host_checks = preflight_host_checks + list(raw_selftest.get("host_checks") or [])
        _record_prompt(
            interactions,
            "support_before_release",
            "Support the dummy blocked printer head before gripper release.",
            prompter,
        )
        release_rc = int(gripper_control("release", port, int(baud)))
        if release_rc != 0:
            print("WARNING: Gripper release command failed. Keep supporting the dummy head and resolve manually.")
        host_checks.append(
            {
                "name": "gripper_teardown_release",
                "pass": release_rc == 0,
                "details": {"action": "release", "returncode": release_rc},
                "timestamp": _now_iso(),
            }
        )
        _record_prompt(
            interactions,
            "remove_dummy_head",
            "Remove the dummy blocked printer head from the gripper.",
            prompter,
        )
        off_rc = int(gripper_control("off", port, int(baud)))
        if off_rc != 0:
            print("WARNING: Gripper off/idle command failed. Verify the gripper state manually before leaving the machine.")
        host_checks.append(
            {
                "name": "gripper_teardown_off",
                "pass": off_rc == 0,
                "details": {"action": "off", "returncode": off_rc},
                "timestamp": _now_iso(),
            }
        )
        shutdown_rc = int(gripper_control("shutdown", port, int(baud)))
        if shutdown_rc != 0:
            print("WARNING: Normal shutdown command failed. Verify pressure regulators, motors, and LED state manually.")
        host_checks.append(
            {
                "name": "gripper_teardown_shutdown",
                "pass": shutdown_rc == 0,
                "details": {"action": "shutdown", "returncode": shutdown_rc},
                "timestamp": _now_iso(),
            }
        )
        raw_selftest["host_checks"] = host_checks

    report = write_qualification_artifacts(
        raw_selftest,
        manifest,
        identity,
        artifacts,
        raw_source_path=raw_source_path,
        selftest_returncode=selftest_returncode,
        fixture_id=fixture_id,
        operator_interactions=interactions,
    )
    _maybe_generate_valve_trace_artifacts(manifest, artifacts)
    qualification_returncode = 0 if report.get("overall_status") == "pass" else 3
    return QualificationRunResult(
        returncode=qualification_returncode,
        run_dir=artifacts.run_dir,
        raw_selftest_path=artifacts.raw_selftest_path,
        report_path=artifacts.report_path,
        summary_csv_path=artifacts.summary_csv_path,
        report=report,
    )
