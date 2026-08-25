"""Small Qt page drivers shared by interactive SIL lifecycle tests."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import math
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PySide6 import QtCore, QtTest, QtWidgets
import shiboken6


def _qt_dialog_is_visible(dialog: Any) -> bool:
    """Return false once Qt has deleted a retained Python dialog wrapper."""

    return bool(
        isinstance(dialog, QtWidgets.QDialog)
        and shiboken6.isValid(dialog)
        and dialog.isVisible()
    )


def _click_button_with_bounded_retry(
    context: Any,
    button: Any,
    *,
    postcondition: Callable[[], bool],
    description: str,
    activated_postcondition_timeout_seconds: float = 0.0,
) -> dict[str, Any]:
    """Use mouse-only activation with one retry after a proven no-op."""

    activations: list[bool] = []
    attempts: list[dict[str, Any]] = []

    def record_activation(*_args: Any) -> None:
        activations.append(True)

    button.clicked.connect(record_activation)
    try:
        for attempt in (1, 2):
            if button is None or not button.isVisible() or not button.isEnabled():
                raise RuntimeError(
                    f"{description} control is not visible and enabled"
                )
            activation_count = len(activations)
            window = button.window()
            if window is not None:
                window.activateWindow()
            button.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            context.app.processEvents()

            QtTest.QTest.mouseMove(button, button.rect().center())
            QtTest.QTest.qWait(5)
            QtTest.QTest.mousePress(
                button, QtCore.Qt.MouseButton.LeftButton
            )
            QtTest.QTest.qWait(10)
            QtTest.QTest.mouseRelease(
                button, QtCore.Qt.MouseButton.LeftButton
            )
            QtTest.QTest.qWait(10)
            context.app.processEvents()

            activated = len(activations) > activation_count
            satisfied = bool(postcondition())
            if activated and not satisfied:
                postcondition_deadline = time.monotonic() + max(
                    0.0, float(activated_postcondition_timeout_seconds)
                )
                while (
                    not satisfied
                    and time.monotonic() < postcondition_deadline
                ):
                    QtTest.QTest.qWait(10)
                    context.app.processEvents()
                    satisfied = bool(postcondition())
            attempts.append(
                {
                    "attempt": attempt,
                    "activated": activated,
                    "postcondition_met": satisfied,
                }
            )
            if satisfied:
                return {
                    "attempt_count": attempt,
                    "retried": attempt > 1,
                    "attempts": attempts,
                }
            if activated:
                raise RuntimeError(
                    f"{description} activated without satisfying its "
                    f"authoritative postcondition: {attempts}"
                )
        raise RuntimeError(
            f"{description} did not activate after one bounded retry: "
            f"{attempts}"
        )
    finally:
        button.clicked.disconnect(record_activation)


@contextmanager
def _expected_dialogs(app: Any, *specs: tuple[str, str]):
    """Temporarily register dialogs that one driver is actively controlling."""

    registry = getattr(app, "_sil_expected_dialog_specs", [])
    setattr(app, "_sil_expected_dialog_specs", registry)
    entries = [{"title": str(title), "type": str(kind)} for title, kind in specs]
    registry.extend(entries)
    try:
        yield
    finally:
        for entry in entries:
            if entry in registry:
                registry.remove(entry)


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

    def select_combo_index(
        self, combo: Any, index: int, *, selected: Callable[[], bool] | None = None
    ) -> None:
        """Select one popup item with one safe retry when no write occurs."""

        target_index = int(index)
        if combo is None or not combo.isVisible() or not combo.isEnabled():
            raise RuntimeError("requested combobox is not visible and enabled")
        if target_index < 0 or target_index >= combo.count():
            raise RuntimeError(f"combobox index is out of range: {target_index}")
        target_text = str(combo.itemText(target_index))
        activations: list[int] = []
        record_activation = lambda value: activations.append(int(value))
        combo.activated.connect(record_activation)
        last_attempt = "not started"

        def close_popup(popup: Any, description: str) -> None:
            combo.hidePopup()
            self.context.pump_events()
            self.wait_until(
                lambda: not popup.isVisible(),
                description,
                timeout_seconds=1.0,
            )

        def popup_diagnostics(
            popup: Any,
            rect: Any,
            *,
            attempt: int,
            index: int,
            attempt_activations: list[int],
            postcondition_met: bool,
        ) -> str:
            active = self.app.activeWindow()
            active_name = type(active).__name__ if active is not None else None
            global_center = (
                popup.viewport().mapToGlobal(rect.center()) if rect.isValid() else None
            )
            widget_at_target = (
                self.app.widgetAt(global_center) if global_center is not None else None
            )
            focus = self.app.focusWidget()
            return (
                f"attempt={attempt}, index={index}, "
                f"current_index={combo.currentIndex()}, "
                f"current_text={combo.currentText()!r}, "
                f"activations={attempt_activations}, "
                f"postcondition={postcondition_met}, "
                f"popup_visible={popup.isVisible()}, "
                f"popup_geometry={popup.geometry().getRect()}, "
                f"viewport_geometry={popup.viewport().rect().getRect()}, "
                f"target_rect={rect.getRect() if rect.isValid() else None}, "
                f"target_global_center="
                f"{(global_center.x(), global_center.y()) if global_center else None}, "
                f"widget_at_target="
                f"{type(widget_at_target).__name__ if widget_at_target else None}, "
                f"target_is_viewport={widget_at_target is popup.viewport()}, "
                f"index_at_target={popup.indexAt(rect.center()).row()}, "
                f"popup_current_index={popup.currentIndex().row()}, "
                f"focus_widget={type(focus).__name__ if focus else None}, "
                f"active_window={active_name}"
            )

        try:
            for attempt in (1, 2):
                if selected is not None and selected():
                    return
                popup = combo.view()
                if popup.isVisible():
                    close_popup(popup, "stale combobox popup cleanup")
                matches = [
                    index
                    for index in range(combo.count())
                    if combo.itemText(index) == target_text
                ]
                if len(matches) != 1:
                    raise RuntimeError(
                        f"combobox target changed: {target_text!r}; indices={matches}"
                    )
                target_index = matches[0]
                activation_offset = len(activations)
                QtTest.QTest.mouseClick(combo, QtCore.Qt.MouseButton.LeftButton)
                self.context.pump_events()
                self.wait_until(popup.isVisible, "combobox popup")
                model_index = combo.model().index(
                    target_index,
                    combo.modelColumn(),
                    combo.rootModelIndex(),
                )
                popup.scrollTo(model_index)
                self.context.pump_events()
                self.wait_until(
                    lambda: popup.visualRect(model_index).isValid()
                    and popup.visualRect(model_index).intersects(
                        popup.viewport().rect()
                    ),
                    "combobox target geometry",
                    timeout_seconds=1.0,
                )
                rect = popup.visualRect(model_index)
                if not rect.isValid():
                    raise RuntimeError(f"combobox item is not visible: {target_index}")
                popup.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
                self.context.pump_events()
                # QComboBox's popup container suppresses mouse releases for the
                # application's double-click interval after a click opens it.
                # Wait out that bounded guard so the distinct item click is not
                # mistaken for the release that opened the popup.
                release_guard_ms = min(
                    max(int(self.app.doubleClickInterval()), 0) + 25,
                    750,
                )
                QtTest.QTest.qWait(release_guard_ms)
                viewport_rect = popup.viewport().rect()
                neutral = (
                    viewport_rect.topLeft()
                    if rect.contains(viewport_rect.bottomRight())
                    else viewport_rect.bottomRight()
                )
                QtTest.QTest.mouseMove(popup.viewport(), neutral)
                QtTest.QTest.qWait(25)
                QtTest.QTest.mouseMove(popup.viewport(), rect.center())
                QtTest.QTest.qWait(25)
                QtTest.QTest.mousePress(
                    popup.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center()
                )
                QtTest.QTest.qWait(25)
                QtTest.QTest.mouseRelease(
                    popup.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center()
                )
                self.context.pump_events()

                settle_deadline = (
                    time.monotonic()
                    + self.context.deadline.remaining_seconds(1.0)
                )
                while time.monotonic() < settle_deadline:
                    self.context.pump_events()
                    new_activations = activations[activation_offset:]
                    postcondition_met = (
                        bool(selected()) if selected is not None else False
                    )
                    if postcondition_met or new_activations:
                        break
                    QtTest.QTest.qWait(5)
                self.context.pump_events()
                new_activations = activations[activation_offset:]
                postcondition_met = (
                    bool(selected()) if selected is not None else False
                )
                last_attempt = popup_diagnostics(
                    popup,
                    rect,
                    attempt=attempt,
                    index=target_index,
                    attempt_activations=new_activations,
                    postcondition_met=postcondition_met,
                )
                if postcondition_met or (
                    selected is None and target_index in new_activations
                ):
                    close_popup(popup, "combobox popup cleanup after selection")
                    return
                if new_activations:
                    close_popup(popup, "combobox popup cleanup after ambiguous write")
                    raise RuntimeError(
                        "combobox activation had no postcondition: "
                        f"target={target_text!r}; {last_attempt}"
                    )
                close_popup(popup, "combobox popup cleanup before retry")
            raise RuntimeError(
                "combobox selection produced no activation: "
                f"target={target_text!r}; {last_attempt}"
            )
        finally:
            try:
                combo.activated.disconnect(record_activation)
            except (RuntimeError, TypeError):
                pass

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
        expected: list[tuple[str, Any]],
    ) -> list[dict[str, Any]]:
        """Click once and accept only the exact ordered QMessageBox sequence."""

        handled: list[dict[str, Any]] = []
        state: dict[str, Any] = {"error": None}
        deadline = time.monotonic() + self.context.deadline.remaining_seconds(10.0)
        inspection_timer = QtCore.QTimer(self.app)
        inspection_timer.setInterval(5)

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
            if not isinstance(active, QtWidgets.QMessageBox):
                state["error"] = RuntimeError(
                    "unexpected modal while handling action: "
                    f"{type(active).__name__} {active.windowTitle()!r}"
                )
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                return
            expected_title, requested_button = expected[len(handled)]
            if active.windowTitle() != expected_title:
                state["error"] = RuntimeError(
                    f"unexpected dialog title {active.windowTitle()!r}; "
                    f"expected {expected_title!r}"
                )
                active.reject()
                return
            if isinstance(requested_button, str):
                button = next(
                    (
                        candidate
                        for candidate in active.buttons()
                        if candidate.text().replace("&", "").strip()
                        == requested_button
                    ),
                    None,
                )
            else:
                button = active.button(requested_button)
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

        inspection_timer.timeout.connect(inspect)

        inspection_timer.start()
        try:
            with _expected_dialogs(
                self.app,
                *((title, "QMessageBox") for title, _button in expected),
            ):
                _click_button_with_bounded_retry(
                    self.context,
                    widget,
                    postcondition=lambda: (
                        state["error"] is not None
                        or len(handled) == len(expected)
                    ),
                    description="message-box action button",
                )
        finally:
            inspection_timer.stop()
            inspection_timer.deleteLater()
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

    def inspect_calibration_launch_state(self) -> dict[str, Any]:
        """Capture the normal printer-head calibration launch boundary."""

        button = self.view.pressure_box.calibrate_pressure_button
        rack = self.context.model.rack_model
        head = rack.get_gripper_printer_head()
        read_only_getter = getattr(
            self.context.model, "is_read_only_experiment_view_active", None
        )
        return {
            "button_text": str(button.text() or ""),
            "button_enabled": bool(button.isEnabled()),
            "button_tooltip": str(button.toolTip() or ""),
            "historical_read_only": bool(
                callable(read_only_getter) and read_only_getter()
            ),
            "head_present": head is not None,
            "printer_head_id": (
                str(getattr(head, "printer_head_id", "") or "")
                if head is not None
                else None
            ),
            "stock_id": str(head.get_stock_id()) if head is not None else None,
        }

    def connect(self) -> None:
        button = self.view.connection_widget.machine_connect_button
        if button.text() != "Connect":
            raise RuntimeError(f"expected Connect control; observed {button.text()!r}")
        self.click(button)
        self.wait_until(
            lambda: self.context.model.machine_model.is_connected(),
            "simulator connection",
        )

    def disconnect(self) -> dict[str, Any]:
        """Disconnect through the normal connection control and wait for UI truth."""

        widget = self.view.connection_widget
        button = widget.machine_connect_button
        if button.text() != "Disconnect" or not button.isEnabled():
            raise RuntimeError(
                "expected enabled Disconnect control; observed "
                f"{button.text()!r} enabled={button.isEnabled()}"
            )
        before = {
            "button_text": button.text(),
            "model_connected": bool(self.context.model.machine_model.is_connected()),
            "simulator_connected": bool(self.context.machine.state.connected),
        }
        self.click(button)
        self.wait_until(
            lambda: (
                not self.context.model.machine_model.is_connected()
                and not self.context.machine.state.connected
                and self.context.machine.check_if_all_completed()
                and not bool(getattr(widget, "_machine_disconnect_pending", False))
                and button.text() == "Connect"
                and button.isEnabled()
            ),
            "simulator disconnect and normal connection-control recovery",
        )
        return {
            "before": before,
            "button_text_after": button.text(),
            "button_enabled_after": bool(button.isEnabled()),
            "disconnect_pending_after": bool(
                getattr(widget, "_machine_disconnect_pending", False)
            ),
            "model_connected_after": bool(
                self.context.model.machine_model.is_connected()
            ),
            "simulator_connected_after": bool(self.context.machine.state.connected),
            "simulator_queue_empty": bool(
                self.context.machine.check_if_all_completed()
            ),
        }

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
        refuel_pulse_width_us: int | None = None,
        refuel_pressure_psi: float | None = None,
    ) -> None:
        box = self.view.pressure_box
        self.replace_spin_value(box.print_pulse_width_spinbox, pulse_width_us)
        self.replace_spin_value(box.target_print_pressure_spinbox, pressure_psi)
        self.replace_spin_value(box.print_frequency_spinbox, frequency_hz)
        if refuel_pulse_width_us is not None:
            self.replace_spin_value(
                box.refuel_pulse_width_spinbox, refuel_pulse_width_us
            )
        if refuel_pressure_psi is not None:
            self.replace_spin_value(
                box.target_refuel_pressure_spinbox, refuel_pressure_psi
            )
        self.wait_until(
            self.context.machine.check_if_all_completed,
            "print settings command queue",
        )

    def enable_pressure_regulation(self, *, require_refuel: bool = False) -> None:
        button = self.view.pressure_box.pressure_regulation_button
        self.click(button)
        self.wait_until(
            lambda: bool(
                self.context.model.machine_model.regulating_print_pressure
            ) and (
                not require_refuel
                or bool(self.context.model.machine_model.regulating_refuel_pressure)
            ),
            "print/refuel-pressure regulation" if require_refuel else "print-pressure regulation",
        )
        self.wait_until(self.context.machine.check_if_all_completed, "pressure regulation command queue")

    def open_calibration_dialog(self) -> Any:
        button = self.view.pressure_box.calibrate_pressure_button
        self.click(button)
        self.wait_until(
            lambda: (
                getattr(self.view.pressure_box, "_droplet_imager_dialog", None)
                is not None
                and getattr(
                    self.view.pressure_box,
                    "_droplet_imager_dialog_state",
                    "inactive",
                )
                == "active"
            ),
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
        capture_milestones: bool = True,
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
            capture_milestones=capture_milestones,
        )

    def run_prepared_sequence(
        self,
        *,
        initial_name: str,
        renamed_name: str,
        experiment: Mapping[str, Any],
        reagent: Mapping[str, Any],
        sequence_steps: Sequence[Mapping[str, Any]],
        intermediate_tolerance_nl: float,
    ) -> dict[str, Any]:
        """Run a validated ordered prepared-editor sequence."""

        from tools.virtual_workflows.actions import drive_editor_prepared_sequence

        return drive_editor_prepared_sequence(
            self.context,
            initial_name=initial_name,
            renamed_name=renamed_name,
            experiment=experiment,
            reagent=reagent,
            sequence_steps=sequence_steps,
            intermediate_tolerance_nl=intermediate_tolerance_nl,
            action_runner=self.action_runner,
        )

    def inspect_lock_and_create_editable_copy(
        self,
        *,
        source_dir: Path,
        source_name: str,
        copy_name: str,
        copy_tolerance_nl: float,
    ) -> dict[str, Any]:
        """Inspect a locked source and finalize one editable copy."""

        return _drive_editor_post_start_lock_and_copy(
            self.context,
            source_dir=Path(source_dir),
            source_name=source_name,
            copy_name=copy_name,
            copy_tolerance_nl=copy_tolerance_nl,
            action_runner=self.action_runner,
        )

    def exercise_new_session_hardening(
        self,
        *,
        source_dir: Path,
        experiments_root: Path,
        candidate_name: str,
        failed_candidate_name: str,
        resume_success_name: str,
        idle_success_name: str,
    ) -> dict[str, Any]:
        """Drive cancel, failure, resume-success, and idle-success resets."""

        import hashlib
        import json
        from unittest.mock import patch

        import Model as model_module
        from View import ExperimentDesignDialog
        from tools.virtual_workflows.actions import capture_milestone

        source_dir = Path(source_dir).resolve()
        experiments_root = Path(experiments_root).resolve()
        if source_dir.parent != experiments_root:
            raise RuntimeError("new-session source is outside the SIL experiment root")

        state: dict[str, Any] = {
            "entered": False,
            "finished": False,
            "error": None,
            "dialog": None,
            "evidence": None,
        }
        load_events: list[bool] = []
        generation_events: list[tuple[Any, ...]] = []
        load_slot = lambda: load_events.append(True)
        generation_slot = lambda *args: generation_events.append(tuple(args))
        self.context.model.experiment_loaded.connect(load_slot)
        self.context.experiment_model.experiment_generated.connect(generation_slot)

        def file_hashes(directory: Path) -> dict[str, str]:
            if not directory.is_dir():
                return {}
            return {
                str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            }

        def runtime_state() -> dict[str, Any]:
            model = self.context.model
            rack = model.rack_model
            head_manager = model.printer_head_manager
            return {
                "reaction_count": len(model.reaction_collection.reactions),
                "assigned_well_count": sum(
                    well.assigned_reaction is not None
                    for well in model.well_plate.get_all_wells()
                ),
                "stock_count": len(model.stock_solutions.stock_solutions),
                "rack_stock_head_count": sum(
                    slot.printer_head is not None
                    and not slot.printer_head.is_calibration_chip()
                    for slot in rack.slots
                ),
                "non_calibration_head_count": sum(
                    not head.is_calibration_chip()
                    for head in head_manager.printer_heads
                ),
                "gripper_loaded": rack.get_gripper_printer_head() is not None,
            }

        def ui_state(dialog: ExperimentDesignDialog) -> dict[str, Any]:
            controls = {
                name: {
                    "enabled": bool(getattr(dialog, name).isEnabled()),
                    "read_only": (
                        bool(getattr(dialog, name).isReadOnly())
                        if hasattr(getattr(dialog, name), "isReadOnly")
                        else None
                    ),
                }
                for name in (
                    "exp_name_edit",
                    "rep_spin",
                    "v_spin",
                    "final_v_spin",
                    "fill_name_edit",
                    "fill_mode_combo",
                    "fill_dv_spin",
                    "subset_chk",
                    "well_selection_btn",
                    "add_reagent_btn",
                    "upload_design_btn",
                    "run_btn",
                    "save_btn",
                )
            }
            return {
                "controls": controls,
                "reset_upload_hidden": bool(dialog.reset_upload_btn.isHidden()),
                "lifecycle_banner_hidden": bool(dialog.lifecycle_banner.isHidden()),
                "stock_stale": bool(dialog._stock_table_stale_active),
                "stock_status_hidden": bool(dialog.stock_table_status_lbl.isHidden()),
                "stock_status_text": str(dialog.stock_table_status_lbl.text() or ""),
                "uploaded_design_active": bool(dialog._uploaded_design_active),
                "uploaded_design_path": dialog._uploaded_design_path,
                "progress_protected": bool(dialog._progress_protected),
                "optimization_dirty": bool(dialog._design_optimization_dirty),
                "last_optimization_result": dialog._last_optimization_result,
                "auto_update": bool(dialog.auto_update_chk.isChecked()),
                "advanced_visible": bool(dialog.advanced_settings_panel.isVisible()),
                "status_text": str(dialog.status_lbl.text() or ""),
            }

        def session_state(dialog: ExperimentDesignDialog) -> dict[str, Any]:
            experiment = self.context.experiment_model
            path = Path(experiment.experiment_dir_path).resolve()
            design_path = path / "experiment_design.json"
            progress_path = path / "progress.json"
            design = (
                json.loads(design_path.read_text(encoding="utf-8"))
                if design_path.is_file()
                else None
            )
            progress = (
                json.loads(progress_path.read_text(encoding="utf-8"))
                if progress_path.is_file()
                else None
            )
            return {
                "experiment_model_id": id(experiment),
                "experiment_dir": str(path),
                "experiment_name": str(experiment.metadata.get("name") or ""),
                "array_state": self.context.controller.get_array_run_state(),
                "array_context_id": (
                    id(self.context.controller._array_context)
                    if self.context.controller._array_context is not None
                    else None
                ),
                "factor_count": len(experiment.factors),
                "additional_condition_count": len(experiment.additional_conditions),
                "uploaded_design": bool(experiment.has_uploaded_design()),
                "uploaded_well_ids": getattr(experiment, "_uploaded_well_ids", None),
                "progress": json.loads(json.dumps(experiment.progress_data)),
                "execution_locked": bool(experiment.is_execution_design_locked()),
                "runtime": runtime_state(),
                "design": design,
                "progress_file": progress,
                "execution_plan_exists": (path / "execution_plan.json").exists(),
                "execution_resume_exists": (path / "execution_resume.json").exists(),
                "directory_hashes": file_hashes(path),
                "load_signal_count": len(load_events),
                "generation_signal_count": len(generation_events),
                "ui": ui_state(dialog),
            }

        def record_dialog(widget: QtWidgets.QMessageBox, selected: str) -> dict[str, Any]:
            default = widget.defaultButton()
            escape = widget.escapeButton()
            entry = {
                "title": widget.windowTitle(),
                "text": widget.text(),
                "informative_text": widget.informativeText(),
                "buttons": [button.text().replace("&", "") for button in widget.buttons()],
                "default_button": (
                    default.text().replace("&", "") if default is not None else None
                ),
                "escape_button": (
                    escape.text().replace("&", "") if escape is not None else None
                ),
                "selected_button": selected,
            }
            self.context.dialogs.append(dict(entry))
            self.context.record_event("dialog", **entry)
            return entry

        original_initialize = (
            model_module.ExperimentModel.initialize_new_experiment_session
        )

        def deterministic_initialize(instance, base_dir=None):
            instance.metadata["name"] = candidate_name
            return original_initialize(instance, base_dir=base_dir)

        def fail_validation(_instance):
            raise OSError("synthetic new-session validation failure")

        def run_new_action(
            dialog: ExperimentDesignDialog,
            *,
            action_id: str,
            choice: str,
            expect_resume_prompt: bool,
            inject_validation_failure: bool = False,
            milestone: str,
        ) -> dict[str, Any]:
            before = session_state(dialog)
            prompt_state: dict[str, Any] = {
                "resume": None,
                "failure": None,
                "error": None,
            }
            handled: set[int] = set()
            prompt_timer = QtCore.QTimer(self.app)
            prompt_timer.setInterval(5)

            def inspect_prompt() -> None:
                widget = self.app.activeModalWidget()
                if (
                    not isinstance(widget, QtWidgets.QMessageBox)
                    or id(widget) in handled
                ):
                    return
                handled.add(id(widget))
                try:
                    title = widget.windowTitle()
                    if title == "Start New Experiment?":
                        if not expect_resume_prompt:
                            raise RuntimeError(
                                "idle New Experiment unexpectedly requested resume confirmation"
                            )
                        buttons = {
                            button.text().replace("&", ""): button
                            for button in widget.buttons()
                        }
                        target = buttons.get(choice)
                        if target is None:
                            raise RuntimeError(
                                f"resume confirmation lacks {choice!r}: {sorted(buttons)}"
                            )
                        prompt_state["resume"] = record_dialog(widget, choice)
                        capture_milestone(
                            self.context,
                            milestone + "_prompt",
                            evidence=dict(prompt_state["resume"]),
                            widget=widget,
                        )
                        self.click(target)
                        return
                    if title == "Cannot start new experiment":
                        if not inject_validation_failure:
                            raise RuntimeError(
                                "unexpected New Experiment backend failure warning"
                            )
                        prompt_state["failure"] = record_dialog(widget, "OK")
                        capture_milestone(
                            self.context,
                            "new_session_validation_failure",
                            evidence=dict(prompt_state["failure"]),
                            widget=widget,
                        )
                        button = widget.button(
                            QtWidgets.QMessageBox.StandardButton.Ok
                        )
                        if button is None:
                            raise RuntimeError("failure warning lacks an OK button")
                        self.click(button)
                        return
                    raise RuntimeError(
                        f"unexpected New Experiment message box: {title!r}"
                    )
                except BaseException as exc:
                    prompt_state["error"] = exc
                    widget.reject()

            prompt_timer.timeout.connect(inspect_prompt)

            def operation() -> Mapping[str, Any]:
                prompt_timer.start()
                try:
                    with ExitStack() as stack:
                        if choice == "Start New Experiment":
                            stack.enter_context(
                                patch.object(
                                    model_module.ExperimentModel,
                                    "initialize_new_experiment_session",
                                    deterministic_initialize,
                                )
                            )
                        if inject_validation_failure:
                            stack.enter_context(
                                patch.object(
                                    model_module.ExperimentModel,
                                    "_validate_new_experiment_session_files",
                                    fail_validation,
                                )
                            )
                        self.click(dialog.new_btn)
                finally:
                    prompt_timer.stop()
                    prompt_timer.deleteLater()
                if prompt_state["error"] is not None:
                    raise prompt_state["error"]
                if expect_resume_prompt and prompt_state["resume"] is None:
                    raise RuntimeError("resume confirmation was not observed")
                if not expect_resume_prompt and prompt_state["resume"] is not None:
                    raise RuntimeError("idle reset displayed a resume confirmation")
                if inject_validation_failure and prompt_state["failure"] is None:
                    raise RuntimeError("injected validation failure warning was not observed")
                after = session_state(dialog)
                evidence = {
                    "before": before,
                    "after": after,
                    "resume_prompt": prompt_state["resume"],
                    "failure_warning": prompt_state["failure"],
                    "failed_candidate_exists": (
                        experiments_root / failed_candidate_name
                    ).exists(),
                    "source_hashes_after": file_hashes(source_dir),
                }
                capture_milestone(
                    self.context,
                    milestone,
                    evidence={
                        "array_state": after["array_state"],
                        "experiment_name": after["experiment_name"],
                        "load_signal_count": after["load_signal_count"],
                    },
                    widget=dialog,
                )
                return evidence

            expected = [("Experiment Design (v2)", "ExperimentDesignDialog")]
            if expect_resume_prompt:
                expected.append(("Start New Experiment?", "QMessageBox"))
            if inject_validation_failure:
                expected.append(("Cannot start new experiment", "QMessageBox"))
            with _expected_dialogs(self.app, *expected):
                return self.action_runner(
                    action_id,
                    operation,
                    allowed_dialogs=(dialog,),
                )["evidence"]

        driver_timer = QtCore.QTimer(self.app)
        driver_timer.setInterval(5)

        def drive_editor() -> None:
            if state["entered"]:
                return
            active = self.app.activeModalWidget()
            if not isinstance(active, ExperimentDesignDialog):
                return
            state["entered"] = True
            driver_timer.stop()
            dialog = active
            state["dialog"] = dialog
            try:
                if not dialog.advanced_settings_toggle.isChecked():
                    self.click(dialog.advanced_settings_toggle)
                preferences = {
                    "auto_update": bool(dialog.auto_update_chk.isChecked()),
                    "advanced_visible": bool(
                        dialog.advanced_settings_panel.isVisible()
                    ),
                }
                opened = self.action_runner(
                    "editor.open_resume_ready_via_ui",
                    lambda: session_state(dialog),
                    allowed_dialogs=(dialog,),
                )["evidence"]
                capture_milestone(
                    self.context,
                    "resume_ready_editor",
                    evidence={
                        "array_state": opened["array_state"],
                        "experiment_name": opened["experiment_name"],
                    },
                    widget=dialog,
                )
                cancelled = run_new_action(
                    dialog,
                    action_id="editor.new_experiment_cancel_via_ui",
                    choice="Cancel",
                    expect_resume_prompt=True,
                    milestone="new_session_cancelled",
                )
                failed = run_new_action(
                    dialog,
                    action_id="editor.new_experiment_fail_validation_via_ui",
                    choice="Start New Experiment",
                    expect_resume_prompt=True,
                    inject_validation_failure=True,
                    milestone="new_session_failure_preserved",
                )
                resumed = run_new_action(
                    dialog,
                    action_id="editor.new_experiment_accept_via_ui",
                    choice="Start New Experiment",
                    expect_resume_prompt=True,
                    milestone="new_session_resume_created",
                )
                resume_dir = experiments_root / resume_success_name
                resume_hashes_before_idle = file_hashes(resume_dir)
                idle = run_new_action(
                    dialog,
                    action_id="editor.new_experiment_idle_via_ui",
                    choice="Start New Experiment",
                    expect_resume_prompt=False,
                    milestone="new_session_idle_created",
                )
                state["evidence"] = {
                    "preferences": preferences,
                    "opened": opened,
                    "cancelled": cancelled,
                    "failed": failed,
                    "resumed": resumed,
                    "idle": idle,
                    "source_hashes_final": file_hashes(source_dir),
                    "resume_hashes_before_idle": resume_hashes_before_idle,
                    "resume_hashes_after_idle": file_hashes(resume_dir),
                    "load_signal_count": len(load_events),
                    "generation_signal_count": len(generation_events),
                    "expected_names": {
                        "failed": failed_candidate_name,
                        "resume": resume_success_name,
                        "idle": idle_success_name,
                    },
                }
                state["finished"] = True
            except BaseException as exc:
                state["error"] = exc
            finally:
                dialog._allow_close_without_prompt = True
                dialog.reject()

        driver_timer.timeout.connect(drive_editor)
        button = self.view.well_plate_widget.design_experiment_button
        try:
            driver_timer.start()
            with _expected_dialogs(
                self.app,
                ("Experiment Design (v2)", "ExperimentDesignDialog"),
            ):
                self.click(button)
        finally:
            driver_timer.stop()
            driver_timer.deleteLater()
            try:
                self.context.model.experiment_loaded.disconnect(load_slot)
            except (RuntimeError, TypeError):
                pass
            try:
                self.context.experiment_model.experiment_generated.disconnect(
                    generation_slot
                )
            except (RuntimeError, TypeError):
                pass
        if state["error"] is not None:
            raise state["error"]
        if not state["entered"] or not state["finished"]:
            raise RuntimeError("New Experiment SIL editor sequence did not finish")
        return dict(state["evidence"])


def inspect_editor_lock_controls(dialog: Any) -> dict[str, Any]:
    """Return the post-start editor control matrix used by the SIL boundary."""

    def state(widget: Any) -> dict[str, Any]:
        read_only = bool(widget.isReadOnly()) if hasattr(widget, "isReadOnly") else None
        return {"enabled": bool(widget.isEnabled()), "read_only": read_only}

    names = (
        "exp_name_edit", "rep_spin", "v_spin", "final_v_spin",
        "volume_tolerance_spin", "plate_format_combo", "well_selection_btn",
        "add_reagent_btn", "run_btn", "save_btn", "finish_btn",
    )
    controls = {name: state(getattr(dialog, name)) for name in names}
    reagent_controls = []
    for row in range(dialog.reagent_table.rowCount()):
        for column in range(dialog.reagent_table.columnCount()):
            widget = dialog.reagent_table.cellWidget(row, column)
            if widget is not None and not isinstance(widget, QtWidgets.QLabel):
                reagent_controls.append({"row": row, "column": column, **state(widget)})
    items_locked = all(
        (not item["enabled"]) or item["read_only"] is True
        for item in reagent_controls
    )
    controls["reagent_table"] = {
        "enabled": bool(dialog.reagent_table.isEnabled()), "read_only": None,
        "all_items_locked": items_locked, "items": reagent_controls,
    }
    locked = items_locked and all(
        (not item["enabled"]) or item["read_only"] is True
        for name, item in controls.items() if name != "reagent_table"
    )
    banner = getattr(dialog, "lifecycle_banner", None)
    banner_text = str(banner.text() or "") if banner is not None else ""
    banner_visible = bool(banner is not None and not banner.isHidden())
    guidance = (banner_visible and "copy" in banner_text.casefold()
                and any(word in banner_text.casefold() for word in ("locked", "read-only")))
    return {
        "controls": controls, "all_mutating_controls_locked": locked,
        "editable_copy_enabled": bool(dialog.duplicate_btn.isEnabled()),
        "status_text": str(dialog.status_lbl.text() or ""),
        "banner_visible": banner_visible, "banner_text": banner_text,
        "action_label": str(dialog.finish_btn.text() or ""),
        "actionable_lock_guidance": guidance,
    }

def _drive_editor_post_start_lock_and_copy(
    context,
    *,
    source_dir: Path,
    source_name: str,
    copy_name: str,
    copy_tolerance_nl: float,
    action_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prove the active editor is locked, then create and finalize a copy."""

    if context.app is None or context.qt_core is None or context.view is None:
        raise RuntimeError("editor automation requires a launched Qt application")

    from PySide6 import QtTest, QtWidgets
    from View import ExperimentDesignDialog
    from tools.virtual_workflows.actions import (
        ScenarioActionError, _ensure_editor_deadline, _qt_replace_text,
        _qt_set_spin_value, _expected_editor_progress_dialog,
        _wait_for_editor_progress_dialogs,
        capture_failure_screenshot, capture_milestone, execute_action,
    )

    QtCore = context.qt_core
    button = context.view.well_plate_widget.design_experiment_button
    if not button.isEnabled():
        raise ScenarioActionError(
            "editor.inspect_active_lock_via_ui",
            "Experiment Editor button is disabled",
            stage="precondition",
        )

    state: dict[str, Any] = dict(
        entered=False, finished=False, error=None, dialog=None,
        lock_matrix={}, in_place_rejection={}, copy_before_finalize={},
        copy_name_dialog={},
    )
    driver_timer = QtCore.QTimer(context.app)
    driver_timer.setInterval(5)

    def run_action(
        action_id: str,
        operation: Callable[[], Mapping[str, Any] | None],
        *,
        precondition=None,
    ) -> dict[str, Any]:
        if action_runner is not None:
            dialog = state.get("dialog")
            allowed_dialogs = ((dialog,) if isinstance(dialog, QtWidgets.QDialog)
                               and dialog.isVisible() else ())
            return action_runner(
                action_id, operation, precondition=precondition,
                allowed_dialogs=allowed_dialogs,
            )
        return execute_action(context, action_id, operation,
                              precondition=precondition)

    def click(widget: Any) -> None:
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)
        context.app.processEvents()

    def drive_copy_modals() -> None:
        modal = context.app.activeModalWidget()
        try:
            if modal is None or modal is state["dialog"]:
                return
            if isinstance(modal, QtWidgets.QFileDialog):
                raise RuntimeError(
                    "unexpected source QFileDialog while creating editable copy"
                )
            if isinstance(modal, QtWidgets.QInputDialog):
                if modal.windowTitle() != "Create Editable Copy":
                    raise RuntimeError(
                        f"unexpected input dialog title: {modal.windowTitle()!r}"
                    )
                line_edit = modal.findChild(QtWidgets.QLineEdit)
                if line_edit is None:
                    raise RuntimeError("copy-name dialog has no text control")
                state["copy_name_dialog"] = {
                    "source_auto_selected": str(
                        Path(
                            state["dialog"].model.experiment_dir_path
                        ).resolve()
                    ),
                    "source_label": str(modal.labelText() or ""),
                    "dialog_width_px": int(modal.width()),
                    "dialog_minimum_width_px": int(modal.minimumWidth()),
                    "name_field_width_px": int(line_edit.width()),
                    "name_field_minimum_width_px": int(
                        line_edit.minimumWidth()
                    ),
                }
                if (
                    int(modal.width()) < 640
                    or int(modal.minimumWidth()) < 640
                    or int(line_edit.minimumWidth()) < 480
                ):
                    raise RuntimeError(
                        "copy-name dialog did not meet the required width: "
                        f"{state['copy_name_dialog']}"
                    )
                _qt_replace_text(QtCore, QtTest, line_edit, copy_name)
                button_box = modal.findChild(QtWidgets.QDialogButtonBox)
                accept = (
                    button_box.button(QtWidgets.QDialogButtonBox.Ok)
                    if button_box is not None
                    else None
                )
                if accept is None:
                    raise RuntimeError("copy-name dialog has no OK button")
                click(accept)
                return
            title = modal.windowTitle() if modal is not None else None
            raise RuntimeError(
                "unexpected modal while creating editable copy: "
                f"{type(modal).__name__ if modal is not None else None} "
                f"{title!r}"
            )
        except BaseException as exc:
            state["error"] = exc
            if isinstance(modal, QtWidgets.QDialog) and modal.isVisible():
                modal.reject()

    def run_driver() -> None:
        if state["entered"]:
            return
        state["entered"] = True
        driver_timer.stop()
        active = context.app.activeModalWidget()
        try:
            if not isinstance(active, ExperimentDesignDialog):
                title = active.windowTitle() if active is not None else None
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                run_action(
                    "editor.inspect_active_lock_via_ui",
                    lambda: {},
                    precondition=lambda: (
                        False,
                        "unexpected active modal while opening locked editor",
                        {
                            "modal_type": (
                                type(active).__name__
                                if active is not None
                                else None
                            ),
                            "modal_title": title,
                        },
                    ),
                )
            dialog = active
            state["dialog"] = dialog

            def inspect_lock() -> Mapping[str, Any]:
                _ensure_editor_deadline(
                    context,
                    "editor.inspect_active_lock_via_ui",
                    "locked editor inspection",
                )
                matrix = inspect_editor_lock_controls(dialog)
                state["lock_matrix"] = matrix
                if dialog.exp_name_edit.text() != source_name:
                    raise RuntimeError(
                        "locked editor did not load the source experiment"
                    )
                failed = [
                    name
                    for name, passed in (
                        (
                            "all_mutating_controls_locked",
                            matrix["all_mutating_controls_locked"],
                        ),
                        (
                            "editable_copy_enabled",
                            matrix["editable_copy_enabled"],
                        ),
                        (
                            "actionable_lock_guidance",
                            matrix["actionable_lock_guidance"],
                        ),
                        (
                            "visible_lock_banner",
                            matrix["banner_visible"],
                        ),
                        (
                            "experiment_loaded_label",
                            matrix["action_label"] == "Experiment Loaded",
                        ),
                    )
                    if not passed
                ]
                if failed:
                    raise ScenarioActionError(
                        "editor.inspect_active_lock_via_ui",
                        "active zero-progress editor lock boundary failed: "
                        + ", ".join(failed),
                        stage="operation",
                        evidence={
                            "failed_checks": failed,
                            "control_matrix": matrix,
                        },
                    )
                return matrix

            run_action("editor.inspect_active_lock_via_ui", inspect_lock)
            capture_milestone(
                context, "locked_editor_opened",
                evidence=state["lock_matrix"], widget=dialog,
            )

            def reject_in_place() -> Mapping[str, Any]:
                name_before = dialog.exp_name_edit.text()
                result_before = int(dialog.result())
                _qt_replace_text(
                    QtCore,
                    QtTest,
                    dialog.exp_name_edit,
                    f"{source_name}-forbidden",
                )
                click(dialog.finish_btn)
                if dialog.exp_name_edit.text() != name_before:
                    raise RuntimeError("locked name control accepted an edit")
                if int(dialog.result()) != result_before or not dialog.isVisible():
                    raise RuntimeError(
                        "disabled Experiment Loaded action closed the locked editor"
                    )
                evidence = {"name_unchanged": True, "finish_rejected": True}
                state["in_place_rejection"] = evidence
                return evidence

            run_action("editor.reject_in_place_edit_via_ui", reject_in_place)
            capture_milestone(
                context, "in_place_edit_rejected",
                evidence={"experiment_name": source_name}, widget=dialog,
            )

            copy_modal_timer = QtCore.QTimer(dialog)
            copy_modal_timer.setInterval(5)
            copy_modal_timer.timeout.connect(drive_copy_modals)

            def create_copy() -> Mapping[str, Any]:
                expected_dir = (source_dir.parent / copy_name).resolve()
                copy_modal_timer.start()
                try:
                    with _expected_dialogs(
                        context.app,
                        (
                            "Create Editable Copy",
                            "EditableCopyNameDialog",
                        ),
                    ):
                        interaction = _click_button_with_bounded_retry(
                            context,
                            dialog.duplicate_btn,
                            postcondition=lambda: (
                                state["error"] is not None
                                or (
                                    bool(state["copy_name_dialog"])
                                    and Path(
                                        dialog.model.experiment_dir_path
                                    ).resolve()
                                    == expected_dir
                                )
                            ),
                            description="editable-copy button",
                        )
                finally:
                    copy_modal_timer.stop()
                    copy_modal_timer.deleteLater()
                if state["error"] is not None:
                    raise state["error"]
                name_dialog_evidence = dict(state["copy_name_dialog"])
                if not name_dialog_evidence:
                    raise RuntimeError("copy-name dialog evidence was not captured")
                if (
                    Path(name_dialog_evidence["source_auto_selected"]).resolve()
                    != source_dir.resolve()
                    or source_name not in name_dialog_evidence["source_label"]
                ):
                    raise RuntimeError(
                        "copy-name dialog did not identify the current source"
                    )
                current_dir = Path(
                    dialog.model.experiment_dir_path
                ).resolve()
                if current_dir != expected_dir:
                    raise ScenarioActionError(
                        "editor.create_editable_copy_via_ui",
                        f"editable copy loaded {current_dir}; "
                        f"expected {expected_dir}",
                        stage="operation",
                        evidence={
                            "current_dir": str(current_dir),
                            "expected_dir": str(expected_dir),
                            "expected_dir_exists": expected_dir.is_dir(),
                            "dialog_status": dialog.status_lbl.text(),
                        },
                    )
                matrix = inspect_editor_lock_controls(dialog)
                editable = (
                    dialog.exp_name_edit.isEnabled()
                    and not dialog.exp_name_edit.isReadOnly()
                    and dialog.volume_tolerance_spin.isEnabled()
                    and dialog.run_btn.isEnabled()
                    and dialog.finish_btn.isEnabled()
                    and dialog.finish_btn.text() == "Finalize Experiment"
                )
                if not editable:
                    raise RuntimeError("editable copy controls remained locked")
                state["copy_before_finalize"] = {
                    "experiment_dir": str(current_dir),
                    "experiment_name": dialog.exp_name_edit.text(),
                    "destination": str(expected_dir),
                    "source_auto_selected": str(source_dir.resolve()),
                    "copy_name_dialog": dict(state["copy_name_dialog"]),
                    "button_interaction": interaction,
                    "action_label": str(dialog.finish_btn.text() or ""),
                    "controls_editable": editable,
                    "control_matrix": matrix,
                }
                return state["copy_before_finalize"]

            run_action("editor.create_editable_copy_via_ui", create_copy)
            capture_milestone(
                context, "editable_copy_created",
                evidence=state["copy_before_finalize"], widget=dialog,
            )

            def edit_copy() -> Mapping[str, Any]:
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.volume_tolerance_spin,
                    copy_tolerance_nl,
                )
                if not math.isclose(
                    float(dialog.volume_tolerance_spin.value()),
                    float(copy_tolerance_nl),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ):
                    raise RuntimeError("copy tolerance edit was not retained")
                with _expected_editor_progress_dialog(context):
                    click(dialog.run_btn)
                    _wait_for_editor_progress_dialogs(
                        context,
                        QtTest,
                        "editor.edit_copy_via_ui",
                    )
                if dialog._design_optimization_dirty:
                    raise RuntimeError("copy design remained dirty")
                return {
                    "printed_volume_tolerance_nL": (
                        dialog.volume_tolerance_spin.value()
                    ),
                }

            run_action("editor.edit_copy_via_ui", edit_copy)
            capture_milestone(
                context, "copy_edited",
                evidence={"printed_volume_tolerance_nL": copy_tolerance_nl},
                widget=dialog,
            )

            def finalize_copy() -> Mapping[str, Any]:
                if dialog.finish_btn.text() != "Finalize Experiment":
                    raise RuntimeError(
                        "editable copy did not expose Finalize Experiment"
                    )
                click(dialog.finish_btn)
                if dialog.result() != QtWidgets.QDialog.DialogCode.Accepted:
                    raise RuntimeError(
                        "copy editor did not accept after Finalize Experiment"
                    )
                return {
                    "dialog_result": int(dialog.result()),
                    "apply_requested": bool(dialog._apply_requested),
                    "action_label": "Finalize Experiment",
                }

            run_action("editor.finalize_copy_via_ui", finalize_copy)
            capture_milestone(
                context, "copy_finalized",
                evidence={"experiment_name": copy_name}, widget=dialog,
            )
            state["finished"] = True
        except BaseException as exc:
            state["error"] = exc
            try:
                if "failure" not in context.screenshots:
                    capture_failure_screenshot(context, widget=active)
            except Exception:
                pass
            if isinstance(active, QtWidgets.QDialog) and active.isVisible():
                active.reject()

    driver_timer.timeout.connect(run_driver)
    driver_timer.start()
    try:
        QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
    finally:
        driver_timer.stop()
        driver_timer.deleteLater()
    if state["error"] is not None:
        raise state["error"]
    if not state["entered"]:
        raise ScenarioActionError(
            "editor.inspect_active_lock_via_ui",
            "the locked editor did not open",
            stage="timeout",
        )
    if not state["finished"]:
        raise ScenarioActionError(
            "editor.finalize_copy_via_ui",
            "the editable copy did not finish",
            stage="operation",
        )
    return {
        "lock_matrix": state["lock_matrix"],
        "in_place_rejection": state["in_place_rejection"],
        "copy_before_finalize": state["copy_before_finalize"],
        "copy_finalized": True,
    }



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
        state: dict[str, Any] = {
            "error": None,
            "loaded": None,
            "activated": None,
        }

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
                if modal is None:
                    if self.context.deadline.remaining_seconds() <= 0:
                        raise RuntimeError(
                            f"{purpose} folder dialog deadline expired"
                        )
                    QtCore.QTimer.singleShot(5, lambda: choose_directory(editor))
                    return
                if not isinstance(modal, QtWidgets.QFileDialog):
                    raise RuntimeError(
                        f"unexpected modal while selecting {purpose} folder: "
                        f"{type(modal).__name__} {modal.windowTitle()!r}"
                    )
                if modal.windowTitle() != "Select Experiment Folder":
                    raise RuntimeError(
                        f"unexpected file dialog title: {modal.windowTitle()!r}"
                    )
                modal.setDirectory(str(directory.parent))
                self.context.pump_events()
                view = modal.findChild(QtWidgets.QTreeView, "treeView")
                if view is None or not view.isVisible():
                    raise RuntimeError(
                        f"{purpose} folder dialog has no visible directory view"
                    )

                def target_index():
                    model = view.model()
                    parent = view.rootIndex()
                    for row in range(model.rowCount(parent)):
                        index = model.index(row, 0, parent)
                        if str(index.data() or "") == directory.name:
                            return index
                    return QtCore.QModelIndex()

                self.wait_until(
                    lambda: target_index().isValid(),
                    f"{purpose} folder row",
                    timeout_seconds=5.0,
                )
                index = target_index()
                view.scrollTo(index)
                self.context.pump_events()
                rect = view.visualRect(index)
                if not rect.isValid():
                    raise RuntimeError(
                        f"{purpose} folder row has invalid geometry"
                    )
                QtTest.QTest.mouseClick(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=rect.center(),
                )
                self.context.pump_events()
                selected = [
                    Path(item).resolve() for item in modal.selectedFiles()
                ]
                if directory not in selected:
                    raise RuntimeError(
                        f"{purpose} folder selection retained {selected!r}; "
                        f"expected {directory}"
                    )
                box = modal.findChild(QtWidgets.QDialogButtonBox)
                accept = box.button(QtWidgets.QDialogButtonBox.Open) if box else None
                if accept is None and box is not None:
                    accept = box.button(QtWidgets.QDialogButtonBox.Ok)
                if accept is None:
                    raise RuntimeError(f"{purpose} folder dialog has no accept button")
                if not accept.isVisible() or not accept.isEnabled():
                    raise RuntimeError(
                        f"{purpose} folder accept control is unavailable"
                    )
                accept.setFocus()
                QtTest.QTest.mouseClick(
                    accept, QtCore.Qt.MouseButton.LeftButton
                )
            except BaseException as exc:
                fail(exc, modal)

        def drive_editor() -> None:
            modal = self.app.activeModalWidget()
            try:
                if self.context.deadline.remaining_seconds() <= 0:
                    raise RuntimeError(f"{purpose} reload deadline expired")
                if modal is None:
                    QtCore.QTimer.singleShot(5, drive_editor)
                    return
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
        with _expected_dialogs(
            self.app,
            ("Experiment Design (v2)", "ExperimentDesignDialog"),
            ("Select Experiment Folder", "QFileDialog"),
        ):
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
        expected_eligibility_status: str = "ready_to_resume",
        expected_array_state: str = "resume_ready",
        loaded_milestone_name: str = "session_2_loaded",
    ) -> dict[str, Any]:
        """Load and activate one authoritative execution through the real editor."""

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
                and f"{loaded_milestone_name}_failed" not in self.context.screenshots
            ):
                try:
                    capture_milestone(
                        self.context,
                        f"{loaded_milestone_name}_failed",
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
            eligibility_check = f"eligibility_{expected_eligibility_status}"
            checks = {
                "name_matches": dialog.exp_name_edit.text() == expected_name,
                "action_is_load_experiment": dialog.finish_btn.text()
                == "Load Experiment",
                "finish_enabled": bool(dialog.finish_btn.isEnabled()),
                eligibility_check: eligibility.get("status")
                == expected_eligibility_status,
                "runtime_inactive": not runtime_active,
                "read_only_guidance": "ready to load" in status_text.casefold()
                and "load experiment" in status_text.casefold(),
                "visible_lock_banner": not dialog.lifecycle_banner.isHidden()
                and "load experiment" in banner_text.casefold()
                and "will not start or resume automatically"
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
            if dialog.finish_btn.text() != "Load Experiment":
                raise RuntimeError("saved experiment did not expose Load Experiment")
            self.click(dialog.finish_btn)
            if dialog.isVisible():
                raise RuntimeError("Load Experiment did not close the editor")
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
                or eligibility.get("status") != expected_eligibility_status
                or array_state != expected_array_state
            ):
                raise RuntimeError(
                    "authoritative activation did not reach the expected "
                    f"{expected_eligibility_status}/{expected_array_state} boundary"
                )
            return {
                "eligibility": eligibility,
                "runtime_active": runtime_active,
                "array_state": array_state,
                "action_label": "Load Experiment",
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
                self.context, loaded_milestone_name, evidence=evidence, widget=dialog
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

    def load_rejected_authoritative_execution(
        self,
        experiment_dir,
        *,
        case,
    ) -> dict[str, Any]:
        """Inspect one prelaunch-faulted bundle and attempt its locked action."""

        from pathlib import Path

        from tools.virtual_workflows.actions import (
            capture_execution_preflight_boundary,
            capture_milestone,
            execute_action,
        )

        directory = Path(experiment_dir).resolve()

        def loaded(dialog) -> Mapping[str, Any]:
            model = self.context.experiment_model
            bundle = model.get_authoritative_execution_bundle()
            if bundle is None:
                raise RuntimeError("authoritative inspection produced no bundle")
            eligibility = model.get_execution_resume_eligibility() or {}
            issues = [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "context": dict(issue.context),
                }
                for issue in bundle.issues
            ]
            raw_code = issues[0]["code"] if issues else str(eligibility.get("status") or "")
            raw_message = issues[0]["message"] if issues else str(eligibility.get("reason") or "")
            normalized_message = raw_message
            if case.case_id == "incomplete_authoritative_bundle_invalid":
                expected_suffix = str(directory / "progress.json")
                portable_raw = raw_message.replace("\\\\", "\\")
                if "No such file or directory" not in raw_message or expected_suffix not in portable_raw:
                    raise RuntimeError("missing progress classification did not identify the exact copied path")
                normalized_message = case.expected.message
            technical_message = str(case.setup["technical_message"])
            if raw_code != case.expected.code or normalized_message != technical_message:
                raise RuntimeError(
                    "authoritative classification drifted: "
                    f"code={raw_code!r}, message={raw_message!r}"
                )
            status_text = str(dialog.status_lbl.text() or "")
            banner_text = str(dialog.lifecycle_banner.text() or "")
            action_label = str(dialog.finish_btn.text() or "")
            operator_message = dialog._user_facing_eligibility_reason(
                eligibility,
                plan_state=dialog._execution_plan_state_text(model),
            )
            if (
                action_label != "Experiment Locked"
                or dialog.finish_btn.isEnabled()
                or model.is_authoritative_execution_runtime_active()
                or self.context.controller.get_array_run_state() != "idle"
                or operator_message not in status_text
                or operator_message not in banner_text
                or raw_message in status_text
                or raw_message in banner_text
            ):
                raise RuntimeError("rejected authoritative editor state is not exact")
            evidence = {
                "classification": case.expected.classification,
                "code": raw_code,
                "message": normalized_message,
                "raw_message": raw_message,
                "issues": issues,
                "eligibility": dict(eligibility),
                "status_text": status_text,
                "banner_text": banner_text,
                "action_label": action_label,
                "action_enabled": bool(dialog.finish_btn.isEnabled()),
                "runtime_active": bool(model.is_authoritative_execution_runtime_active()),
                "experiment_dir": str(directory),
            }
            execute_action(
                self.context,
                case.operator_action_id,
                lambda: evidence,
            )
            before = capture_execution_preflight_boundary(
                self.context,
                identity_keys=case.identity_keys,
                workflow_state=case.expected.workflow_state,
            )

            def attempt_locked_action() -> Mapping[str, Any]:
                QtTest.QTest.mouseClick(
                    dialog.finish_btn,
                    QtCore.Qt.MouseButton.LeftButton,
                )
                self.context.app.processEvents()
                if not dialog.isVisible() or dialog.finish_btn.isEnabled():
                    raise RuntimeError("locked activation action changed state")
                return {
                    "selected_control": str(dialog.finish_btn.text() or ""),
                    "enabled": bool(dialog.finish_btn.isEnabled()),
                }

            attempt = execute_action(
                self.context,
                "experiment.attempt_locked_activation_via_ui",
                attempt_locked_action,
            )
            after = capture_execution_preflight_boundary(
                self.context,
                identity_keys=case.identity_keys,
                workflow_state=case.expected.workflow_state,
            )
            capture_milestone(
                self.context,
                "rejection_observed",
                evidence={
                    "case_id": case.case_id,
                    "code": raw_code,
                    "message": raw_message,
                    "action_label": action_label,
                    "action_enabled": False,
                },
                widget=dialog,
            )
            dialog.reject()
            return {
                "classification": evidence,
                "attempt": dict(attempt),
                "before": before,
                "after": after,
                "ui": {
                    "title": None,
                    "message": operator_message,
                    "raw_message": raw_message,
                    "selected_control": action_label,
                    "status_text": status_text,
                    "banner_text": banner_text,
                },
            }

        return self._drive_directory_load(
            directory,
            purpose="authoritative persistence safeguard",
            on_loaded=loaded,
        )["loaded"]

    def load_prepared_design(
        self,
        experiment_dir,
        *,
        expected_name: str,
        expected_plan_id: str,
        expected_plan_revision: int,
        capture_milestone_name: str | None = None,
    ) -> dict[str, Any]:
        from tools.virtual_workflows.actions import capture_milestone

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
                if capture_milestone_name is not None:
                    capture_milestone(
                        self.context,
                        capture_milestone_name,
                        evidence=result,
                        widget=dialog,
                    )
                QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
                if dialog.isVisible():
                    raise RuntimeError("prepared inspection editor did not close")
                return result

        return self._drive_directory_load(
            directory, purpose="prepared", on_loaded=inspect_loaded
        )["loaded"]

    def inspect_same_session_completed_execution(
        self,
        *,
        expected_name: str,
        action_runner: Callable[..., dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Open and display the current completed execution in the live session."""

        from View import ExperimentDesignDialog
        from tools.virtual_workflows.actions import execute_action

        button = self.view.well_plate_widget.design_experiment_button
        if not button.isVisible() or not button.isEnabled():
            raise RuntimeError("Experiment Editor control is not visible and enabled")

        state: dict[str, Any] = {
            "error": None,
            "direct_launch": False,
            "unexpected_launch_dialog": {},
            "editor": None,
            "inspection": None,
        }
        timer = QtCore.QTimer(self.app)
        timer.setInterval(5)

        def run_action(
            action_id: str,
            operation: Callable[[], Mapping[str, Any] | None],
            *,
            allowed_dialogs: tuple[Any, ...] = (),
        ) -> dict[str, Any]:
            if action_runner is not None:
                return action_runner(
                    action_id,
                    operation,
                    allowed_dialogs=allowed_dialogs,
                )
            return execute_action(self.context, action_id, operation)

        def dispatch_snapshot() -> dict[str, int]:
            instrumentation = getattr(self.context, "instrumentation", None)
            machine = getattr(self.context, "machine", None)
            return {
                "intent_begins": len(
                    getattr(instrumentation, "intent_begins", ()) or ()
                ),
                "intent_attachments": len(
                    getattr(instrumentation, "intent_attachments", ()) or ()
                ),
                "intent_completions": len(
                    getattr(instrumentation, "intent_completions", ()) or ()
                ),
                "simulator_dispenses": len(
                    getattr(instrumentation, "simulator_dispenses", ()) or ()
                ),
                "machine_commands": len(
                    getattr(machine, "command_event_history", ()) or ()
                ),
            }

        def inspect_and_close(dialog) -> Mapping[str, Any]:
            plan = self.context.experiment_model.get_execution_plan_snapshot()
            eligibility = (
                self.context.experiment_model.get_execution_resume_eligibility()
                or {}
            )
            progress_data = self.context.experiment_model.progress_data
            status_text = str(dialog.status_lbl.text() or "")
            banner_text = str(dialog.lifecycle_banner.text() or "")
            initial_checks = {
                "direct_read_only_launch": bool(state["direct_launch"]),
                "saved_progress_prompt_absent": not bool(
                    state["unexpected_launch_dialog"]
                ),
                "name_matches": dialog.exp_name_edit.text() == expected_name,
                "plan_completed": str(plan.state.value) == "completed",
                "live_runtime_assignments_present": any(
                    well.get_assigned_reaction() is not None
                    for well in self.context.model.well_plate.get_all_wells()
                ),
                "action_is_view_completed": dialog.finish_btn.text()
                == "View Completed Experiment",
                "action_enabled": bool(dialog.finish_btn.isEnabled()),
                "read_only_guidance": (
                    "experiment complete" in status_text.casefold()
                    and "view completed experiment" in status_text.casefold()
                )
                or (
                    "saved printing progress" in status_text.casefold()
                    and "view-only" in status_text.casefold()
                ),
                "visible_lock_banner": not dialog.lifecycle_banner.isHidden()
                and "locked and read-only" in banner_text.casefold(),
                "eligibility_terminal_analysis_only": eligibility.get("status")
                == "analysis_only",
            }
            dispatch_before = dispatch_snapshot()
            unexpected_before = len(self.context.unexpected_dialogs)
            errors_before = len(self.context.errors)
            modal_failure: dict[str, Any] = {}
            modal_watch = QtCore.QTimer(self.app)
            modal_watch.setInterval(5)

            def reject_unexpected_result_dialog() -> None:
                modal = self.app.activeModalWidget()
                if modal is None or modal is dialog:
                    return
                modal_failure.update(
                    {
                        "type": type(modal).__name__,
                        "title": str(modal.windowTitle() or ""),
                        "text": str(
                            modal.text()
                            if isinstance(modal, QtWidgets.QMessageBox)
                            else ""
                        ),
                    }
                )
                if isinstance(modal, QtWidgets.QDialog) and modal.isVisible():
                    modal.reject()

            modal_watch.timeout.connect(reject_unexpected_result_dialog)
            modal_watch.start()
            try:
                self.click(dialog.finish_btn)
            finally:
                modal_watch.stop()
                modal_watch.deleteLater()
            self.context.pump_events()

            model = self.context.model
            experiment_model = self.context.experiment_model
            well_plate = model.well_plate
            assignments = {
                well.well_id: well.get_assigned_reaction().unique_id
                for well in well_plate.get_all_wells()
                if well.get_assigned_reaction() is not None
            }
            expected_assignments = {
                well.well_id: well.reaction_id for well in plan.wells
            }
            expected_targets = {
                well.well_id: {
                    dispense.stock_id: int(dispense.target_dispenses)
                    for dispense in well.dispenses
                }
                for well in plan.wells
            }
            expected_added = {
                plan_well.well_id: {
                    dispense.stock_id: int(
                        progress_data[plan_well.well_id]["reagents"][
                            dispense.stock_id
                        ].get("added_droplets", 0)
                        or 0
                    )
                    for dispense in plan_well.dispenses
                }
                for plan_well in plan.wells
            }
            displayed_targets: dict[str, dict[str, int]] = {}
            displayed_added: dict[str, dict[str, int]] = {}
            completed_wells = []
            for plan_well in plan.wells:
                reaction = well_plate.get_well(
                    plan_well.well_id
                ).get_assigned_reaction()
                displayed_targets[plan_well.well_id] = {
                    stock_id: int(reagent.target_droplets)
                    for stock_id, reagent in reaction.get_all_reagents().items()
                }
                displayed_added[plan_well.well_id] = {
                    stock_id: int(reagent.added_droplets)
                    for stock_id, reagent in reaction.get_all_reagents().items()
                }
                if reaction.check_all_complete():
                    completed_wells.append(plan_well.well_id)

            plate_widget = self.context.view.well_plate_widget
            calibration_button = (
                self.context.view.pressure_box.calibrate_pressure_button
            )
            projected_eligibility = (
                experiment_model.get_execution_resume_eligibility() or {}
            )
            dispatch_after = dispatch_snapshot()
            checks = {
                **initial_checks,
                "no_result_warning_dialog": not modal_failure,
                "dialog_closed_after_explicit_action": not dialog.isVisible(),
                "display_projection_active": bool(
                    model.is_completed_execution_view_active()
                ),
                "runtime_inactive_after_view": not bool(
                    experiment_model.is_authoritative_execution_runtime_active()
                ),
                "controller_still_idle": self.context.controller.get_array_run_state()
                == "idle",
                "eligibility_still_terminal_analysis_only": (
                    projected_eligibility.get("status") == "analysis_only"
                    and not projected_eligibility.get("can_activate_runtime")
                    and not projected_eligibility.get("can_start_hardware")
                    and not projected_eligibility.get("can_resume_hardware")
                ),
                "plate_identity_exact": (
                    well_plate.get_current_plate_name() == plan.plate.name
                    and well_plate.get_plate_dimensions()
                    == (int(plan.plate.rows), int(plan.plate.columns))
                ),
                "well_assignments_exact": assignments == expected_assignments,
                "targets_exact": displayed_targets == expected_targets,
                "added_progress_exact": displayed_added == expected_added
                and expected_added == expected_targets,
                "all_assigned_wells_complete": set(completed_wells)
                == set(expected_assignments),
                "start_control_disabled": (
                    plate_widget.start_print_array_button.text()
                    == "Experiment Complete"
                    and not plate_widget.start_print_array_button.isEnabled()
                ),
                "stock_prep_calculator_enabled": bool(
                    plate_widget.stock_prep_button.isEnabled()
                ),
                "authoritative_mutation_controls_disabled": not bool(
                    plate_widget.calibration_button.isEnabled()
                ),
                "printer_head_diagnostics_disabled": not bool(
                    calibration_button.isEnabled()
                ),
                "no_machine_or_simulator_dispatch": dispatch_after
                == dispatch_before,
                "no_new_unexpected_dialogs": len(self.context.unexpected_dialogs)
                == unexpected_before,
                "no_new_errors": len(self.context.errors) == errors_before,
            }
            evidence = {
                "checks": checks,
                "failed_checks": [
                    name for name, passed in checks.items() if not passed
                ],
                "launch": {
                    "direct_read_only": bool(state["direct_launch"]),
                    "saved_progress_prompt_absent": not bool(
                        state["unexpected_launch_dialog"]
                    ),
                    "unexpected_dialog": dict(state["unexpected_launch_dialog"]),
                },
                "experiment_name": dialog.exp_name_edit.text(),
                "plan_id": str(plan.plan_id),
                "plan_revision": int(plan.plan_revision),
                "plan_state": str(plan.state.value),
                "eligibility": projected_eligibility,
                "status_text": status_text,
                "banner_text": banner_text,
                "runtime_assignments": assignments,
                "expected_assignments": expected_assignments,
                "displayed_targets": displayed_targets,
                "displayed_added": displayed_added,
                "persisted_added": expected_added,
                "completed_well_ids": sorted(completed_wells),
                "dispatch_before": dispatch_before,
                "dispatch_after": dispatch_after,
                "unexpected_result_dialog": modal_failure,
                "activation_performed": False,
                "display_projection_performed": True,
            }
            if not all(checks.values()):
                raise RuntimeError(
                    "same-session completed projection was not exact: "
                    f"{checks}"
                )
            return evidence

        def drive_modal() -> None:
            modal = self.app.activeModalWidget()
            try:
                if self.context.deadline.remaining_seconds() <= 0:
                    raise RuntimeError(
                        "same-session completed projection deadline expired"
                    )
                if modal is None:
                    return
                if isinstance(modal, QtWidgets.QMessageBox):
                    state["unexpected_launch_dialog"] = {
                        "title": str(modal.windowTitle() or ""),
                        "text": str(modal.text() or ""),
                        "informative_text": str(modal.informativeText() or ""),
                    }
                    raise RuntimeError(
                        "unexpected dialog while directly opening completed editor: "
                        f"{state['unexpected_launch_dialog']}"
                    )
                if not isinstance(modal, ExperimentDesignDialog):
                    raise RuntimeError(
                        "unexpected modal while opening same-session completed "
                        f"editor: {type(modal).__name__} {modal.windowTitle()!r}"
                    )
                if not modal.isVisible() or not modal.finish_btn.isVisible():
                    return
                timer.stop()
                state["direct_launch"] = True
                state["editor"] = run_action(
                    "editor.open_via_ui",
                    lambda: {
                        "window_title": str(modal.windowTitle() or ""),
                        "dialog_visible": bool(modal.isVisible()),
                        "direct_read_only_launch": True,
                        "saved_progress_prompt_absent": not bool(
                            state["unexpected_launch_dialog"]
                        ),
                    },
                    allowed_dialogs=(modal,),
                )["evidence"]
                state["inspection"] = run_action(
                    "experiment.inspect_completed_via_ui",
                    lambda: inspect_and_close(modal),
                    allowed_dialogs=(modal,),
                )["evidence"]
            except BaseException as exc:
                state["error"] = exc
                timer.stop()
                if isinstance(modal, QtWidgets.QDialog) and modal.isVisible():
                    modal.reject()

        timer.timeout.connect(drive_modal)
        timer.start()
        with _expected_dialogs(
            self.app,
            ("Experiment Design (v2)", "ExperimentDesignDialog"),
        ):
            self.click(button)
        timer.stop()
        timer.deleteLater()
        if state["error"] is not None:
            raise state["error"]
        if state["editor"] is None or state["inspection"] is None:
            raise RuntimeError(
                "same-session completed editor inspection did not finish"
            )
        return {
            "editor": dict(state["editor"]),
            "inspection": dict(state["inspection"]),
        }

    def inspect_completed_execution(
        self,
        experiment_dir,
        *,
        expected_name: str,
    ) -> dict[str, Any]:
        """Display one completed execution read-only without runtime activation."""

        from pathlib import Path
        from ExecutionPlan import canonical_sha256
        from tools.virtual_workflows.actions import capture_milestone, execute_action

        directory = Path(experiment_dir).resolve()

        def dispatch_snapshot() -> dict[str, int]:
            instrumentation = getattr(self.context, "instrumentation", None)
            machine = getattr(self.context, "machine", None)
            return {
                "intent_begins": len(
                    getattr(instrumentation, "intent_begins", ()) or ()
                ),
                "intent_attachments": len(
                    getattr(instrumentation, "intent_attachments", ()) or ()
                ),
                "intent_completions": len(
                    getattr(instrumentation, "intent_completions", ()) or ()
                ),
                "simulator_dispenses": len(
                    getattr(instrumentation, "simulator_dispenses", ()) or ()
                ),
                "machine_commands": len(
                    getattr(machine, "command_event_history", ()) or ()
                ),
            }

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
            status_text = str(dialog.status_lbl.text() or "")
            banner_text = str(dialog.lifecycle_banner.text() or "")
            progress_rows = self.context.experiment_model.progress_data.values()
            progress_complete = all(
                int(details.get("added_droplets", 0) or 0)
                == int(details.get("target_droplets", 0) or 0)
                for well in progress_rows
                for details in (well.get("reagents") or {}).values()
            )
            initial_checks = {
                "name_matches": dialog.exp_name_edit.text() == expected_name,
                "path_matches": Path(
                    self.context.experiment_model.experiment_dir_path
                ).resolve() == directory,
                "plan_completed": str(plan.state.value) == "completed",
                "progress_complete": progress_complete,
                "eligibility_terminal_analysis_only": eligibility.get("status")
                == "analysis_only"
                and not bool(eligibility.get("can_activate_runtime"))
                and not bool(eligibility.get("can_start_hardware"))
                and not bool(eligibility.get("can_resume_hardware")),
                "runtime_inactive": not runtime_active,
                "action_is_view_completed": dialog.finish_btn.text()
                == "View Completed Experiment",
                "action_enabled": bool(dialog.finish_btn.isEnabled()),
                "read_only_guidance": "experiment complete" in status_text.casefold()
                and "view completed experiment" in status_text.casefold(),
                "visible_lock_banner": not dialog.lifecycle_banner.isHidden()
                and "locked and read-only" in banner_text.casefold()
                and "printing cannot be started or resumed"
                in banner_text.casefold(),
            }
            if not all(initial_checks.values()):
                raise RuntimeError(
                    "completed execution did not expose its read-only view: "
                    f"{initial_checks}"
                )

            dispatch_before = dispatch_snapshot()
            self.click(dialog.finish_btn)
            if dialog.isVisible():
                raise RuntimeError("View Completed Experiment did not close the editor")
            self.context.pump_events()

            model = self.context.model
            experiment_model = self.context.experiment_model
            well_plate = model.well_plate
            assignments = {
                well.well_id: well.get_assigned_reaction().unique_id
                for well in well_plate.get_all_wells()
                if well.get_assigned_reaction() is not None
            }
            expected_assignments = {
                well.well_id: well.reaction_id for well in plan.wells
            }
            expected_targets = {
                well.well_id: {
                    dispense.stock_id: int(dispense.target_dispenses)
                    for dispense in well.dispenses
                }
                for well in plan.wells
            }
            expected_added = {
                plan_well.well_id: {
                    dispense.stock_id: int(
                        self.context.experiment_model.progress_data[
                            plan_well.well_id
                        ]["reagents"][dispense.stock_id].get(
                            "added_droplets", 0
                        )
                        or 0
                    )
                    for dispense in plan_well.dispenses
                }
                for plan_well in plan.wells
            }
            displayed_targets = {}
            displayed_added = {}
            completed_wells = []
            completed_styles = {}
            plate_widget = self.context.view.well_plate_widget
            for plan_well in plan.wells:
                runtime_well = well_plate.get_well(plan_well.well_id)
                reaction = runtime_well.get_assigned_reaction()
                displayed_targets[plan_well.well_id] = {
                    stock_id: int(reagent.target_droplets)
                    for stock_id, reagent in reaction.get_all_reagents().items()
                }
                displayed_added[plan_well.well_id] = {
                    stock_id: int(reagent.added_droplets)
                    for stock_id, reagent in reaction.get_all_reagents().items()
                }
                if reaction.check_all_complete():
                    completed_wells.append(plan_well.well_id)
                label = plate_widget.well_labels[
                    runtime_well.row_num
                ][runtime_well.col - 1]
                completed_styles[plan_well.well_id] = str(label.styleSheet() or "")

            expected_stock_ids = {stock.stock_id for stock in plan.stocks}
            display_heads = model.get_completed_execution_display_heads()
            display_stock_ids = {head.get_stock_id() for head in display_heads}
            reagent_rack_assignments = [
                index
                for index, slot in enumerate(model.rack_model.slots)
                if getattr(slot, "printer_head", None) is not None
                and not bool(
                    getattr(slot.printer_head, "calibration_chip", False)
                )
            ]
            projected_eligibility = (
                experiment_model.get_execution_resume_eligibility() or {}
            )
            projected_runtime_active = bool(
                experiment_model.is_authoritative_execution_runtime_active()
            )
            array_state = self.context.controller.get_array_run_state()
            start_button = plate_widget.start_print_array_button
            calibration_button = (
                self.context.view.pressure_box.calibrate_pressure_button
            )
            calibration_tooltip = str(calibration_button.toolTip() or "")
            guide = self.context.view.experiment_task_list
            dispatch_after = dispatch_snapshot()
            checks = {
                **initial_checks,
                "dialog_closed_after_explicit_action": not dialog.isVisible(),
                "display_projection_active": bool(
                    model.is_completed_execution_view_active()
                ),
                "runtime_still_inactive": not projected_runtime_active,
                "durable_runtime_checkpoint_inactive": not bool(
                    experiment_model.uses_durable_execution_checkpoint()
                ),
                "controller_still_idle": array_state == "idle",
                "eligibility_still_terminal_analysis_only": (
                    projected_eligibility.get("status") == "analysis_only"
                    and not projected_eligibility.get("can_activate_runtime")
                    and not projected_eligibility.get("can_start_hardware")
                    and not projected_eligibility.get("can_resume_hardware")
                ),
                "plate_identity_exact": (
                    well_plate.get_current_plate_name() == plan.plate.name
                    and well_plate.get_plate_dimensions()
                    == (int(plan.plate.rows), int(plan.plate.columns))
                ),
                "well_assignments_exact": assignments == expected_assignments,
                "targets_exact": displayed_targets == expected_targets,
                "added_progress_exact": displayed_added == expected_added
                and expected_added == expected_targets,
                "all_assigned_wells_complete": set(completed_wells)
                == set(expected_assignments),
                "all_assigned_wells_visibly_complete": all(
                    "border: 1px solid white" in style
                    for style in completed_styles.values()
                ),
                "display_heads_exact": display_stock_ids == expected_stock_ids,
                "no_reagent_rack_assignments_invented": not reagent_rack_assignments,
                "start_control_disabled": (
                    start_button.text() == "Experiment Complete"
                    and not start_button.isEnabled()
                ),
                "stock_prep_calculator_enabled": bool(
                    plate_widget.stock_prep_button.isEnabled()
                ),
                "authoritative_mutation_controls_disabled": not bool(
                    plate_widget.calibration_button.isEnabled()
                ),
                "printer_head_diagnostics_disabled": not bool(
                    calibration_button.isEnabled()
                ),
                "printer_head_diagnostics_tooltip": (
                    "Historical experiments are analysis-only"
                    in calibration_tooltip
                ),
                "guide_reports_complete": guide.next_label.text()
                == "Next: Experiment complete",
                "no_machine_or_simulator_dispatch": dispatch_after
                == dispatch_before,
            }
            evidence = {
                "checks": checks,
                "experiment_dir": str(directory),
                "experiment_name": dialog.exp_name_edit.text(),
                "plan_id": str(plan.plan_id),
                "plan_revision": int(plan.plan_revision),
                "plan_state": str(plan.state.value),
                "eligibility": projected_eligibility,
                "runtime_active": projected_runtime_active,
                "array_state": array_state,
                "action_label": "View Completed Experiment",
                "action_enabled": True,
                "printer_head_diagnostics_enabled": bool(
                    calibration_button.isEnabled()
                ),
                "printer_head_diagnostics_tooltip": calibration_tooltip,
                "status_text": status_text,
                "banner_text": banner_text,
                "activation_performed": False,
                "display_projection_performed": True,
                "runtime_assignments": assignments,
                "expected_assignments": expected_assignments,
                "runtime_assignment_count": len(assignments),
                "expected_assignment_count": len(expected_assignments),
                "runtime_assignments_sha256": canonical_sha256(assignments),
                "expected_assignments_sha256": canonical_sha256(
                    expected_assignments
                ),
                "displayed_targets": displayed_targets,
                "displayed_added": displayed_added,
                "persisted_added": expected_added,
                "completed_well_ids": sorted(completed_wells),
                "display_stock_ids": sorted(display_stock_ids),
                "reagent_rack_assignments": reagent_rack_assignments,
                "dispatch_before": dispatch_before,
                "dispatch_after": dispatch_after,
                "file_selection_mechanic": "qt_file_dialog_directory_selection",
            }
            if not all(checks.values()):
                raise RuntimeError(
                    f"completed execution did not reload read-only: {checks}"
                )
            capture_milestone(
                self.context,
                "terminal_reloaded",
                evidence=evidence,
                widget=self.context.view,
            )
            return evidence

        def record_loaded(dialog) -> Mapping[str, Any]:
            return execute_action(
                self.context,
                "experiment.inspect_completed_via_ui",
                lambda: inspect_loaded(dialog),
            )["evidence"]

        return self._drive_directory_load(
            directory, purpose="completed", on_loaded=record_loaded
        )["loaded"]

    def inspect_legacy_execution(
        self,
        experiment_dir,
        *,
        expected_name: str,
    ) -> dict[str, Any]:
        """Display one reconstructed older experiment through the real editor."""

        from pathlib import Path
        from tools.virtual_workflows.actions import capture_milestone, execute_action

        directory = Path(experiment_dir).resolve()

        def dispatch_snapshot() -> dict[str, int]:
            instrumentation = getattr(self.context, "instrumentation", None)
            machine = getattr(self.context, "machine", None)
            return {
                "intent_begins": len(
                    getattr(instrumentation, "intent_begins", ()) or ()
                ),
                "simulator_dispenses": len(
                    getattr(instrumentation, "simulator_dispenses", ()) or ()
                ),
                "machine_commands": len(
                    getattr(machine, "command_event_history", ()) or ()
                ),
            }

        def inspect_loaded(dialog) -> Mapping[str, Any]:
            experiment_model = self.context.experiment_model
            plan = experiment_model.get_execution_plan_snapshot()
            status_text = str(dialog.status_lbl.text() or "")
            banner_text = str(dialog.lifecycle_banner.text() or "")
            initial_checks = {
                "name_matches": dialog.exp_name_edit.text() == expected_name,
                "path_matches": Path(experiment_model.experiment_dir_path).resolve()
                == directory,
                "legacy_read_only": experiment_model.is_read_only_legacy_execution(),
                "legacy_view_available": experiment_model.can_view_legacy_execution(),
                "plan_partial": str(plan.state.value) == "active",
                "action_is_view_older": dialog.finish_btn.text()
                == "View Older Experiment",
                "action_enabled": bool(dialog.finish_btn.isEnabled()),
                "read_only_guidance": "view older experiment"
                in status_text.casefold(),
                "visible_lock_banner": not dialog.lifecycle_banner.isHidden()
                and "locked and read-only" in banner_text.casefold()
                and "printing cannot be started or resumed"
                in banner_text.casefold(),
            }
            if not all(initial_checks.values()):
                raise RuntimeError(
                    "older experiment did not expose its read-only view: "
                    f"{initial_checks}"
                )
            capture_milestone(
                self.context,
                "legacy_editor",
                evidence=initial_checks,
                widget=dialog,
            )

            dispatch_before = dispatch_snapshot()
            self.click(dialog.finish_btn)
            if dialog.isVisible():
                raise RuntimeError("View Older Experiment did not close the editor")
            self.context.pump_events()

            model = self.context.model
            displayed_targets = {}
            displayed_added = {}
            completed_wells = []
            for plan_well in plan.wells:
                reaction = model.well_plate.get_well(
                    plan_well.well_id
                ).get_assigned_reaction()
                displayed_targets[plan_well.well_id] = {
                    stock_id: int(reagent.target_droplets)
                    for stock_id, reagent in reaction.get_all_reagents().items()
                }
                displayed_added[plan_well.well_id] = {
                    stock_id: int(reagent.added_droplets)
                    for stock_id, reagent in reaction.get_all_reagents().items()
                }
                if reaction.check_all_complete():
                    completed_wells.append(plan_well.well_id)

            expected_targets = {
                well.well_id: {
                    dispense.stock_id: int(dispense.target_dispenses)
                    for dispense in well.dispenses
                }
                for well in plan.wells
            }
            expected_added = {
                well.well_id: {
                    dispense.stock_id: int(
                        experiment_model.progress_data[well.well_id]["reagents"][
                            dispense.stock_id
                        ].get("added_droplets", 0)
                        or 0
                    )
                    for dispense in well.dispenses
                }
                for well in plan.wells
            }
            plate_widget = self.context.view.well_plate_widget
            checks = {
                **initial_checks,
                "display_projection_active": model.is_read_only_experiment_view_active(),
                "not_completed_view": not model.is_completed_execution_view_active(),
                "runtime_inactive": not experiment_model.is_authoritative_execution_runtime_active(),
                "targets_exact": displayed_targets == expected_targets,
                "added_progress_exact": displayed_added == expected_added,
                "mixed_completion_visible": completed_wells == ["A1"],
                "start_control_disabled": (
                    plate_widget.start_print_array_button.text()
                    == "Experiment Read-Only"
                    and not plate_widget.start_print_array_button.isEnabled()
                ),
                "stock_prep_calculator_enabled": bool(
                    plate_widget.stock_prep_button.isEnabled()
                ),
                "authoritative_mutation_controls_disabled": not bool(
                    plate_widget.calibration_button.isEnabled()
                ),
                "no_machine_or_simulator_dispatch": dispatch_snapshot()
                == dispatch_before,
            }
            if not all(checks.values()):
                raise RuntimeError(
                    f"older experiment read-only projection was not exact: {checks}"
                )
            capture_milestone(
                self.context,
                "legacy_main",
                evidence=checks,
            )
            return {
                "checks": checks,
                "experiment_dir": str(directory),
                "experiment_name": expected_name,
                "plan_state": str(plan.state.value),
                "displayed_targets": displayed_targets,
                "displayed_added": displayed_added,
                "completed_well_ids": completed_wells,
                "status_text": status_text,
                "banner_text": banner_text,
                "dispatch_before": dispatch_before,
                "dispatch_after": dispatch_snapshot(),
            }

        def record_loaded(dialog) -> Mapping[str, Any]:
            return execute_action(
                self.context,
                "experiment.inspect_legacy_via_ui",
                lambda: inspect_loaded(dialog),
            )["evidence"]

        return self._drive_directory_load(
            directory,
            purpose="older experiment",
            on_loaded=record_loaded,
        )["loaded"]

    def create_legacy_editable_copy(
        self,
        experiment_dir,
        *,
        copy_name: str,
    ) -> dict[str, Any]:
        """Create a fresh editable copy from an older experiment via the editor."""

        import json
        from pathlib import Path
        from View import ExperimentDesignDialog
        from tools.virtual_workflows.actions import capture_milestone, execute_action

        directory = Path(experiment_dir).resolve()
        destination = (directory.parent / copy_name).resolve()

        button = self.view.well_plate_widget.design_experiment_button
        if not button.isVisible() or not button.isEnabled():
            raise RuntimeError("Experiment Editor control is not visible and enabled")
        state: dict[str, Any] = {
            "editor_opened": False,
            "source_opened_read_only": False,
            "copy_button_clicked": False,
            "copy_action_active": False,
            "name_handled": False,
            "error": None,
            "evidence": None,
        }

        def inspect_editable_copy(dialog) -> None:
            if Path(self.context.experiment_model.experiment_dir_path).resolve() != destination:
                raise RuntimeError("editable copy did not become the active design")
            progress = json.loads(
                (destination / "progress.json").read_text(encoding="utf-8")
            )
            controls_editable = (
                dialog.exp_name_edit.isEnabled()
                and not dialog.exp_name_edit.isReadOnly()
                and dialog.run_btn.isEnabled()
                and dialog.finish_btn.isEnabled()
                and dialog.finish_btn.text() == "Finalize Experiment"
            )
            evidence = {
                "source": str(directory),
                "destination": str(destination),
                "copy_name": str(dialog.exp_name_edit.text()),
                "direct_read_only_launch": bool(state["editor_opened"]),
                "saved_progress_prompt_absent": True,
                "source_opened_read_only": bool(state["source_opened_read_only"]),
                "copy_button_clicked": bool(state["copy_button_clicked"]),
                "name_dialog_handled": bool(state["name_handled"]),
                "controls_editable": controls_editable,
                "legacy_state_cleared": not dialog.model.is_read_only_legacy_execution(),
                "progress_empty": progress == {},
                "no_execution_plan": not (
                    destination / "execution_plan.json"
                ).exists(),
                "no_resume_checkpoint": not (
                    destination / "execution_resume.json"
                ).exists(),
            }
            capture_milestone(
                self.context,
                "legacy_editable_copy",
                evidence=evidence,
                widget=dialog,
            )
            state["evidence"] = evidence
            dialog.reject()

        def click_copy_and_inspect(dialog) -> None:
            try:
                self.click(dialog.duplicate_btn)
                state["copy_action_active"] = False
                if not state["name_handled"]:
                    raise RuntimeError(
                        "editable-copy name dialog was not completed"
                    )
                inspect_editable_copy(dialog)
            except BaseException as exc:
                state["copy_action_active"] = False
                state["error"] = exc
                if dialog.isVisible():
                    dialog.reject()

        def drive_editor_and_name_dialog() -> None:
            modal = self.app.activeModalWidget()
            if modal is None:
                return
            try:
                if isinstance(modal, QtWidgets.QMessageBox):
                    raise RuntimeError(
                        "unexpected prompt while directly opening the read-only editor: "
                        f"{modal.windowTitle()!r}"
                    )
                if isinstance(modal, QtWidgets.QInputDialog):
                    if state["name_handled"]:
                        return
                    line_edit = modal.findChild(QtWidgets.QLineEdit)
                    button_box = modal.findChild(QtWidgets.QDialogButtonBox)
                    accept = (
                        button_box.button(QtWidgets.QDialogButtonBox.Ok)
                        if button_box is not None
                        else None
                    )
                    if (
                        modal.windowTitle() != "Create Editable Copy"
                        or line_edit is None
                        or accept is None
                    ):
                        raise RuntimeError("editable-copy name controls are missing")
                    line_edit.setFocus()
                    QtTest.QTest.keyClick(
                        line_edit,
                        QtCore.Qt.Key.Key_A,
                        QtCore.Qt.KeyboardModifier.ControlModifier,
                    )
                    QtTest.QTest.keyClicks(line_edit, copy_name)
                    state["name_handled"] = True
                    QtTest.QTest.mouseClick(
                        accept,
                        QtCore.Qt.MouseButton.LeftButton,
                    )
                    return
                if isinstance(modal, ExperimentDesignDialog):
                    if state["copy_action_active"]:
                        return
                    if state["evidence"] is not None:
                        return
                    if not state["editor_opened"]:
                        state["editor_opened"] = True
                        state["source_opened_read_only"] = bool(
                            getattr(modal, "_progress_protected", False)
                            and modal.model.is_read_only_legacy_execution()
                            and not modal.finish_btn.text() == "Finalize Experiment"
                        )
                        if not modal.duplicate_btn.isEnabled():
                            raise RuntimeError(
                                "Create Editable Copy is disabled in the read-only editor"
                            )
                        state["copy_button_clicked"] = True
                        state["copy_action_active"] = True
                        QtCore.QTimer.singleShot(
                            0,
                            lambda dialog=modal: click_copy_and_inspect(dialog),
                        )
                    return
                raise RuntimeError(
                    "unexpected modal while creating editable copy: "
                    f"{type(modal).__name__} {modal.windowTitle()!r}"
                )
            except BaseException as exc:
                state["error"] = exc
                if isinstance(modal, QtWidgets.QDialog) and modal.isVisible():
                    modal.reject()

        def operation() -> Mapping[str, Any]:
            modal_timer = QtCore.QTimer(self.app)
            modal_timer.setInterval(5)
            modal_timer.timeout.connect(drive_editor_and_name_dialog)
            modal_timer.start()
            try:
                with _expected_dialogs(
                    self.app,
                    ("Experiment Design (v2)", "ExperimentDesignDialog"),
                    ("Create Editable Copy", "EditableCopyNameDialog"),
                ):
                    self.click(button)
            finally:
                modal_timer.stop()
                modal_timer.deleteLater()
            if state["error"] is not None:
                raise state["error"]
            if not state["editor_opened"] or not state["name_handled"]:
                raise RuntimeError(
                    "read-only editor editable-copy flow was not completed"
                )
            if state["evidence"] is None:
                raise RuntimeError("editable copy editor inspection did not finish")
            if not all(
                value
                for key, value in state["evidence"].items()
                if key not in {"source", "destination", "copy_name"}
            ):
                raise RuntimeError(
                    f"editable copy was not fresh and editable: {state['evidence']}"
                )
            return dict(state["evidence"])

        return execute_action(
            self.context,
            "editor.create_editable_copy_via_ui",
            operation,
        )["evidence"]

    def validate_legacy_plate_reader_analysis(
        self,
        experiment_dir,
        plate_reader_path,
        *,
        action_runner: Callable[..., dict[str, Any]],
    ) -> dict[str, Any]:
        """Open the real analysis window and validate its prefilled legacy inputs."""

        from tools.virtual_workflows.actions import capture_milestone

        directory = Path(experiment_dir).resolve()
        plate_path = Path(plate_reader_path).resolve()

        def operation() -> Mapping[str, Any]:
            button = self.view.plate_reader_analysis_button
            if not button.isVisible() or not button.isEnabled():
                raise RuntimeError("plate-reader analysis control is unavailable")
            self.click(button)
            self.wait_until(
                lambda: getattr(
                    self.view, "_plate_reader_analysis_window", None
                )
                is not None,
                "plate-reader analysis window",
                timeout_seconds=5.0,
            )
            window = getattr(self.view, "_plate_reader_analysis_window", None)
            if window is None:
                raise RuntimeError("plate-reader analysis window did not open")
            window.show()
            self.context.pump_events()
            if window.isHidden():
                raise RuntimeError(
                    "plate-reader analysis window did not become visible"
                )
            window.plate_reader_file_edit.setText(str(plate_path))
            self.context.pump_events()
            paths_prefilled = (
                Path(window.experiment_dir_edit.text()).resolve() == directory
                and Path(window.key_file_edit.text()).resolve()
                == (directory / "concentration_key.csv").resolve()
            )
            self.click(window.validate_preview_button)
            self.wait_until(
                lambda: not bool(getattr(window, "_previewing", False)),
                "legacy plate-reader validation preview",
                timeout_seconds=20.0,
            )
            preview = dict(getattr(window, "_last_preview_payload", {}) or {})
            evidence = {
                "paths_prefilled": paths_prefilled,
                "preview_valid": bool(getattr(window, "_preview_valid", False)),
                "preview_ok": bool(preview.get("ok")),
                "preview_errors": list(preview.get("errors", []) or []),
                "experiment_dir": window.experiment_dir_edit.text(),
                "key_file": window.key_file_edit.text(),
                "plate_reader_file": window.plate_reader_file_edit.text(),
            }
            capture_milestone(
                self.context,
                "legacy_plate_reader",
                evidence=evidence,
                widget=window,
            )
            window.close()
            self.context.pump_events()
            return evidence

        with _expected_dialogs(
            self.app,
            ("Plate Reader Analysis", "PlateReaderAnalysisWindow"),
        ):
            return action_runner(
                "analysis.open_plate_reader_via_ui",
                operation,
            )["evidence"]


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

        with _expected_dialogs(self.app, ("Edit Volume", "VolumeDialog")):
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
        if button.text() == "Confirm":
            self.click(button)
            self.wait_until(lambda: button.text() == "Load", "rack slot confirmation")
        elif button.text() != "Load":
            raise RuntimeError(
                f"expected Confirm or Load control; observed {button.text()!r}"
            )
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

    def assigned_slot_for_stock(self, stock_id: str) -> int | None:
        matches = [
            index
            for index, slot in enumerate(self.context.model.rack_model.slots)
            if slot.printer_head is not None
            and str(slot.printer_head.get_stock_id()) == str(stock_id)
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"expected at most one rack slot for stock {stock_id!r}; observed {matches}"
            )
        return matches[0] if matches else None

    def swap_unassigned_head(self, slot_index: int, stock_id: str) -> Mapping[str, Any]:
        """Select one unassigned stock head through the normal Swap combobox."""

        slot_index = int(slot_index)
        rack_model = self.context.model.rack_model
        if rack_model.get_gripper_printer_head() is not None:
            raise RuntimeError("cannot swap a rack head while the gripper is occupied")
        if self.context.controller.get_array_run_state() not in {"idle", "resume_ready"}:
            raise RuntimeError("cannot swap a rack head while the array is active")
        if not self.context.machine.check_if_all_completed():
            raise RuntimeError("cannot swap a rack head before the command queue drains")

        manager = self.context.model.printer_head_manager
        matches = [
            head
            for head in manager.get_unassigned_printer_heads()
            if str(head.get_stock_id()) == str(stock_id)
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one unassigned head for stock {stock_id!r}; observed {len(matches)}"
            )
        target = matches[0]
        previous = rack_model.slots[slot_index].printer_head
        combo = self.view.rack_box.slot_widgets[slot_index][3]
        label = target.get_display_stock_name()
        indices = [index for index in range(combo.count()) if combo.itemText(index) == label]
        if len(indices) != 1:
            raise RuntimeError(
                f"expected one Swap option for stock {stock_id!r}; observed {indices}"
            )
        if not combo.isVisible() or not combo.isEnabled():
            raise RuntimeError("rack Swap control must be visible and enabled")

        self.select_combo_index(
            combo,
            indices[0],
            selected=lambda: rack_model.slots[slot_index].printer_head is target,
        )
        self.wait_until(
            lambda: rack_model.slots[slot_index].printer_head is target,
            "rack head swap",
        )
        return {
            "slot": slot_index,
            "stock_id": str(stock_id),
            "printer_head_id": str(target.printer_head_id),
            "replaced_printer_head_id": (
                str(previous.printer_head_id) if previous is not None else None
            ),
            "control": "rack_swap_combobox",
        }

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
        self.inspect_control(expected_text=text, expected_enabled=enabled)

    def inspect_control(
        self,
        *,
        expected_text: str | None = None,
        expected_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Capture and optionally validate the real print-array control."""

        self.context.pump_events()
        button = self.control
        loaded_array_getter = getattr(
            self.context.controller,
            "get_loaded_array_control_state",
            None,
        )
        loaded_array = (
            loaded_array_getter() if callable(loaded_array_getter) else {}
        )
        evidence = {
            "text": str(button.text()),
            "enabled": bool(button.isEnabled()),
            "visible": bool(button.isVisible()),
            "array_state": str(self.context.controller.get_array_run_state()),
            "loaded_array": dict(loaded_array or {}),
        }
        if (
            expected_text is not None
            and evidence["text"] != str(expected_text)
        ) or (
            expected_enabled is not None
            and evidence["enabled"] is not bool(expected_enabled)
        ):
            raise RuntimeError(
                f"expected {expected_text!r} array control "
                f"(enabled={expected_enabled}); observed {evidence['text']!r} "
                f"(enabled={evidence['enabled']})"
            )
        return evidence

    def click_start(self) -> None:
        self.click(self.control)

    def start(
        self,
        expected_dialogs: list[tuple[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        self._require_control("Start Array")
        dialogs = self.click_with_message_boxes(
            self.control,
            expected_dialogs or [
                ("Start Print Array", QtWidgets.QMessageBox.StandardButton.Yes),
                (
                    "Evaporation Plate Dock Check",
                    QtWidgets.QMessageBox.StandardButton.Yes,
                ),
            ],
        )
        self.wait_until(
            lambda: self.context.controller.get_array_run_state() == "running",
            "started array running state",
        )
        self._require_control("Stop After Well")
        return dialogs

    def start_and_cancel_manual_refuel_guard(
        self,
        start_dialogs: list[tuple[str, Any]],
        *,
        completion_count: Callable[[], int],
    ) -> dict[str, Any]:
        """Attempt Start, select the default-safe refuel Cancel, and prove no run."""

        before_plan = self.context.experiment_model.get_execution_plan_snapshot()
        before_state = self.context.controller.get_array_run_state()
        before_completed = int(completion_count())
        self._require_control("Start Array")
        dialogs = self.click_with_message_boxes(
            self.control,
            [
                *start_dialogs,
                ("Manual Refuel Check Required", "Cancel"),
            ],
        )
        self.wait_until(
            lambda: self.context.controller.get_array_run_state() == "idle"
            and self.context.machine.check_if_all_completed(),
            "cancelled manual-refuel safeguard boundary",
        )
        after_plan = self.context.experiment_model.get_execution_plan_snapshot()
        after_completed = int(completion_count())
        if (
            before_state != "idle"
            or str(after_plan.state.value) != str(before_plan.state.value)
            or before_completed != after_completed
        ):
            raise RuntimeError(
                "manual-refuel Cancel did not preserve the authoritative idle boundary"
            )
        return {
            "dialogs": dialogs,
            "cancelled": True,
            "array_state_before": before_state,
            "array_state_after": self.context.controller.get_array_run_state(),
            "plan_state_before": str(before_plan.state.value),
            "plan_state_after": str(after_plan.state.value),
            "completion_count_before": before_completed,
            "completion_count_after": after_completed,
            "queue_drained": True,
        }

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
        self._require_control("Stop After Well")
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

    def _select_printing_mode_tab(self, target_mode: str) -> None:
        target_mode = str(target_mode or "").strip().lower()
        if target_mode == "droplet":
            tab = self.dialog.droplet_tab
        elif target_mode == "stream":
            tab = self.dialog.stream_tab
        else:
            raise ValueError("target_mode must be droplet or stream")
        self.dialog.calibration_tabs.setCurrentWidget(tab)
        self.app.processEvents()

    def _expand_printing_controls(self) -> None:
        toggle = getattr(self.dialog, "printing_controls_toggle", None)
        if toggle is None:
            raise RuntimeError("printing controls toggle is missing")
        if not toggle.isChecked():
            QtTest.QTest.mouseClick(toggle, QtCore.Qt.MouseButton.LeftButton)
            self.app.processEvents()
        if not toggle.isChecked():
            raise RuntimeError("printing controls did not expand")

    def _replace_spin_value(self, widget: Any, value: int | float) -> None:
        if widget is None or not widget.isVisible() or not widget.isEnabled():
            raise RuntimeError("requested printing control is not visible and enabled")
        editor = widget.lineEdit()
        QtTest.QTest.mouseClick(editor, QtCore.Qt.MouseButton.LeftButton)
        QtTest.QTest.keyClick(
            editor,
            QtCore.Qt.Key.Key_A,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QtTest.QTest.keyClicks(editor, str(value))
        QtTest.QTest.keyClick(editor, QtCore.Qt.Key.Key_Enter)
        self.app.processEvents()

    def _printing_queue_empty(self) -> bool:
        controller = getattr(self.dialog, "controller", None)
        machine = getattr(controller, "machine", None)
        getter = getattr(machine, "check_if_all_completed", None)
        return bool(getter()) if callable(getter) else True

    def inspect_printing_controls(self, target_mode: str) -> dict[str, Any]:
        """Inspect the real printing-control surface for one workflow tab."""

        self._select_printing_mode_tab(target_mode)
        self._expand_printing_controls()
        section = getattr(self.dialog, "printing_controls_section", None)
        combo = getattr(self.dialog, "print_profile_combo", None)
        button = getattr(self.dialog, "print_profile_apply_button", None)
        required = (
            section,
            combo,
            button,
            getattr(self.dialog, "target_print_pressure_spinbox", None),
            getattr(self.dialog, "target_refuel_pressure_spinbox", None),
            getattr(self.dialog, "print_pulse_width_spinbox", None),
            getattr(self.dialog, "refuel_pulse_width_spinbox", None),
        )
        if any(widget is None for widget in required):
            raise RuntimeError("printing controls are incomplete")
        profiles = [combo.itemData(index) for index in range(combo.count())]
        selected = combo.currentData()
        return {
            "target_mode": str(target_mode).strip().lower(),
            "section_visible": bool(section.isVisible()),
            "expanded": bool(self.dialog.printing_controls_toggle.isChecked()),
            "controls_enabled": bool(
                self.dialog.target_print_pressure_spinbox.isEnabled()
            ),
            "profile_ids": [
                str(profile.get("id") or "")
                for profile in profiles
                if isinstance(profile, dict)
            ],
            "selected_profile_id": (
                str(selected.get("id") or "")
                if isinstance(selected, dict)
                else None
            ),
            "profile_button_text": button.text(),
            "target_print_pressure_psi": float(
                self.dialog.target_print_pressure_spinbox.value()
            ),
            "target_refuel_pressure_psi": float(
                self.dialog.target_refuel_pressure_spinbox.value()
            ),
            "print_pulse_width_us": int(
                self.dialog.print_pulse_width_spinbox.value()
            ),
            "refuel_pulse_width_us": int(
                self.dialog.refuel_pulse_width_spinbox.value()
            ),
            "current_print_pressure_text": self.dialog.current_print_pressure_value.text(),
            "current_refuel_pressure_text": self.dialog.current_refuel_pressure_value.text(),
        }

    def set_printing_controls(
        self,
        target_mode: str,
        *,
        print_pressure_psi: float,
        refuel_pressure_psi: float,
        print_pulse_width_us: int,
        refuel_pulse_width_us: int,
    ) -> dict[str, Any]:
        """Edit all four settings through the visible dialog controls."""

        state = self.inspect_printing_controls(target_mode)
        if not state["section_visible"] or not state["controls_enabled"]:
            raise RuntimeError("printing controls are not available")
        requested = (
            (self.dialog.target_print_pressure_spinbox, float(print_pressure_psi)),
            (self.dialog.target_refuel_pressure_spinbox, float(refuel_pressure_psi)),
            (self.dialog.print_pulse_width_spinbox, int(print_pulse_width_us)),
            (self.dialog.refuel_pulse_width_spinbox, int(refuel_pulse_width_us)),
        )
        for widget, value in requested:
            self._replace_spin_value(widget, value)
        machine_model = getattr(getattr(self.dialog, "model", None), "machine_model", None)

        def converged() -> bool:
            getters = (
                ("get_target_print_pressure", float(print_pressure_psi), 0.005),
                ("get_target_refuel_pressure", float(refuel_pressure_psi), 0.005),
                ("get_print_pulse_width", int(print_pulse_width_us), 0),
                ("get_refuel_pulse_width", int(refuel_pulse_width_us), 0),
            )
            for getter_name, expected, tolerance in getters:
                getter = getattr(machine_model, getter_name, None)
                if callable(getter) and abs(float(getter()) - float(expected)) > tolerance:
                    return False
            return self._printing_queue_empty()

        self.wait_until(converged, "printing settings convergence")
        return self.inspect_printing_controls(target_mode)

    def apply_print_profile_from_panel(
        self,
        target_mode: str,
        profile_id: str,
    ) -> dict[str, Any]:
        """Select and apply one tab-filtered profile through the dialog."""

        state = self.inspect_printing_controls(target_mode)
        combo = self.dialog.print_profile_combo
        match = next(
            (
                index
                for index in range(combo.count())
                if isinstance(combo.itemData(index), dict)
                and str(combo.itemData(index).get("id") or "") == str(profile_id)
            ),
            -1,
        )
        if match < 0:
            raise RuntimeError(
                f"print profile is unavailable for {target_mode}: {profile_id}"
            )
        combo.setCurrentIndex(match)
        self.app.processEvents()
        button = self.dialog.print_profile_apply_button
        if button.text() != "Loaded":
            if not button.isVisible() or not button.isEnabled():
                raise RuntimeError(
                    f"print profile cannot be applied: {button.text()}"
                )
            QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
            self.wait_until(
                lambda: button.text() == "Loaded" and self._printing_queue_empty(),
                f"print profile {profile_id} convergence",
            )
        evidence = self.inspect_printing_controls(target_mode)
        if evidence["selected_profile_id"] != str(profile_id):
            raise RuntimeError("selected print profile drifted during application")
        return evidence

    def inspect_live_pressure_plot(self) -> dict[str, Any]:
        """Return read-only evidence from the imager's live-pressure chart."""

        section = getattr(self.dialog, "live_pressure_section", None)
        toggle = getattr(self.dialog, "live_pressure_toggle", None)
        timer = getattr(self.dialog, "live_pressure_render_timer", None)
        chart = getattr(self.dialog, "live_pressure_chart", None)
        axis_x = getattr(self.dialog, "live_pressure_axis_x", None)
        axis_y = getattr(self.dialog, "live_pressure_axis_y", None)
        named_series = {
            "print": getattr(self.dialog, "live_print_pressure_series", None),
            "refuel": getattr(self.dialog, "live_refuel_pressure_series", None),
            "target_print": getattr(
                self.dialog, "live_target_print_pressure_series", None
            ),
            "target_refuel": getattr(
                self.dialog, "live_target_refuel_pressure_series", None
            ),
        }
        required = (
            section,
            toggle,
            timer,
            chart,
            axis_x,
            axis_y,
            *named_series.values(),
        )
        if any(item is None for item in required):
            raise RuntimeError("live pressure plot is incomplete")

        def inspect_series(series: Any) -> dict[str, Any]:
            count = int(series.count())
            latest = float(series.at(count - 1).y()) if count else None
            pen = series.pen()
            pen_style = pen.style()
            if pen_style == QtCore.Qt.PenStyle.SolidLine:
                line_style = "solid"
            elif pen_style == QtCore.Qt.PenStyle.DashLine:
                line_style = "dash"
            else:
                line_style = str(pen_style)
            return {
                "name": str(series.name()),
                "count": count,
                "latest_value": latest,
                "color": str(pen.color().name()).lower(),
                "opacity": float(pen.color().alphaF()),
                "line_width": float(pen.widthF()),
                "line_style": line_style,
            }

        series_evidence = {
            key: inspect_series(series) for key, series in named_series.items()
        }
        return {
            "section_visible": bool(section.isVisible()),
            "expanded": bool(toggle.isChecked()),
            "timer_active": bool(timer.isActive()),
            "series": series_evidence,
            "series_names": [
                evidence["name"] for evidence in series_evidence.values()
            ],
            "animation": (
                "none" if not bool(chart.animationOptions()) else str(chart.animationOptions())
            ),
            "legend_entries": [
                str(label)
                for label in (
                    chart.property("pressureLegendEntries")
                    or [
                        marker.label()
                        for marker in chart.legend().markers()
                        if marker.isVisible()
                    ]
                )
            ],
            "target_print_pressure_psi": series_evidence["target_print"][
                "latest_value"
            ],
            "target_refuel_pressure_psi": series_evidence["target_refuel"][
                "latest_value"
            ],
            "axis_x": {"minimum": float(axis_x.min()), "maximum": float(axis_x.max())},
            "axis_y": {"minimum": float(axis_y.min()), "maximum": float(axis_y.max())},
        }

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
        preflight_expected = bool(readiness.get("correctable"))
        with _expected_dialogs(
            self.app,
            *(("Calibration Settings Check", "CalibrationModePreflightDialog"),)
            if preflight_expected
            else (),
        ):
            if preflight_expected:
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
        expected = str(result_fingerprint)
        match: tuple[int, Mapping[str, Any]] | None = None

        for source_row in range(source.rowCount()):
            raw = source.raw_row_at(source_row) or {}
            if raw.get("synthetic_result_fingerprint") != expected:
                continue
            result_set_key = str(raw.get("result_set_key") or "")
            combo = getattr(self.dialog, "summary_result_set_combo", None)
            if result_set_key and isinstance(combo, QtWidgets.QComboBox):
                result_set_index = combo.findData(result_set_key)
                if result_set_index >= 0 and combo.currentIndex() != result_set_index:
                    combo.setCurrentIndex(result_set_index)
                    self.app.processEvents()
            break

        def _result_visible() -> bool:
            nonlocal match
            match = None
            for proxy_row in range(proxy.rowCount()):
                source_index = proxy.mapToSource(proxy.index(proxy_row, 0))
                raw = source.raw_row_at(source_index.row()) or {}
                if raw.get("synthetic_result_fingerprint") == expected:
                    match = (proxy_row, raw)
                    return True
            return False

        self.wait_until(
            _result_visible,
            f"synthetic calibration result visibility: {expected}",
        )
        if match is None:
            raise RuntimeError(f"synthetic result is not visible: {expected}")
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

    def select_persisted_result(
        self,
        *,
        source_run_id: str,
        source_phase_key: str,
        source_step_index: int,
        source_pressure_index: int | None,
    ) -> dict[str, Any]:
        """Select one legacy-backed summary row by its stable source coordinates."""

        expected = {
            "source_run_id": str(source_run_id),
            "source_phase_key": str(source_phase_key),
            "source_step_index": int(source_step_index),
            "source_pressure_index": (
                None
                if source_pressure_index is None
                else int(source_pressure_index)
            ),
        }
        table = self.dialog.summary_table
        proxy = self.dialog.summary_table_proxy_model
        source = self.dialog.summary_table_model
        match = None
        for proxy_row in range(proxy.rowCount()):
            source_index = proxy.mapToSource(proxy.index(proxy_row, 0))
            raw = dict(source.raw_row_at(source_index.row()) or {})
            observed = {
                "source_run_id": str(raw.get("source_run_id") or ""),
                "source_phase_key": str(raw.get("source_phase_key") or ""),
                "source_step_index": raw.get("source_step_index"),
                "source_pressure_index": raw.get("source_pressure_index"),
            }
            if observed == expected:
                match = (proxy_row, raw)
                break
        if match is None:
            raise RuntimeError(
                "persisted calibration result is not visible at source coordinates: "
                f"{expected}"
            )
        proxy_row, raw = match
        target = proxy.index(proxy_row, 1)
        table.scrollTo(target)
        rect = table.visualRect(target)
        QtTest.QTest.mouseClick(
            table.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=rect.center(),
        )
        self.wait_until(
            lambda: bool(self.dialog._selected_summary_row()[1]),
            "persisted calibration row selection",
        )
        selected = dict(self.dialog._selected_summary_row()[1] or {})
        for key, value in expected.items():
            if selected.get(key) != value:
                raise RuntimeError(
                    "persisted calibration selection drifted from its source coordinates"
                )
        return dict(raw)

    def select_canonical_result(
        self,
        *,
        result_id: str,
        update_id: str,
        row_ordinal: int = 0,
    ) -> dict[str, Any]:
        """Select one persisted row by canonical result/update identity."""

        expected = (str(result_id), str(update_id), int(row_ordinal))
        table = self.dialog.summary_table
        proxy = self.dialog.summary_table_proxy_model
        source = self.dialog.summary_table_model
        match = None
        for proxy_row in range(proxy.rowCount()):
            source_index = proxy.mapToSource(proxy.index(proxy_row, 0))
            raw = dict(source.raw_row_at(source_index.row()) or {})
            observed = (
                str(raw.get("result_id") or ""),
                str(raw.get("update_id") or ""),
                int(raw.get("row_ordinal") or 0),
            )
            if observed == expected:
                match = (proxy_row, raw)
                break
        if match is None:
            raise RuntimeError(f"canonical calibration result is not visible: {expected}")
        proxy_row, raw = match
        target = proxy.index(proxy_row, 1)
        table.scrollTo(target)
        rect = table.visualRect(target)
        QtTest.QTest.mouseClick(
            table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center()
        )
        self.wait_until(
            lambda: bool(self.dialog._selected_summary_row()[1]),
            "canonical calibration row selection",
        )
        selected = dict(self.dialog._selected_summary_row()[1] or {})
        if (
            str(selected.get("result_id") or ""),
            str(selected.get("update_id") or ""),
            int(selected.get("row_ordinal") or 0),
        ) != expected:
            raise RuntimeError("canonical calibration selection identity drifted")
        return dict(raw)

    def inspect_preview(self) -> dict[str, Any]:
        payload = dict(getattr(self.dialog, "_bridge_preview_payload", None) or {})
        table = self.dialog.bridge_table
        headers = [
            (
                table.horizontalHeaderItem(column).text()
                if table.horizontalHeaderItem(column) is not None
                else None
            )
            for column in range(table.columnCount())
        ]
        rows = [
            [
                (
                    table.item(row, column).text()
                    if table.item(row, column) is not None
                    else None
                )
                for column in range(table.columnCount())
            ]
            for row in range(table.rowCount())
        ]
        return {
            "payload": payload,
            "status": self.dialog.bridge_status_label.text(),
            "apply_enabled": self.dialog.bridge_apply_btn.isEnabled(),
            "apply_text": self.dialog.bridge_apply_btn.text(),
            "apply_state": str(
                getattr(self.dialog, "_bridge_apply_button_state", "") or ""
            ),
            "apply_tooltip": str(self.dialog.bridge_apply_btn.toolTip() or ""),
            "load_selected_enabled": bool(
                self.dialog.load_selected_button.isEnabled()
            ),
            "recheck_enabled": bool(
                self.dialog.recheck_selected_button.isEnabled()
            ),
            "calibrate_all_enabled": bool(
                self.dialog.calibrate_all_button.isEnabled()
            ),
            "preview_rows": table.rowCount(),
            "visible_table": {
                "headers": headers,
                "rows": rows,
                "row_count": table.rowCount(),
                "column_count": table.columnCount(),
            },
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
                    "unexpected Apply dialog title: "
                    f"{active.windowTitle()!r}; message={active.text()!r}"
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

        with _expected_dialogs(
            self.app,
            *((title, "QMessageBox") for title, _button in steps),
        ):
            QtCore.QTimer.singleShot(0, handle_modal)
            QtTest.QTest.mouseClick(
                self.dialog.bridge_apply_btn,
                QtCore.Qt.MouseButton.LeftButton,
            )
        if state["error"] is not None:
            raise state["error"]
        if steps:
            raise RuntimeError(
                "expected calibration Apply dialog sequence did not complete; "
                f"enabled={self.dialog.bridge_apply_btn.isEnabled()} "
                f"state={getattr(self.dialog, '_bridge_apply_button_state', None)!r} "
                f"tooltip={self.dialog.bridge_apply_btn.toolTip()!r} "
                f"status={self.dialog.bridge_status_label.text()!r}"
            )
        return list(state["handled"])

    def apply_expected_failure(
        self,
        *,
        expected_title: str,
        expected_message_fragment: str,
        mode_switch_choice: str | None = None,
        capture_modal: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """Apply through the real modal sequence and retain the expected failure."""

        if not str(expected_title).strip() or not str(expected_message_fragment):
            raise ValueError("expected failure title and message fragment are required")
        steps: list[tuple[str, Any, bool]] = []
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
                    False,
                )
            )
        steps.append((str(expected_title), QtWidgets.QMessageBox.Ok, True))
        state: dict[str, Any] = {
            "handled": [],
            "failure": None,
            "error": None,
        }

        def enum_name(value: Any) -> str:
            return str(getattr(value, "name", None) or value)

        def handle_modal() -> None:
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
            expected_step_title, standard_button, is_failure = steps.pop(0)
            if active.windowTitle() != expected_step_title:
                state["error"] = RuntimeError(
                    f"unexpected Apply dialog title: {active.windowTitle()!r}"
                )
                active.reject()
                return
            message = active.text()
            if is_failure and expected_message_fragment not in message:
                state["error"] = RuntimeError(
                    "expected Apply failure message fragment was absent"
                )
                active.reject()
                return
            button = active.button(standard_button)
            if button is None:
                state["error"] = RuntimeError(
                    f"expected button is missing from {active.windowTitle()!r}"
                )
                active.reject()
                return
            evidence = {
                "title": active.windowTitle(),
                "text": message,
                "icon": enum_name(active.icon()),
                "standard_buttons": enum_name(active.standardButtons()),
                "selected_button": enum_name(standard_button),
            }
            state["handled"].append(active.windowTitle())
            if is_failure:
                state["failure"] = evidence
                if capture_modal is not None:
                    capture_modal(dict(evidence))
            QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
            if steps:
                QtCore.QTimer.singleShot(0, handle_modal)

        with _expected_dialogs(
            self.app,
            *((title, "QMessageBox") for title, _button, _failure in steps),
        ):
            QtCore.QTimer.singleShot(0, handle_modal)
            QtTest.QTest.mouseClick(
                self.dialog.bridge_apply_btn,
                QtCore.Qt.MouseButton.LeftButton,
            )
        if state["error"] is not None:
            raise state["error"]
        if steps or state["failure"] is None:
            raise RuntimeError("expected calibration Apply failure did not complete")
        return {
            "handled_dialogs": list(state["handled"]),
            "failure": dict(state["failure"]),
        }

    def close(self, *, confirm_without_applied: bool = False) -> None:
        def accept_close_confirmation() -> None:
            active = self.app.activeModalWidget()
            if not isinstance(active, QtWidgets.QMessageBox):
                return
            if active.windowTitle() != "Exit without applied calibration?":
                active.reject()
                return
            button = active.button(QtWidgets.QMessageBox.Yes)
            if button is not None:
                QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)

        with _expected_dialogs(
            self.app,
            *(("Exit without applied calibration?", "QMessageBox"),)
            if confirm_without_applied
            else (),
        ):
            if confirm_without_applied:
                QtCore.QTimer.singleShot(0, accept_close_confirmation)
            self.dialog.close()
        self.wait_until(lambda: not self.dialog.isVisible(), "calibration dialog close")


class ManualRefuelCheckDriver(_QTestSurfaceDriver):
    """Drive the real post-calibration modal through bounded QTest clicks."""

    def complete_after_calibration_close(
        self,
        calibration: CalibrationDialogDriver,
        *,
        stock_id: str,
        printer_head_id: str,
        trial_count: int,
        trial_droplet_count: int,
        outcome: str,
        operator_judgment: str,
        capture_passed: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        if trial_count <= 0 or trial_droplet_count <= 0:
            raise ValueError("manual-refuel trial count and droplet count must be positive")
        outcome = str(outcome).strip().lower()
        operator_judgment = str(operator_judgment).strip().lower()
        outcome_controls = {
            ("passed", "stable"): "stable_button",
            ("failed", "level_rose"): "level_rose_button",
            ("failed", "level_fell"): "level_fell_button",
            ("unclear", "unclear"): "unclear_button",
        }
        control_name = outcome_controls.get((outcome, operator_judgment))
        if control_name is None:
            raise ValueError("manual-refuel outcome and judgment are unsupported")

        pressure_box = self.view.pressure_box
        deadline = time.monotonic() + self.context.deadline.remaining_seconds(20.0)
        state: dict[str, Any] = {
            "phase": "discover",
            "dialog": None,
            "trials_queued": 0,
            "error": None,
            "record": None,
        }

        def fail(message: str) -> None:
            if state["error"] is None:
                state["error"] = RuntimeError(message)
            dialog = state.get("dialog")
            if _qt_dialog_is_visible(dialog):
                dialog.reject()

        def reschedule() -> None:
            QtCore.QTimer.singleShot(10, advance)

        def current_record() -> dict[str, Any] | None:
            head = self.context.model.rack_model.get_gripper_printer_head()
            if head is None:
                return None
            record = self.context.experiment_model.get_manual_refuel_check(
                printer_head=head
            )
            return dict(record) if isinstance(record, dict) else None

        def record_matches(record: Mapping[str, Any], dialog: Any) -> bool:
            return (
                str(record.get("status") or "") == outcome
                and str(record.get("source") or "")
                == "sil_simulated_manual_refuel_check"
                and str(record.get("stock_id") or "") == str(stock_id)
                and str(record.get("printer_head_id") or "")
                == str(printer_head_id)
                and str(record.get("printing_mode") or "") == "stream"
                and int(record.get("trial_count") or 0) == trial_count
                and int(record.get("trial_droplet_count") or 0)
                == trial_droplet_count
                and str(record.get("operator_judgment") or "")
                == operator_judgment
                and str(record.get("applied_calibration_fingerprint") or "")
                == str(dialog.expected_calibration_fingerprint or "")
            )

        def advance() -> None:
            if state["error"] is not None or state["phase"] == "done":
                return
            if time.monotonic() >= deadline:
                fail(f"timed out during manual-refuel phase {state['phase']}")
                return
            dialog = getattr(pressure_box, "_manual_refuel_check_dialog", None)
            active = QtWidgets.QApplication.activeModalWidget()
            if state["phase"] == "discover":
                if dialog is None:
                    if active is not None and active is not calibration.dialog:
                        fail(
                            "unexpected modal while waiting for Manual Refuel Check: "
                            f"{active.windowTitle()!r}"
                        )
                        return
                    reschedule()
                    return
                if dialog.windowTitle() != "Manual Refuel Check" or not dialog.isVisible():
                    fail("manual-refuel dialog was not the expected visible application dialog")
                    return
                state["dialog"] = dialog
                try:
                    self.replace_spin_value(
                        dialog.trial_droplets_spin, trial_droplet_count
                    )
                except Exception as exc:
                    fail(f"could not set manual-refuel trial droplets: {exc}")
                    return
                state["phase"] = "queue_trial"
                reschedule()
                return

            dialog = state.get("dialog")
            if not isinstance(dialog, QtWidgets.QDialog):
                fail("manual-refuel dialog identity became unavailable")
                return
            if state["phase"] == "queue_trial":
                if not self.context.machine.check_if_all_completed():
                    reschedule()
                    return
                button = dialog.run_trial_button
                if not button.isVisible() or not button.isEnabled():
                    fail("manual-refuel Run Trial control is unavailable")
                    return
                trial_count_before = int(dialog.trial_count)
                QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
                state["trials_queued"] += 1
                if int(dialog.trial_count) != trial_count_before + 1:
                    fail(
                        "manual-refuel trial click produced no authoritative trial "
                        f"increment: before={trial_count_before} "
                        f"after={int(dialog.trial_count)}"
                    )
                    return
                state["phase"] = "wait_trial"
                reschedule()
                return
            if state["phase"] == "wait_trial":
                if not self.context.machine.check_if_all_completed():
                    reschedule()
                    return
                state["phase"] = (
                    "queue_trial"
                    if state["trials_queued"] < trial_count
                    else "record_outcome"
                )
                reschedule()
                return
            if state["phase"] == "record_outcome":
                button = getattr(dialog, control_name)
                if not button.isVisible() or not button.isEnabled():
                    fail("manual-refuel outcome control is unavailable")
                    return
                QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
                record = current_record()
                if record is None or not record_matches(record, dialog):
                    fail("manual-refuel outcome did not persist the expected matching record")
                    return
                state["record"] = record
                if outcome == "passed" and dialog.close_button.text() != "Done":
                    fail("passed manual-refuel check did not expose the Done control")
                    return
                if capture_passed is not None:
                    capture_passed(record)
                state["phase"] = "close"
                reschedule()
                return
            if state["phase"] == "close":
                QtTest.QTest.mouseClick(
                    dialog.close_button, QtCore.Qt.MouseButton.LeftButton
                )
                state["phase"] = "wait_closed"
                reschedule()
                return
            if state["phase"] == "wait_closed":
                active_launch = bool(
                    getattr(pressure_box, "_manual_refuel_check_launch_is_active")()
                )
                if _qt_dialog_is_visible(dialog) or active_launch:
                    reschedule()
                    return
                state["phase"] = "done"

        with _expected_dialogs(
            self.app, ("Manual Refuel Check", "ManualRefuelCheckDialog")
        ):
            QtCore.QTimer.singleShot(0, advance)
            calibration.close()
            self.wait_until(
                lambda: state["error"] is not None or state["phase"] == "done",
                "manual-refuel modal completion",
                timeout_seconds=20.0,
            )
        if state["error"] is not None:
            raise state["error"]
        return {
            "dialog_title": "Manual Refuel Check",
            "trial_count": state["trials_queued"],
            "trial_droplet_count": trial_droplet_count,
            "outcome": outcome,
            "operator_judgment": operator_judgment,
            "record": dict(state["record"] or {}),
            "dialog_closed": True,
            "launch_pending": False,
        }


__all__ = [
    "ArrayDriver",
    "CalibrationDialogDriver",
    "ExperimentEditorDriver",
    "ExperimentLoaderDriver",
    "MachineControlsDriver",
    "ManualRefuelCheckDriver",
    "MainWindowDriver",
    "RackDriver",
]
