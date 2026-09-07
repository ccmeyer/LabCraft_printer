"""Bounded scripted Qt walkthrough; simulated dependencies, external evidence only."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(args):
    if args.visible:
        if os.name == "nt":
            os.environ["QT_QPA_PLATFORM"] = "windows"
        else:
            runtime = Path(f"/run/user/{os.getuid()}")
            sockets = sorted(p for p in runtime.glob("wayland-*") if not p.name.endswith(".lock"))
            if not sockets and not Path("/tmp/.X11-unix/X0").exists():
                raise RuntimeError("A visible Pi desktop session is required")
            os.environ.update(DISPLAY=":0", XDG_RUNTIME_DIR=str(runtime),
                              DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus",
                              QT_QPA_PLATFORM="wayland;xcb" if sockets else "xcb")
            if sockets:
                os.environ["WAYLAND_DISPLAY"] = sockets[0].name
    import tests.conftest  # Simulated dependencies; no production app or hardware factories.
    from PySide6.QtWidgets import QApplication
    from OptimizationJobs import optimization_job_manager
    from tools.optimizer_memory_qualification import state_digest, write_json
    from tools.optimizer_realistic_qualification import new_editor, new_wizard, close_owner, finish_input_events
    from tests.optimizer_qualification_cases import load_case, assert_physical_allocation

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    manager = optimization_job_manager()
    output = Path(args.output)
    screenshots = output.with_suffix(".screenshots")
    screenshots.mkdir()
    evidence = dict(schema_version=1, pid=os.getpid(), revision=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        platform=app.platformName(), visible=args.visible, complete=False, status="running", scenes=[], captures=[])
    if args.visible and app.platformName() in ("offscreen", "minimal"):
        raise RuntimeError("Visible walkthrough cannot use a headless Qt platform")
    stop = threading.Event()
    cancel = output.with_suffix(".cancel")
    def watch():
        while not stop.wait(.1):
            if cancel.exists(): manager.cancel()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    owners = []

    def capture(owner, label):
        finish_input_events()
        assert owner.isVisible()
        assert owner.grab().save(str(screenshots / f"{label}.png"))
        evidence["captures"].append(dict(name=label, window_size=[owner.width(), owner.height()],
            screen_available=list(owner.screen().availableGeometry().getRect()),
            status=owner.status_lbl.text()))
        ui = getattr(owner, "_optimization_ui", None)
        if ui and ui.dialog.isVisible():
            assert ui.dialog.grab().save(str(screenshots / f"{label}-progress.png"))

    def job(owner, action, label, *, slow_cancel=False, close_active=False):
        outcomes, phases, activities = [], [], []
        before = state_digest(owner.model) if slow_cancel or close_active else None
        terminal_times = []
        def finished(*values):
            terminal_times.append(time.monotonic())
            outcomes.append(values)
        owner.optimization_finished.connect(finished)
        def phase(_job_id, name): phases.append(name)
        manager.phase_changed.connect(phase)
        started = time.monotonic()
        canceled = None
        last_activity = None
        captured = False
        try:
            action()
            while not outcomes or manager.busy or (close_active and owner.isVisible()):
                app.processEvents()
                if cancel.exists() or time.monotonic() - started > 180:
                    manager.cancel(owner)
                    raise RuntimeError("Walkthrough canceled or scene exceeded three minutes")
                ui = getattr(owner, "_optimization_ui", None)
                if ui and ui.dialog.isVisible():
                    text = ui.dialog.labelText()
                    if text != last_activity and len(activities) < 48:
                        activities.append(text); last_activity = text
                    if not captured and time.monotonic()-started > 1:
                        capture(owner, label + "-working"); captured = True
                if canceled is None and slow_cancel and getattr(owner, "_slow_auto_update_paused", False):
                    assert not owner.auto_update_chk.isChecked()
                    capture(owner, label + "-slow-auto-paused")
                    canceled = time.monotonic()
                    owner._optimization_ui.cancel()
                if canceled is None and close_active and "Preparing candidates" in phases:
                    canceled = time.monotonic()
                    owner._allow_close_without_prompt = True
                    owner.close()
                time.sleep(.002)
            assert len(outcomes) == 1 and not owner._qualification_dialog_errors
            if slow_cancel or close_active:
                assert canceled is not None and not outcomes[0][0]
                assert state_digest(owner.model) == before
                assert owner._design_optimization_dirty
            else:
                assert outcomes[0][0], outcomes[0]
            if not close_active:
                capture(owner, label + "-complete")
            evidence["scenes"].append(dict(name=label, elapsed_seconds=time.monotonic()-started,
                phases=phases, visible_activity=activities, success=bool(outcomes[0][0]),
                cancellation_ms=(terminal_times[0]-canceled)*1000 if canceled else None,
                status=owner.status_lbl.text()))
            write_json(output, evidence)
            print(label + " complete", flush=True)
        finally:
            manager.phase_changed.disconnect(phase)
            owner.optimization_finished.disconnect(finished)

    try:
        write_json(output, evidence)
        manual = load_case("manual_groups")
        editor = new_editor(manual, True); owners.append(editor)
        job(editor, editor.run_btn.click, "manual-groups")
        assert editor.model._uploaded_reactions is None
        assert_physical_allocation(manual, editor.model)
        close_owner(app, editor); owners.remove(editor)

        imported = load_case("groups_import")
        wizard = new_wizard(imported, True); owners.append(wizard)
        job(wizard, wizard.calculate_btn.click, "import-groups-report")
        assert wizard.report["ok"] and wizard.apply_btn.isEnabled()
        assert "not imported" in wizard.status_lbl.text()
        payload = wizard.get_apply_payload()
        wizard.apply_btn.click()
        close_owner(app, wizard); owners.remove(wizard)
        editor = new_editor(imported, True); owners.append(editor)
        job(editor, lambda: editor._apply_uploaded_design_payload(payload), "import-groups-apply")
        assert_physical_allocation(imported, editor.model)
        close_owner(app, editor); owners.remove(editor)

        dense = load_case("dense_384_10")
        wizard = new_wizard(dense, True); owners.append(wizard)
        job(wizard, wizard.calculate_btn.click, "dense-import-report")
        assert wizard.report["ok"] and wizard.apply_btn.isEnabled()
        payload = wizard.get_apply_payload()
        close_owner(app, wizard); owners.remove(wizard)
        editor = new_editor(dense, True); owners.append(editor)
        job(editor, lambda: editor._apply_uploaded_design_payload(payload), "dense-import-apply")
        for index, reagent in enumerate(dense.reagents):
            editor._reagent_cell_widget(index, editor.COL_DROPLET).setValue(reagent.droplet)
        finish_input_events()
        job(editor, editor.run_btn.click, "dense-recalculate")
        assert_physical_allocation(dense, editor.model)
        editor.auto_update_chk.setChecked(True)
        editor._auto_timer.stop()
        editor._mark_design_optimization_dirty()
        job(editor, editor._recompute_silent, "dense-auto-cancel", slow_cancel=True)
        assert not editor._auto_timer.isActive() and not editor.auto_update_chk.isChecked()
        assert editor.run_btn.isEnabled()
        job(editor, editor.run_btn.click, "dense-explicit-recalculate")
        assert_physical_allocation(dense, editor.model)
        editor._mark_design_optimization_dirty()
        job(editor, editor.run_btn.click, "dense-active-close", close_active=True)
        close_owner(app, editor); owners.remove(editor)
        reopened = new_editor(manual, True); owners.append(reopened)
        assert reopened.run_btn.isEnabled()
        capture(reopened, "reopened-editor")
        evidence.update(status="passed", complete=True)
    except Exception as exc:
        evidence.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        for owner in owners:
            close_owner(app, owner)
        stopped = []
        manager.shutdown(lambda: stopped.append(True))
        while not stopped:
            app.processEvents(); time.sleep(.002)
        evidence["worker_stopped"] = manager._thread is None
        stop.set(); watcher.join(timeout=1)
        write_json(output, evidence)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from tests.optimizer_qualification_cases import require_external
    if not Path(args.output).is_absolute(): parser.error("Output must be an absolute external path")
    args.output = str(require_external(args.output))
    if args.worker:
        return run(args)
    from tools.optimizer_memory_qualification import supervise
    args.max_seconds = 600
    return supervise(args, [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:], "--worker"])


if __name__ == "__main__":
    raise SystemExit(main())
