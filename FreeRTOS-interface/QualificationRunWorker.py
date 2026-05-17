from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore


class QualificationRunWorker(QtCore.QThread):
    stage = QtCore.Signal(str)
    output = QtCore.Signal(str)
    prompt = QtCore.Signal(str)
    selftest_event = QtCore.Signal(object)
    campaign_event = QtCore.Signal(object)
    run_finished = QtCore.Signal(bool, str, object)

    SELFTEST_EVENT_PREFIX = "SELFTEST_EVENT "

    def __init__(
        self,
        config: dict[str, Any],
        *,
        repo_root: str | Path,
        invoker: Callable[[Any], int] | None = None,
        prompter: Callable[[str], None] | None = None,
        gripper_control: Callable[[str, str, int], int] | None = None,
        qualification_runner: Callable[..., Any] | None = None,
        campaign_runner: Callable[..., Any] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.config = dict(config)
        self.repo_root = Path(repo_root)
        self._external_invoker = invoker
        self._external_prompter = prompter
        self._external_gripper_control = gripper_control
        self._external_qualification_runner = qualification_runner
        self._external_campaign_runner = campaign_runner
        self._prompt_event: threading.Event | None = None
        self._prompt_accepted = False
        self._active_campaign_step_index: int | None = None
        self._active_campaign_manifest_id: str | None = None

    def resolve_prompt(self, accepted: bool):
        self._prompt_accepted = bool(accepted)
        event = self._prompt_event
        if event is not None:
            event.set()

    def run(self):
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))

        try:
            if str(self.config.get("run_kind") or "suite").lower() == "campaign":
                self._run_campaign()
            else:
                self._run_suite()
        except Exception as exc:
            self.stage.emit("Failed")
            self.run_finished.emit(False, f"Qualification run failed: {exc}", {})

    def _run_suite(self):
        from tools.qualification.runner import default_gripper_control, run_qualification

        self.stage.emit("Preparing qualification run")
        suite_runner = self._external_qualification_runner or run_qualification
        result = suite_runner(
            manifest_ref=self.config["manifest_ref"],
            port=str(self.config.get("port") or "/dev/ttyAMA0"),
            baud=int(self.config.get("baud") or 115200),
            machine_id=self._optional_text(self.config.get("machine_id")),
            identity_path=self.config.get("identity_path") or self.repo_root / "local" / "machine_identity.json",
            output_root=self.config.get("output_root") or self.repo_root / "hil_reports" / "qualification",
            timeout_ms=self._optional_int(self.config.get("timeout_ms")),
            run_selftest_path=self.config.get("run_selftest_path") or self.repo_root / "tools" / "run_selftest.py",
            fixture_id=self._optional_text(self.config.get("fixture_id")),
            operator_prompts=bool(self.config.get("operator_prompts")),
            progress_jsonl=True,
            invoker=self._run_selftest_invoker,
            prompter=self._external_prompter or self._prompt_operator,
            gripper_control=self._external_gripper_control or default_gripper_control,
        )
        ok = int(result.returncode) == 0
        self.stage.emit("Finished" if ok else "Failed")
        payload = {
            "run_kind": "suite",
            "returncode": int(result.returncode),
            "run_dir": str(result.run_dir),
            "raw_selftest_path": str(result.raw_selftest_path),
            "report_path": str(result.report_path),
            "summary_csv_path": str(result.summary_csv_path),
            "report": result.report,
        }
        message = f"Qualification {'passed' if ok else 'failed'}: {result.report_path}"
        self.run_finished.emit(ok, message, payload)

    def _run_campaign(self):
        from tools.qualification.campaign import run_campaign
        from tools.qualification.runner import default_gripper_control, run_qualification

        self.stage.emit("Preparing qualification campaign")

        def child_runner(**kwargs):
            result = run_qualification(**kwargs)
            return result

        campaign_runner = self._external_campaign_runner or run_campaign

        result = campaign_runner(
            campaign_ref=self.config["campaign_ref"],
            port=str(self.config.get("port") or "/dev/ttyAMA0"),
            baud=int(self.config.get("baud") or 115200),
            machine_id=self._optional_text(self.config.get("machine_id")),
            identity_path=self.config.get("identity_path") or self.repo_root / "local" / "machine_identity.json",
            campaign_output_root=self.config.get("campaign_output_root") or self.repo_root / "hil_reports" / "qualification_campaigns",
            suite_output_root=self.config.get("suite_output_root") or self.repo_root / "hil_reports" / "qualification",
            operator_prompts=bool(self.config.get("operator_prompts")),
            progress_jsonl=True,
            continue_on_failure=bool(self.config.get("continue_on_failure")),
            run_selftest_path=self.config.get("run_selftest_path") or self.repo_root / "tools" / "run_selftest.py",
            invoker=self._run_selftest_invoker,
            prompter=self._external_prompter or self._prompt_operator,
            gripper_control=self._external_gripper_control or default_gripper_control,
            qualification_runner=self._external_qualification_runner or child_runner,
            event_callback=self._handle_campaign_event,
        )
        ok = int(result.returncode) == 0
        self.stage.emit("Finished" if ok else "Failed")
        steps = list(result.report.get("steps") or [])
        completed = [step for step in steps if step.get("report_path")]
        last_report_path = completed[-1].get("report_path") if completed else None
        payload = {
            "run_kind": "campaign",
            "returncode": int(result.returncode),
            "campaign_dir": str(result.campaign_dir),
            "campaign_report_path": str(result.report_path),
            "campaign_summary_csv_path": str(result.summary_csv_path),
            "report_path": last_report_path,
            "report": result.report,
        }
        message = f"Qualification campaign {'passed' if ok else 'failed'}: {result.report_path}"
        self.run_finished.emit(ok, message, payload)

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    def _run_selftest_invoker(self, invocation) -> int:
        if self._external_invoker is not None:
            self.stage.emit("Running self-test")
            rc = int(self._external_invoker(invocation))
            self.output.emit(f"Self-test invoker returned {rc}")
            self.stage.emit("Writing report")
            return rc

        command = [str(item) for item in invocation.command]
        self.stage.emit("Running self-test")
        self.output.emit(" ".join(command))
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self.output.emit(f"Failed to launch self-test runner: {exc}")
            self.stage.emit("Writing report")
            return 3

        if proc.stdout is not None:
            for line in proc.stdout:
                self._handle_selftest_output_line(line.rstrip())
        rc = int(proc.wait())
        self.output.emit(f"Self-test runner exited with {rc}")
        self.stage.emit("Writing report")
        return rc

    def _handle_selftest_output_line(self, line: str) -> None:
        text = str(line)
        if not text.startswith(self.SELFTEST_EVENT_PREFIX):
            self.output.emit(text)
            return
        raw = text[len(self.SELFTEST_EVENT_PREFIX) :]
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            self.output.emit(text)
            return
        if not isinstance(event, dict):
            self.output.emit(text)
            return
        if self._active_campaign_step_index is not None:
            event.setdefault("campaign_step_index", self._active_campaign_step_index)
        if self._active_campaign_manifest_id:
            event.setdefault("manifest_id", self._active_campaign_manifest_id)
        self.selftest_event.emit(event)

    def _handle_campaign_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event") or "")
        if event_type == "campaign_step_started":
            step = event.get("step") if isinstance(event.get("step"), dict) else {}
            self._active_campaign_step_index = self._optional_int(step.get("index"))
            self._active_campaign_manifest_id = self._optional_text(step.get("manifest_id"))
            label = self._active_campaign_manifest_id or "suite"
            self.stage.emit(f"Running campaign step {self._active_campaign_step_index}: {label}")
        elif event_type == "campaign_step_finished":
            self._active_campaign_step_index = None
            self._active_campaign_manifest_id = None
        elif event_type == "campaign_finished":
            self._active_campaign_step_index = None
            self._active_campaign_manifest_id = None
        self.campaign_event.emit(dict(event))

    def _prompt_operator(self, message: str) -> None:
        self.stage.emit("Operator prompt")
        self._prompt_accepted = False
        self._prompt_event = threading.Event()
        self.prompt.emit(str(message))
        self._prompt_event.wait()
        self._prompt_event = None
        if not self._prompt_accepted:
            raise RuntimeError("Operator prompt cancelled.")
