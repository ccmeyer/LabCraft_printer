"""Small Qt page drivers shared by interactive SIL lifecycle tests."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from PySide6 import QtCore, QtTest, QtWidgets


class _QTestSurfaceDriver:
    """Shared bounded QTest mechanics with no workflow policy."""

    def __init__(self, context):
        self.context = context
        self.app = context.app
        self.view = context.view

    def wait_until(
        self,
        predicate: Callable[[], bool],
        description: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        allowed = self.context.deadline.remaining_seconds(timeout_seconds)
        deadline = time.monotonic() + allowed
        while time.monotonic() < deadline:
            self.context.pump_events()
            if predicate():
                return
            QtTest.QTest.qWait(5)
        self.context.pump_events()
        if predicate():
            return
        raise RuntimeError(f"timed out waiting for {description}")

    def click(self, widget: Any) -> None:
        if widget is None or not widget.isVisible() or not widget.isEnabled():
            raise RuntimeError("requested UI control is not visible and enabled")
        widget.setFocus()
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)
        self.context.pump_events()

    def replace_spin_value(self, widget: Any, value: int | float) -> None:
        if not widget.isVisible() or not widget.isEnabled():
            raise RuntimeError("requested spin control is not visible and enabled")
        editor = widget.lineEdit()
        self.click(editor)
        QtTest.QTest.keyClick(
            editor,
            QtCore.Qt.Key.Key_A,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QtTest.QTest.keyClicks(editor, str(value))
        QtTest.QTest.keyClick(editor, QtCore.Qt.Key.Key_Enter)
        self.context.pump_events()

    def click_with_message_boxes(
        self,
        widget: Any,
        expected: list[tuple[str, QtWidgets.QMessageBox.StandardButton]],
    ) -> list[dict[str, Any]]:
        """Click once and accept only the exact ordered QMessageBox sequence."""

        handled: list[dict[str, Any]] = []
        state: dict[str, Any] = {"error": None}
        deadline = time.monotonic() + self.context.deadline.remaining_seconds(10.0)

        def inspect() -> None:
            if state["error"] is not None or len(handled) >= len(expected):
                return
            active = self.app.activeModalWidget()
            if active is None:
                if time.monotonic() >= deadline:
                    state["error"] = RuntimeError(
                        "expected dialog sequence did not complete"
                    )
                    return
                QtCore.QTimer.singleShot(5, inspect)
                return
            if not isinstance(active, QtWidgets.QMessageBox):
                state["error"] = RuntimeError(
                    "unexpected modal while handling action: "
                    f"{type(active).__name__} {active.windowTitle()!r}"
                )
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                return
            expected_title, standard_button = expected[len(handled)]
            if active.windowTitle() != expected_title:
                state["error"] = RuntimeError(
                    f"unexpected dialog title {active.windowTitle()!r}; "
                    f"expected {expected_title!r}"
                )
                active.reject()
                return
            button = active.button(standard_button)
            if button is None:
                state["error"] = RuntimeError(
                    f"expected dialog button is missing from {expected_title!r}"
                )
                active.reject()
                return
            entry = {"title": active.windowTitle(), "text": active.text()}
            handled.append(entry)
            self.context.dialogs.append(entry)
            self.context.record_event("dialog", **entry)
            QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
            if len(handled) < len(expected):
                QtCore.QTimer.singleShot(0, inspect)

        QtCore.QTimer.singleShot(0, inspect)
        self.click(widget)
        self.context.pump_events()
        if state["error"] is not None:
            raise state["error"]
        if len(handled) != len(expected):
            raise RuntimeError(
                f"handled {len(handled)} dialogs; expected {len(expected)}"
            )
        return handled


class MainWindowDriver(_QTestSurfaceDriver):
    """Read and focus the normal application window."""

    def inspect_simulation_identity(self) -> dict[str, Any]:
        banner = getattr(self.view, "simulation_identity_banner", None)
        label = getattr(self.view, "simulation_identity_label", None)
        return {
            "window_visible": bool(self.view.isVisible()),
            "banner_visible": bool(banner is not None and banner.isVisible()),
            "banner_text": label.text() if label is not None else None,
        }


class MachineControlsDriver(_QTestSurfaceDriver):
    """QTest mechanics for normal connection, motor, and pressure controls."""

    def connect(self) -> None:
        button = self.view.connection_widget.machine_connect_button
        if button.text() != "Connect":
            raise RuntimeError(f"expected Connect control; observed {button.text()!r}")
        self.click(button)
        self.wait_until(
            lambda: self.context.model.machine_model.is_connected(),
            "simulator connection",
        )

    def enable_motors(self) -> None:
        button = self.view.coordinates_box.toggle_motor_button
        if button.text() != "Enable Motors":
            raise RuntimeError(
                f"expected Enable Motors control; observed {button.text()!r}"
            )
        self.click(button)
        self.wait_until(
            self.context.model.machine_model.motors_are_enabled,
            "motor enable",
        )

    def home_motors(self) -> None:
        self.click(self.view.coordinates_box.home_button)
        self.wait_until(
            self.context.model.machine_model.motors_are_homed,
            "motor home",
        )
        self.wait_until(
            self.context.machine.check_if_all_completed,
            "home command queue",
        )

    def configure_print_settings(
        self,
        *,
        pulse_width_us: int,
        pressure_psi: float,
        frequency_hz: int,
    ) -> None:
        box = self.view.pressure_box
        self.replace_spin_value(box.print_pulse_width_spinbox, pulse_width_us)
        self.replace_spin_value(box.target_print_pressure_spinbox, pressure_psi)
        self.replace_spin_value(box.print_frequency_spinbox, frequency_hz)
        self.wait_until(
            self.context.machine.check_if_all_completed,
            "print settings command queue",
        )

    def enable_pressure_regulation(self) -> None:
        button = self.view.pressure_box.pressure_regulation_button
        self.click(button)
        self.wait_until(
            lambda: bool(
                self.context.model.machine_model.regulating_print_pressure
            ),
            "print-pressure regulation",
        )

    def open_calibration_dialog(self) -> Any:
        button = self.view.pressure_box.calibrate_pressure_button
        self.click(button)
        self.wait_until(
            lambda: getattr(
                self.view.pressure_box, "_droplet_imager_dialog", None
            )
            is not None,
            "normal calibration dialog",
        )
        dialog = self.view.pressure_box._droplet_imager_dialog
        if not dialog.isVisible():
            raise RuntimeError("normal calibration dialog is not visible")
        return dialog


class ExperimentEditorDriver(_QTestSurfaceDriver):
    """QTest mechanics for the normal Experiment Editor surface."""

    def __init__(self, context, *, action_runner=None):
        super().__init__(context)
        self.action_runner = action_runner

    def create_and_finalize(
        self,
        specification: dict[str, Any],
        *,
        capture_editor_milestones: bool = True,
    ) -> dict[str, Any]:
        # The bounded editor mechanics remain the compatibility implementation
        # while the shared harness owns composed-journey action boundaries.
        from tools.virtual_workflows.actions import drive_editor_create_finalize

        return drive_editor_create_finalize(
            self.context,
            specification,
            action_runner=self.action_runner,
            capture_editor_milestones=capture_editor_milestones,
        )

    def revise_prepared_design(
        self,
        *,
        initial_name: str,
        renamed_name: str,
        experiment: Mapping[str, Any],
        reagent: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Rename, edit, regenerate, and refinalize one prepared design."""

        from tools.virtual_workflows.actions import (
            drive_editor_prestart_rename_refinalize,
        )

        return drive_editor_prestart_rename_refinalize(
            self.context,
            initial_name=initial_name,
            renamed_name=renamed_name,
            experiment=experiment,
            reagent=reagent,
            action_runner=self.action_runner,
        )


class ExperimentLoaderDriver(_QTestSurfaceDriver):
    """QTest mechanics for reopening contained authoritative experiments."""

    def _drive_directory_load(
        self,
        experiment_dir,
        *,
        purpose: str,
        on_loaded: Callable[[Any], Mapping[str, Any]],
        on_activated: Callable[[Any], Mapping[str, Any]] | None = None,
        on_failure: Callable[[BaseException, Any], None] | None = None,
    ) -> dict[str, Any]:
        """Drive the editor and nested directory chooser, then run callbacks."""

        from pathlib import Path
        from View import ExperimentDesignDialog

        directory = Path(experiment_dir).resolve()
        if not directory.is_relative_to(Path(self.context.scenario_root).resolve()):
            root_label = "SIL session root" if purpose == "prepared" else "SIL root"
            raise RuntimeError(f"{purpose} experiment escaped the {root_label}")
        button = self.view.well_plate_widget.design_experiment_button
        if not button.isVisible() or not button.isEnabled():
            raise RuntimeError("Experiment Editor control is not visible and enabled")
        state: dict[str, Any] = {"error": None, "loaded": None, "activated": None}

        def fail(exc: BaseException, modal=None) -> None:
            state["error"] = exc
            if on_failure is not None:
                on_failure(exc, modal)
            for widget in (modal, self.app.activeModalWidget()):
                if isinstance(widget, QtWidgets.QDialog) and widget.isVisible():
                    widget.reject()

        def choose_directory(editor) -> None:
            modal = self.app.activeModalWidget()
            try:
                if not isinstance(modal, QtWidgets.QFileDialog):
                    raise RuntimeError(
                        f"unexpected modal while selecting {purpose} folder: "
                        f"{type(modal).__name__} {modal.windowTitle()!r}"
                    )
                if modal.windowTitle() != "Select Experiment Folder":
                    raise RuntimeError(
                        f"unexpected file dialog title: {modal.windowTitle()!r}"
                    )
                modal.setDirectory(str(directory))
                self.context.pump_events()
                box = modal.findChild(QtWidgets.QDialogButtonBox)
                accept = box.button(QtWidgets.QDialogButtonBox.Open) if box else None
                if accept is None and box is not None:
                    accept = box.button(QtWidgets.QDialogButtonBox.Ok)
                if accept is None:
                    raise RuntimeError(f"{purpose} folder dialog has no accept button")
                self.click(accept)
            except BaseException as exc:
                fail(exc, modal)

        def drive_editor() -> None:
            modal = self.app.activeModalWidget()
            try:
                if self.context.deadline.remaining_seconds() <= 0:
                    raise RuntimeError(f"{purpose} reload deadline expired")
                if not isinstance(modal, ExperimentDesignDialog):
                    raise RuntimeError(
                        f"unexpected modal while opening {purpose} editor: "
                        f"{type(modal).__name__} {modal.windowTitle()!r}"
                    )
                QtCore.QTimer.singleShot(0, lambda: choose_directory(modal))
                self.click(modal.load_btn)
                if state["error"] is not None:
                    raise state["error"]
                state["loaded"] = dict(on_loaded(modal))
                if on_activated is not None:
                    state["activated"] = dict(on_activated(modal))
            except BaseException as exc:
                fail(exc, modal)

        QtCore.QTimer.singleShot(0, drive_editor)
        self.click(button)
        if state["error"] is not None:
            raise state["error"]
        if state["loaded"] is None or (on_activated and state["activated"] is None):
            raise RuntimeError(f"{purpose} UI reload did not finish")
        return {key: state[key] for key in ("loaded", "activated")}

    def load_authoritative_execution(
        self,
        experiment_dir,
        *,
        expected_name: str,
        before_activation: Callable[[], Mapping[str, Any]] | None = None,
        after_activation: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Load and activate one paused execution through the real editor."""

        import json
        from pathlib import Path

        from ExecutionPlan import canonical_sha256
        from tools.virtual_workflows.actions import (
            ScenarioActionError,
            capture_milestone,
            execute_action,
        )

        directory = Path(experiment_dir).resolve()
        def capture_failure(exc: BaseException, dialog) -> None:
            if (
                isinstance(dialog, QtWidgets.QDialog)
                and dialog.isVisible()
                and "session_2_load_failed" not in self.context.screenshots
            ):
                try:
                    capture_milestone(
                        self.context,
                        "session_2_load_failed",
                        evidence={
                            "failure_type": type(exc).__name__,
                            "failure_message": str(exc),
                        },
                        widget=dialog,
                    )
                except Exception:
                    pass

        def loaded_evidence(dialog) -> Mapping[str, Any]:
            eligibility = (
                self.context.experiment_model.get_execution_resume_eligibility() or {}
            )
            runtime_active = bool(
                self.context.experiment_model
                .is_authoritative_execution_runtime_active()
            )
            status_text = str(dialog.status_lbl.text() or "")
            banner_text = str(dialog.lifecycle_banner.text() or "")
            checks = {
                "name_matches": dialog.exp_name_edit.text() == expected_name,
                "action_is_load_execution": dialog.finish_btn.text()
                == "Load Execution",
                "finish_enabled": bool(dialog.finish_btn.isEnabled()),
                "eligibility_ready_to_resume": eligibility.get("status")
                == "ready_to_resume",
                "runtime_inactive": not runtime_active,
                "read_only_guidance": "execution plan validated"
                in status_text.casefold()
                and "load execution" in status_text.casefold(),
                "visible_lock_banner": not dialog.lifecycle_banner.isHidden()
                and "load execution" in banner_text.casefold()
                and "without starting or resuming printing"
                in banner_text.casefold(),
            }
            loaded_path = Path(self.context.experiment_model.experiment_file_path)
            disk_payload = json.loads(loaded_path.read_text(encoding="utf-8"))
            design_identity = {
                "experiment_dir_path": str(
                    self.context.experiment_model.experiment_dir_path
                ),
                "experiment_file_path": str(loaded_path),
                "disk_design_sha256": canonical_sha256(disk_payload),
                "model_design_sha256": canonical_sha256(
                    self.context.experiment_model.to_dict()
                ),
                "plan_design_sha256": self.context.experiment_model
                .get_execution_plan_snapshot()
                .design_sha256,
            }
            evidence = {
                "checks": checks,
                "eligibility": eligibility,
                "status_text": status_text,
                "banner_text": banner_text,
                "action_label": str(dialog.finish_btn.text() or ""),
                "design_identity": design_identity,
                "experiment_dir": str(directory),
            }
            if not all(checks.values()):
                raise ScenarioActionError(
                    "experiment.load_authoritative_via_ui",
                    "loaded authoritative editor state is invalid",
                    stage="operation",
                    evidence=evidence,
                )
            evidence["reload_boundary"] = (
                dict(before_activation()) if before_activation is not None else {}
            )
            return evidence

        def activate_evidence(dialog) -> Mapping[str, Any]:
            if dialog.finish_btn.text() != "Load Execution":
                raise RuntimeError("saved runtime did not expose Load Execution")
            self.click(dialog.finish_btn)
            if dialog.isVisible():
                raise RuntimeError("Load Execution did not close the editor")
            eligibility = (
                self.context.experiment_model.get_execution_resume_eligibility() or {}
            )
            runtime_active = bool(
                self.context.experiment_model
                .is_authoritative_execution_runtime_active()
            )
            array_state = self.context.controller.get_array_run_state()
            if (
                not runtime_active
                or eligibility.get("status") != "ready_to_resume"
                or array_state != "resume_ready"
            ):
                raise RuntimeError(
                    "authoritative activation did not restore resume_ready"
                )
            return {
                "eligibility": eligibility,
                "runtime_active": runtime_active,
                "array_state": array_state,
                "action_label": "Load Execution",
                "reload_boundary": (
                    dict(after_activation()) if after_activation is not None else {}
                ),
            }

        def record_loaded(dialog) -> Mapping[str, Any]:
            result = execute_action(
                self.context, "experiment.load_authoritative_via_ui",
                lambda: loaded_evidence(dialog),
            )
            evidence = dict(result["evidence"])
            capture_milestone(
                self.context, "session_2_loaded", evidence=evidence, widget=dialog
            )
            return evidence

        def record_activated(dialog) -> Mapping[str, Any]:
            return execute_action(
                self.context, "experiment.activate_authoritative_via_ui",
                lambda: activate_evidence(dialog),
            )["evidence"]

        return self._drive_directory_load(
            directory,
            purpose="authoritative",
            on_loaded=record_loaded,
            on_activated=record_activated,
            on_failure=capture_failure,
        )

    def load_prepared_design(
        self,
        experiment_dir,
        *,
        expected_name: str,
        expected_plan_id: str,
        expected_plan_revision: int,
    ) -> dict[str, Any]:
        from pathlib import Path
        directory = Path(experiment_dir).resolve()
        def inspect_loaded(dialog) -> Mapping[str, Any]:
                plan = self.context.experiment_model.get_execution_plan_snapshot()
                eligibility = (
                    self.context.experiment_model.get_execution_resume_eligibility()
                    or {}
                )
                runtime_active = bool(
                    self.context.experiment_model
                    .is_authoritative_execution_runtime_active()
                )
                checks = {
                    "name_matches": dialog.exp_name_edit.text() == expected_name,
                    "plan_id_matches": str(plan.plan_id) == str(expected_plan_id),
                    "plan_revision_matches": int(plan.plan_revision)
                    == int(expected_plan_revision),
                    "plan_prepared": str(plan.state.value) == "prepared",
                    "eligibility_ready_to_start": eligibility.get("status")
                    == "ready_to_start",
                    "runtime_inactive": not runtime_active,
                    "path_matches": Path(
                        self.context.experiment_model.experiment_dir_path
                    ).resolve()
                    == directory,
                }
                if not all(checks.values()):
                    raise RuntimeError(
                        f"prepared design did not reload unchanged: {checks}"
                    )
                result = {
                    "checks": checks,
                    "experiment_dir": str(directory),
                    "experiment_name": dialog.exp_name_edit.text(),
                    "plan_id": str(plan.plan_id),
                    "plan_revision": int(plan.plan_revision),
                    "plan_state": str(plan.state.value),
                    "eligibility_status": eligibility.get("status"),
                    "runtime_active": runtime_active,
                    "activation_performed": False,
                    "file_selection_mechanic": "qt_file_dialog_directory_selection",
                }
                QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
                if dialog.isVisible():
                    raise RuntimeError("prepared inspection editor did not close")
                return result

        return self._drive_directory_load(
            directory, purpose="prepared", on_loaded=inspect_loaded
        )["loaded"]


class RackDriver(_QTestSurfaceDriver):
    """QTest mechanics for rack volume, confirmation, and head loading."""

    def set_slot_volume(self, slot_index: int, volume_uL: float) -> None:
        rack = self.view.rack_box
        volume_label = rack.slot_widgets[int(slot_index)][1]
        state: dict[str, Any] = {"entered": False, "error": None}

        def drive_dialog() -> None:
            active = self.app.activeModalWidget()
            try:
                if active is None or active.windowTitle() != "Edit Volume":
                    raise RuntimeError("Edit Volume dialog did not open")
                state["entered"] = True
                spin = active.findChild(QtWidgets.QDoubleSpinBox)
                button = next(
                    (
                        item
                        for item in active.findChildren(QtWidgets.QPushButton)
                        if item.text() == "Update volume"
                    ),
                    None,
                )
                if spin is None or button is None:
                    raise RuntimeError("Edit Volume controls are missing")
                self.replace_spin_value(spin, volume_uL)
                # Enter on the spin editor may activate the dialog's default
                # Update button. Click it only when the modal is still open.
                if active.isVisible():
                    QtTest.QTest.mouseClick(
                        button, QtCore.Qt.MouseButton.LeftButton
                    )
            except BaseException as exc:
                state["error"] = exc
                if isinstance(active, QtWidgets.QDialog) and active.isVisible():
                    active.reject()

        QtCore.QTimer.singleShot(0, drive_dialog)
        QtTest.QTest.mouseDClick(
            volume_label,
            QtCore.Qt.MouseButton.LeftButton,
        )
        if state["error"] is not None:
            raise state["error"]
        if not state["entered"]:
            raise RuntimeError("Edit Volume dialog did not run")
        head = self.context.model.rack_model.slots[int(slot_index)].printer_head
        self.wait_until(
            lambda: head is not None
            and abs(float(head.get_current_volume() or 0.0) - float(volume_uL))
            < 1e-6,
            "printer-head volume update",
        )

    def confirm_and_load(self, slot_index: int) -> None:
        rack = self.view.rack_box
        button = rack.slot_widgets[int(slot_index)][2]
        if button.text() != "Confirm":
            raise RuntimeError(f"expected Confirm control; observed {button.text()!r}")
        self.click(button)
        self.wait_until(lambda: button.text() == "Load", "rack slot confirmation")
        self.click(button)
        self.wait_until(
            lambda: self.context.model.rack_model.get_gripper_printer_head()
            is not None,
            "printer-head load",
        )
        self.wait_until(
            self.context.machine.check_if_all_completed,
            "printer-head load command queue",
        )

    def find_slot_for_stock(self, stock_id: str) -> int:
        matches = [
            index
            for index, slot in enumerate(self.context.model.rack_model.slots)
            if slot.printer_head is not None
            and str(slot.printer_head.get_stock_id()) == str(stock_id)
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one rack slot for stock {stock_id!r}; observed {matches}"
            )
        return matches[0]

    def unload(self, slot_index: int) -> None:
        rack = self.view.rack_box
        button = rack.slot_widgets[int(slot_index)][2]
        if button.text() != "Unload":
            raise RuntimeError(f"expected Unload control; observed {button.text()!r}")
        self.click(button)
        self.wait_until(
            lambda: self.context.model.rack_model.get_gripper_printer_head()
            is None,
            "printer-head return",
        )
        self.wait_until(
            self.context.machine.check_if_all_completed,
            "printer-head return command queue",
        )


class ArrayDriver(_QTestSurfaceDriver):
    """QTest mechanics for the normal print-array surface."""

    @property
    def control(self):
        return self.view.well_plate_widget.start_print_array_button

    def _require_control(self, text: str, *, enabled: bool = True) -> None:
        button = self.control
        if button.text() != text or bool(button.isEnabled()) is not bool(enabled):
            raise RuntimeError(
                f"expected {text!r} array control (enabled={enabled}); observed "
                f"{button.text()!r} (enabled={button.isEnabled()})"
            )

    def click_start(self) -> None:
        self.click(self.control)

    def start(
        self,
        expected_dialogs: list[tuple[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return self.click_with_message_boxes(
            self.control,
            expected_dialogs or [
                ("Start Print Array", QtWidgets.QMessageBox.StandardButton.Yes),
                (
                    "Evaporation Plate Dock Check",
                    QtWidgets.QMessageBox.StandardButton.Yes,
                ),
            ],
        )

    def request_soft_stop(self) -> dict[str, Any]:
        """Click the running array control; trigger timing remains journey policy."""

        self._require_control("Stop After Well")
        before = self.control.text()
        self.click(self.control)
        self.wait_until(
            lambda: self.control.text() == "Stop Pending"
            and not self.control.isEnabled(),
            "soft-stop pending control",
        )
        return {
            "button_text_before": before,
            "button_text_after": self.control.text(),
            "button_enabled_after": bool(self.control.isEnabled()),
        }

    def resume(self) -> dict[str, Any]:
        """Resume a paused array through the normal control and confirmation."""

        self._require_control("Resume Print")
        dialogs = self.click_with_message_boxes(
            self.control,
            [("Resume Print Array", QtWidgets.QMessageBox.StandardButton.Yes)],
        )
        self.wait_until(
            lambda: self.context.controller.get_array_run_state() == "running",
            "resumed array running state",
        )
        return {
            "dialogs": dialogs,
            "array_state": self.context.controller.get_array_run_state(),
            "button_text": self.control.text(),
        }


class CalibrationDialogDriver:
    """Bounded QTest mechanics for the normal simulation calibration dialog."""

    def __init__(self, app, dialog, *, timeout_seconds: float = 10.0):
        self.app = app
        self.dialog = dialog
        self.timeout_seconds = float(timeout_seconds)

    def wait_until(self, predicate: Callable[[], bool], description: str) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QtTest.QTest.qWait(10)
        raise RuntimeError(f"timed out waiting for {description}")

    def inspect_presentation(self) -> dict[str, Any]:
        banner = self.dialog.findChild(QtWidgets.QLabel, "syntheticCalibrationBanner")
        mode_label = self.dialog.findChild(
            QtWidgets.QLabel, "syntheticCalibrationModeLabel"
        )
        table = self.dialog.findChild(QtWidgets.QTableView, "characterizationSummaryTable")
        if banner is None or mode_label is None or table is None:
            raise RuntimeError("synthetic calibration presentation controls are missing")
        return {
            "window_title": self.dialog.windowTitle(),
            "banner_text": banner.text(),
            "banner_visible": banner.isVisible(),
            "mode_text": mode_label.text(),
            "mode_visible": mode_label.isVisible(),
            "row_count": table.model().rowCount(),
            "source_filter": self.dialog.summary_source_combo.currentData(),
        }

    def _schedule_profile_preflight_acceptance(self, profile_id: str | None) -> None:
        deadline = time.monotonic() + self.timeout_seconds

        def _accept_when_visible():
            modal = QtWidgets.QApplication.activeModalWidget()
            if modal is None or modal.windowTitle() != "Calibration Settings Check":
                if time.monotonic() >= deadline:
                    return
                QtCore.QTimer.singleShot(10, _accept_when_visible)
                return
            combo = modal.findChild(QtWidgets.QComboBox)
            if combo is not None and profile_id:
                match = -1
                for index in range(combo.count()):
                    data = combo.itemData(index)
                    if isinstance(data, dict) and str(data.get("id") or "") == profile_id:
                        match = index
                        break
                if match < 0:
                    modal.reject()
                    raise RuntimeError(
                        f"calibration print profile is unavailable: {profile_id}"
                    )
                combo.setCurrentIndex(match)
            apply_button = next(
                (
                    button
                    for button in modal.findChildren(QtWidgets.QPushButton)
                    if button.text() == "Apply Selected Profile and Continue"
                ),
                None,
            )
            if apply_button is None:
                modal.reject()
                raise RuntimeError("profile application control is missing from preflight")
            QtTest.QTest.mouseClick(
                apply_button,
                QtCore.Qt.MouseButton.LeftButton,
            )

        QtCore.QTimer.singleShot(0, _accept_when_visible)

    def generate_from_tab(
        self,
        target_mode: str,
        *,
        print_profile_id: str | None = None,
    ) -> dict[str, Any]:
        """Use the real tab and Calibrate All control to generate one result."""

        target_mode = str(target_mode or "").strip().lower()
        if target_mode == "droplet":
            tab = self.dialog.droplet_tab
            button = self.dialog.calibrate_all_button
        elif target_mode == "stream":
            tab = self.dialog.stream_tab
            button = self.dialog.calibrate_all_stream_button
        else:
            raise ValueError("target_mode must be droplet or stream")
        self.dialog.calibration_tabs.setCurrentWidget(tab)
        self.app.processEvents()
        if not button.isEnabled():
            raise RuntimeError(
                f"synthetic {target_mode} Calibrate All is unavailable: {button.toolTip()}"
            )
        profile_id = str(button.property("synthetic_profile_id") or "")
        availability = getattr(self.dialog, "synthetic_availability_callback", None)
        readiness = dict(availability(profile_id) or {}) if callable(availability) else {}
        if readiness.get("correctable"):
            self._schedule_profile_preflight_acceptance(print_profile_id)
        QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)

        generated: dict[str, Any] = {}

        def _generated_result_visible():
            manager = getattr(self.dialog.model, "calibration_manager", None)
            stored = getattr(manager, "_transient_characterization_candidate", None)
            candidate = stored.get("candidate") if isinstance(stored, dict) else None
            expected = str(getattr(candidate, "result_fingerprint", "") or "")
            if not expected:
                return False
            for row in range(self.dialog.summary_table_model.rowCount()):
                raw = self.dialog.summary_table_model.raw_row_at(row) or {}
                fingerprint = str(raw.get("synthetic_result_fingerprint") or "")
                if fingerprint == expected:
                    generated.update(raw)
                    return True
            return False

        self.wait_until(
            _generated_result_visible,
            f"synthetic {target_mode} result generation",
        )
        return dict(generated)

    def select_result(self, result_fingerprint: str) -> dict[str, Any]:
        table = self.dialog.summary_table
        proxy = self.dialog.summary_table_proxy_model
        source = self.dialog.summary_table_model
        match = None
        for proxy_row in range(proxy.rowCount()):
            source_index = proxy.mapToSource(proxy.index(proxy_row, 0))
            raw = source.raw_row_at(source_index.row()) or {}
            if raw.get("synthetic_result_fingerprint") == str(result_fingerprint):
                match = (proxy_row, raw)
                break
        if match is None:
            raise RuntimeError(f"synthetic result is not visible: {result_fingerprint}")
        proxy_row, raw = match
        target = proxy.index(proxy_row, 1)
        rect = table.visualRect(target)
        QtTest.QTest.mouseClick(
            table.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=rect.center(),
        )
        self.wait_until(
            lambda: bool(self.dialog._selected_summary_row()[1]),
            "synthetic calibration row selection",
        )
        return dict(raw)

    def inspect_preview(self) -> dict[str, Any]:
        payload = dict(getattr(self.dialog, "_bridge_preview_payload", None) or {})
        return {
            "payload": payload,
            "status": self.dialog.bridge_status_label.text(),
            "apply_enabled": self.dialog.bridge_apply_btn.isEnabled(),
            "apply_text": self.dialog.bridge_apply_btn.text(),
            "preview_rows": self.dialog.bridge_table.rowCount(),
        }

    def apply_selected(
        self,
        *,
        expected_title: str | None = "Applied",
        mode_switch_choice: str | None = None,
        manual_refuel_choice: str | None = None,
    ) -> list[str]:
        steps: list[tuple[str, Any]] = []
        if mode_switch_choice is not None:
            choice = str(mode_switch_choice).strip().lower()
            if choice not in {"yes", "no"}:
                raise ValueError("mode_switch_choice must be yes, no, or None")
            steps.append(
                (
                    "Apply calibration as mode switch?",
                    QtWidgets.QMessageBox.Yes
                    if choice == "yes"
                    else QtWidgets.QMessageBox.No,
                )
            )
        if manual_refuel_choice is not None:
            choice = str(manual_refuel_choice).strip().lower()
            if choice not in {"yes", "no"}:
                raise ValueError("manual_refuel_choice must be yes, no, or None")
            steps.append(
                (
                    "Manual Refuel Check Required",
                    QtWidgets.QMessageBox.Yes
                    if choice == "yes"
                    else QtWidgets.QMessageBox.No,
                )
            )
        elif expected_title is not None:
            steps.append((str(expected_title), None))

        state: dict[str, Any] = {"handled": [], "error": None}

        def handle_modal():
            if not steps:
                return
            active = self.app.activeModalWidget()
            if not isinstance(active, QtWidgets.QMessageBox):
                state["error"] = RuntimeError(
                    f"unexpected Apply modal: {type(active).__name__ if active else None}"
                )
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                return
            expected_step_title, standard_button = steps.pop(0)
            if active.windowTitle() != expected_step_title:
                state["error"] = RuntimeError(
                    f"unexpected Apply dialog title: {active.windowTitle()!r}"
                )
                active.reject()
                return
            state["handled"].append(active.windowTitle())
            if standard_button is None:
                active.accept()
            else:
                button = active.button(standard_button)
                if button is None:
                    state["error"] = RuntimeError(
                        f"expected button is missing from {active.windowTitle()!r}"
                    )
                    active.reject()
                    return
                QtTest.QTest.mouseClick(
                    button,
                    QtCore.Qt.MouseButton.LeftButton,
                )
            if steps:
                QtCore.QTimer.singleShot(0, handle_modal)

        QtCore.QTimer.singleShot(0, handle_modal)
        QtTest.QTest.mouseClick(
            self.dialog.bridge_apply_btn,
            QtCore.Qt.MouseButton.LeftButton,
        )
        if state["error"] is not None:
            raise state["error"]
        if steps:
            raise RuntimeError("expected calibration Apply dialog sequence did not complete")
        return list(state["handled"])

    def close(self) -> None:
        self.dialog.close()
        self.wait_until(lambda: not self.dialog.isVisible(), "calibration dialog close")


__all__ = [
    "ArrayDriver",
    "CalibrationDialogDriver",
    "ExperimentEditorDriver",
    "ExperimentLoaderDriver",
    "MachineControlsDriver",
    "MainWindowDriver",
    "RackDriver",
]
