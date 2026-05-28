# App Update and Restart Plan

## Summary

Add an operator-friendly way to update the Python application from inside the main app while keeping update mechanics outside the running app process.

The recommended design is a hybrid:

- The main app exposes an `Update App` action for operators.
- The app confirms the action, safely disconnects from the MCU using the existing close path, and exits.
- A separate updater process waits for the main app to close, runs a conservative Git update, reports progress, and relaunches the app.

This feature should update only application code and local Python-side assets. It must not change firmware protocol behavior, flash firmware, force-reset the repository, or try to resolve Git conflicts for an operator.

## Target Call Path

Planned app path:

`MainWindow Update App action -> Controller update request -> existing close/disconnect flow -> Machine.disconnect_board() -> GOODBYE/BYE_ACK/BYE_DONE -> app exits -> updater process -> git pull --ff-only -> relaunch FreeRTOS-interface/App.py`

Existing safety path to reuse:

1. `MainWindow.closeEvent(...)` checks whether the machine is connected.
2. If connected, it asks the operator to disconnect and close.
3. `_begin_close_disconnect()` calls `Controller.disconnect_machine()`.
4. `Controller.disconnect_machine()` calls `Machine.disconnect_board()`.
5. `Machine.disconnect_board()` sends `GOODBYE`, waits for `BYE_ACK`/`BYE_DONE` when possible, closes serial, and emits `disconnect_complete_signal`.
6. `MainWindow._handle_close_disconnect_complete()` closes the window.

The update feature should build on this path rather than adding a second machine shutdown path.

## Operator Flow

The intended operator experience:

1. Operator clicks `Update App`.
2. Main app shows a confirmation:
   - The app will disconnect from the machine if needed.
   - The app will close.
   - A LabCraft updater window will show progress.
   - The app will reopen automatically when finished.
3. If the machine is connected, the existing disconnect progress dialog appears.
4. Main app exits.
5. Updater window appears and shows progress:
   - `Waiting for LabCraft to close...`
   - `Checking local checkout...`
   - `Checking for updates...`
   - `Downloading update...`
   - `Applying update...`
   - `Starting LabCraft...`
6. On success, the updater relaunches the app and exits.

If update cannot proceed, the updater should show a clear error and offer `Reopen Current Version`.

## Safety Rules

- Do not run update while motion, printing, calibration, firmware flashing, or queued hardware work is active.
- Do not change device protocol, firmware opcodes, message parsing, or firmware flashing behavior.
- Do not run `git reset`, `git clean`, `git checkout`, `git stash`, or merge conflict resolution from the operator update path.
- Use `git pull --ff-only` or an equivalent `fetch` plus fast-forward-only update.
- Treat a dirty worktree as a stop condition.
- Treat a divergent branch or non-fast-forward update as a stop condition.
- Leave the repo at the previous commit on failure whenever Git has not completed a clean fast-forward.
- Log the previous and resulting commit SHAs for support.

## Failure Behavior

Dirty worktree:

- Detect with `git status --porcelain`.
- Stop before pulling.
- Show: `Update cannot continue because this installation has local developer changes. The current app version was not changed. Please contact support.`
- Offer `Reopen Current Version`.

Local changes that would conflict with remote updates:

- The updater should normally catch this as a dirty worktree before pull.
- It should not stash or overwrite those changes.
- The repo remains on the existing commit.

Remote branch requires a merge or rebase:

- `git pull --ff-only` fails.
- Show: `Update cannot continue because this checkout cannot fast-forward cleanly. The current app version was not changed. Please contact support.`
- Offer `Reopen Current Version`.

Network, credentials, or GitHub failure:

- Show a concise failure message plus the Git command output summary.
- Leave the repo unchanged.
- Offer `Reopen Current Version`.

Dependency mismatch after update:

- First implementation should not automatically install dependencies.
- If the relaunched app fails, the updater log should preserve the update result and support should fix dependencies manually.
- A later slice may add a conservative dependency check/update step if operator machines need it.

Relaunch failure:

- Keep the updater window open.
- Show the app launch command and log path.
- Offer `Retry Launch` and `Close`.

## Slice 1: Standalone Updater Backend

Purpose:

Build and test the update mechanics without main-app lifecycle changes.

Likely files:

- `tools/update_and_restart.py`
- `tests/test_update_and_restart.py`
- `docs/app_update_plan.md`

Responsibilities:

- Accept repo path, app PID, Python executable, app entrypoint, and optional log path.
- Wait for the app PID to exit when provided.
- Verify the path is a Git checkout.
- Record current branch and current commit SHA.
- Check for local changes with `git status --porcelain`.
- Run a fast-forward-only update.
- Record the resulting commit SHA.
- Relaunch the app only after a clean update or after a blocked/failed update when the operator chooses to reopen.

Implemented CLI shape:

Primary Raspberry Pi command:

```bash
venv/bin/python tools/update_and_restart.py --repo-root . --wait-pid <pid>
```

Primary Windows command:

```powershell
.\env\Scripts\python.exe tools\update_and_restart.py --repo-root . --wait-pid <pid> --python .\env\Scripts\python.exe --app FreeRTOS-interface\App.py
```

If `--python` is omitted, the updater chooses a repo-local interpreter in the same order as the Pi desktop launcher:

- Linux/Pi: `venv/bin/python`, then `.venv/bin/python`, then `env/bin/python`, then the current interpreter.
- Windows: `env/Scripts/python.exe`, then `.venv/Scripts/python.exe`, then `venv/Scripts/python.exe`, then the current interpreter.

Testing focus:

- Clean checkout with no updates is handled.
- Dirty checkout blocks before pull.
- Fast-forward failure is surfaced cleanly.
- Git command failures return clear status objects.
- Relaunch command is built without depending on the current shell.

Done when:

- The updater can be run manually by a developer.
- Unit tests cover Git-state decision logic with fakes or temporary repos.
- No main app files are changed yet.

## Slice 2: Main App Integration

Purpose:

Add the app-side update request and safe shutdown handoff.

Likely files:

- `FreeRTOS-interface/View.py`
- `FreeRTOS-interface/Controller.py`
- `tools/update_and_restart.py`
- `tests/test_app_update_request.py` or focused view/controller tests

UI placement:

- Add `Update App` near other maintenance actions, likely in the existing Firmware/maintenance area, but keep it visually distinct from `Update Firmware`.
- The text must avoid implying that firmware will be flashed.

Responsibilities:

- Confirm the update request.
- Refuse the request when an unsafe app state is detected.
- Launch the external updater before the main app exits, passing the current app PID.
- Reuse the existing close/disconnect path for connected machines.
- Exit only after the updater process has started successfully.

Unsafe states to consider:

- Machine connected and disconnect refused by operator.
- Command queue not empty.
- Active print run, calibration process, qualification run, firmware update, or long-running worker.
- Updater already running.

Done when:

- A developer can trigger update from the app.
- The app disconnects through the existing close path before update.
- If updater launch fails, the main app stays open and shows an error.
- Focused tests cover request gating and updater command construction.

## Slice 3: Operator-Ready Updater Window

Purpose:

Make the updater understandable and recoverable for non-technical operators.

Likely files:

- `tools/update_and_restart.py`
- optional `tools/update_window.py` if the UI is split from update logic
- `README.md`
- `tests/test_update_and_restart.py`

Window requirements:

- Small titled window: `LabCraft Updater`.
- Progress/status text for each major step.
- Scrollable details or a `Show Details` area for Git output.
- Final success state before relaunch.
- Clear failure state with `Reopen Current Version`.
- Log path shown on failure.

Recommended log path:

- `local/update_logs/update_<timestamp>.log`

The `local/` directory is intended for untracked machine-local state.

Done when:

- An operator never sees a silent gap between app close and relaunch.
- Common failures produce readable messages.
- A blocked update can reopen the old app without support intervention.
- README/operator notes explain what support should ask for when an update fails.

## Validation

Documentation-only slice:

- Read the plan for completeness.
- No automated tests required.

Standalone updater validation:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py
```

Raspberry Pi validation:

```bash
venv/bin/python -m pytest -q tests/test_update_and_restart.py
venv/bin/python tools/update_and_restart.py --repo-root . --no-relaunch
```

Main app integration validation:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py
.\env\Scripts\python.exe -m pytest -q
```

Manual validation:

- Start the app from the repo virtualenv.
- Click `Update App`.
- Confirm the update.
- Confirm the updater window appears after the app closes.
- Confirm a clean no-op update relaunches the app.
- Create a harmless local test change and confirm update is blocked before pull.
- Disconnect network and confirm update failure leaves the current app version launchable.
- Confirm app update does not invoke firmware flashing or firmware update UI.

Firmware validation:

- Not required unless a later implementation changes files under `firmware/`.

## Rollback Plan

Documentation-only slice:

- Revert `docs/app_update_plan.md`.

Standalone updater slice:

- Stop using the updater script.
- Revert `tools/update_and_restart.py` and related tests.
- No app behavior changes should exist in this slice.

Main app integration slice:

- Hide or remove the `Update App` button/action.
- Revert controller/view update handoff code.
- Keep the standalone updater script only if it remains useful for developer support.

Operator window slice:

- Fall back to the standalone updater backend.
- Keep logs for diagnosing what failed.

Support rollback after a bad application update:

- Use the logged previous commit SHA.
- A technical maintainer can manually restore the previous revision.
- This should remain a support workflow, not an operator button.

## Open Questions

- Should the first operator-ready updater include dependency installation, or should dependency changes remain a support task?
- Should the app display the current commit/version in the main window before adding update support?
- Should update be allowed only from a specific branch, such as `main`, to avoid updating developer checkouts accidentally?
- Should the updater check remote availability before closing the app, or is closing first safer because it releases files and hardware resources?
- Should update logs include machine identity once a stable local machine ID exists?
