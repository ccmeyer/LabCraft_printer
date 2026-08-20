# Milestone 3 First-Start and Support Guide

Applies to the first `v1.3.0-rc.2` launch when updating a deployed printer from
`v1.2.0-rc.6` or `v1.3.0-rc.1`.

## Before launching rc.2

1. Keep the Milestone 0 copies of the complete legacy `local/` directory and
   `VERSION` file on both the Desktop and the external drive.
2. Do not rename, edit, merge, or delete files inside either backup.
3. Close every LabCraft checkout. Only one checkout may control or migrate a
   printer at a time.
4. Keep the machine in a safe, stationary state with the operator stop control
   available. Bootstrap itself does not connect to or move hardware.
5. Have the printer's exact machine display ID, the operator name, and the
   reason for choosing the source ready. If the displayed Camera values match a
   historical preset, also have an independent service-record reference.

The file hash mentioned in early planning is not a separate operator task. rc.2
creates, stores, and reopens the required hashes automatically. The preserved
whole-directory copies are the required human-created backup evidence.

## What appears on first start

The machine-data verification window opens before Settings, the normal main
window, cameras, serial ports, balance services, or the machine controller are
constructed.

1. The current checkout's direct `local/` directory is offered when it exists,
   but it is never inspected or approved silently. After an update, prefer the
   preserved wrapper containing the pre-update `local/` and `VERSION` so the
   displayed source version remains authoritative.
2. The operator may instead browse to:
   - the saved `local/` directory;
   - a parent folder containing `local/` and `VERSION`; or
   - a ZIP containing the preserved source.
3. Select **Inspect selected source**. Inspection and hashing run in a worker;
   the source is not modified.
4. Review the declared version, identity state, CalibrationMemory state,
   preset warnings, every saved location, all four corners of every calibrated
   plate, and any comparison with another inspected candidate.
5. If candidates conflict, choose the one known to belong to this physical
   printer and enter a specific source-selection reason. Do not combine the
   directories.
6. Type the machine display ID and operator name. Camera X, Y, and Z are copied
   directly from immutable inspected evidence and displayed read-only; review
   them, then check the separate Camera-preservation approval. Do not transcribe
   the coordinates.
7. Enter the independent service-record reference when the dialog reports a
   preset or Camera preset match.
8. Check the source/target attestation only after reviewing all displayed
   targets, then start backup/migration/activation.

The app creates a verified source archive, copies into the external
per-machine store, reopens and verifies every artifact, records separate source
and target verification, writes an activation receipt, and writes the active
pointer last. The original selected source remains untouched.

## Successful completion

The normal splash and main window appear only after all evidence has been
validated and the per-machine configuration lock is held. Later launches from
another checkout under the same OS account reuse the same external machine
store and do not read that checkout's `local/` configuration.

The normal main window does not currently present the canonical machine ID and
hardware profile clearly enough to serve as verification evidence. Before
commanding movement, print and record both values from the authorized pointer
and canonical Settings as shown in Step 4. A main-window screenshot proves that
normal startup completed, not which identity/profile was authorized. Milestone
7 still owns the controlled physical-route validation; completing bootstrap
alone is not authorization to skip that checklist.

## Exact target-Pi first-start validation

Run this validation from the Milestone 3 commit before using its normal desktop
launcher or production external store. It uses a disposable root beneath
`/tmp`, so the later production first start is still a real first start.

### 1. Make hardware physically unavailable

1. Close every LabCraft window and updater process.
2. Engage the operator stop control and remove motion/pressure power.
3. Physically disconnect the controller USB/serial connection. Do not rely on
   an application checkbox or a port-selection setting for this gate.
4. Keep both Milestone 0 backups untouched and connected/readable.
5. Run the commands as the normal desktop operator account, not with `sudo`.

From the repository root, confirm the checkout and interpreter:

```bash
current_repo="$(pwd -P)"
validation_python="$current_repo/venv/bin/python"
git status --short
git rev-parse HEAD
"$validation_python" --version
```

`git status --short` must print nothing. If this Pi uses `.venv/bin/python` or
`env/bin/python`, change only the `validation_python` assignment to that
absolute path and repeat the version command.

Create and select an isolated root outside the checkout:

```bash
validation_parent="$(mktemp -d /tmp/labcraft-m3-first-start.XXXXXX)"
validation_root="$validation_parent/machine-data"
export LABCRAFT_MACHINE_DATA_ROOT="$validation_root"
printf 'Validation parent: %s\nMachine-data root: %s\n' \
  "$validation_parent" "$LABCRAFT_MACHINE_DATA_ROOT"
```

Both printed paths must start with `/tmp/labcraft-m3-first-start.`. Stop if
either path is empty, inside the repository, or is the intended production
machine-data root.

### 2. Prove cancellation is hardware-free

Launch the app from that terminal:

```bash
"$validation_python" FreeRTOS-interface/App.py
cancel_exit=$?
printf 'Cancel exit code: %s\n' "$cancel_exit"
```

Confirm that the machine-data verification window is the only actionable
window. Cancel on its source page. The shell must report exit code `2`; no
normal splash/main window, serial connection, camera construction, or motion
may occur. Repeat once after selecting the Milestone 0 source and pressing
**Inspect selected source**, then cancel from the review page. Do not press the
activation button during these cancellation runs.

### 3. Complete one isolated first start

Launch the same command again. In the verification window:

1. Choose **Browse folder** and select the preserved wrapper directory that
   contains both `local/` and `VERSION`. Selecting the preserved `local/`
   directory itself or its ZIP is also supported.
2. Select **Inspect selected source**.
3. Confirm the displayed source version is the expected deployed cohort,
   `v1.2.0-rc.6` or `v1.3.0-rc.1`.
4. Compare every displayed location, rack pair, and four-corner plate
   calibration with the preserved source. Give Camera X/Y/Z their own review.
5. Enter the physical printer's display ID, operator name, and a specific
   reason such as `Milestone 0 backup from <date> for <printer ID>`.
6. Review the read-only Camera X, Y, and Z integers populated from the inspected
   source, then check the separate approval to preserve that exact Camera
   position. No coordinate transcription is required.
7. If a preset warning is displayed, enter the real independent service-record
   reference. Stop rather than inventing a reference if none exists.
8. Check the source/target attestation, then select **Create verified backup and
   activate**.

The main window may appear only after activation succeeds. Take a screenshot
as startup-lifecycle evidence and close the app normally without requesting any
motion, pressure, camera, balance, or other hardware operation. Verify machine
identity and hardware profile from canonical evidence in Step 4 rather than
assuming the current main window displays them.

### 4. Record and reopen the activation evidence

Resolve the created machine directory and check the required evidence:

```bash
active_json="$validation_root/active_machine.json"
machine_uuid="$("$validation_python" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["machine_uuid"])' "$active_json")"
machine_root="$validation_root/machines/$machine_uuid"

"$validation_python" -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p["schema_version"] == 2; print("Authorized pointer:", p["machine_id"], p["machine_uuid"], p["activation_id"], p["migration_id"])' "$active_json"

"$validation_python" -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); s=json.load(open(sys.argv[2], encoding="utf-8")); print("Authorized machine ID:", p["machine_id"]); print("Canonical hardware profile:", s.get("HARDWARE_PROFILE", "current"))' "$active_json" "$machine_root/config/Settings.json"

missing_evidence=0
for evidence_path in \
  "$machine_root/metadata/machine_identity.json" \
  "$machine_root/metadata/candidate_evidence.json" \
  "$machine_root/metadata/migration_receipt.json" \
  "$machine_root/metadata/migration_tree_manifest.json" \
  "$machine_root/metadata/verification.json" \
  "$machine_root/metadata/activation_receipt.json"
do
  if test -f "$evidence_path"; then
    printf 'Found: %s\n' "$evidence_path"
  else
    printf 'Missing: %s\n' "$evidence_path"
    missing_evidence=1
  fi
done

if test "$missing_evidence" -ne 0; then
  printf 'STOP: required evidence is missing; preserve this terminal output and contact support.\n'
else
  sha256sum \
    "$active_json" \
    "$machine_root"/metadata/*.json \
    "$machine_root/config/Settings.json" \
    | tee "$validation_parent/evidence-sha256.txt"
fi
```

Do not replace a filename merely to test this loop, and do not add `exit` to a
command pasted into the interactive operator shell. A new terminal does not
remove the disposable root, but shell variables must be assigned again.

Run the domain-level reopen check. It reacquires and releases the canonical
configuration lock but does not construct application hardware:

```bash
PYTHONPATH="$current_repo/FreeRTOS-interface" \
  "$validation_python" - "$current_repo" <<'PY'
import sys
from pathlib import Path

from AppVersion import get_app_commit, get_app_version
from MachineData import resolve_machine_data_base
from MachineDataBootstrap import MachineDataBootstrap

repo = Path(sys.argv[1]).resolve()
base = resolve_machine_data_base(app_local_data_root=repo.parent, repo_root=repo)
bootstrap = MachineDataBootstrap(
    base,
    app_version=get_app_version(repo),
    app_commit=get_app_commit(repo),
)
print("Inspection state:", bootstrap.inspect().state.value)
context = bootstrap.open_ready()
try:
    print("Authorized machine:", context.identity.machine_id, context.paths.machine_uuid)
    print("Canonical root:", context.paths.machine_root)
finally:
    context.close()
PY
```

Expected inspection state is `ready`, and the canonical root must be beneath
the disposable `validation_root`, never beneath either checkout.

### 5. Prove a second checkout reuses the same store

Create a detached disposable worktree. It intentionally has no untracked
legacy `local/` directory:

```bash
second_checkout="$validation_parent/second-checkout"
git worktree add --detach "$second_checkout" HEAD
test ! -e "$second_checkout/local"
(
  cd "$second_checkout"
  "$validation_python" FreeRTOS-interface/App.py
)
second_exit=$?
printf 'Second-checkout exit code: %s\n' "$second_exit"
```

The verification window should briefly report that verified external data is
ready and revalidate it without asking for a source. The normal main window is
not expected to display the canonical machine ID/profile clearly; use the Step
4 evidence output for those values. Close without hardware actions. The exit
code must be `0`.

### 6. Prove corruption cannot fall back to legacy data

With the app closed, change one byte only in the disposable canonical
`Settings.json`, while keeping its recovery copy outside `machine-data`:

```bash
settings_path="$machine_root/config/Settings.json"
settings_recovery="$validation_parent/Settings.before-corruption.json"
cp -- "$settings_path" "$settings_recovery"
printf ' ' >> "$settings_path"
(
  cd "$second_checkout"
  "$validation_python" FreeRTOS-interface/App.py
)
corruption_exit=$?
printf 'Corruption exit code: %s\n' "$corruption_exit"
```

Dismiss the recovery messages. The exit code must be `4`, and no normal main
window or hardware construction may appear. Restore the exact bytes and prove
revalidation succeeds:

```bash
cp -- "$settings_recovery" "$settings_path"
(
  cd "$second_checkout"
  "$validation_python" FreeRTOS-interface/App.py
)
restored_exit=$?
printf 'Restored exit code: %s\n' "$restored_exit"

sha256sum -c "$validation_parent/evidence-sha256.txt" \
  | tee "$validation_parent/restored-evidence-check.txt"
```

The app must reuse the verified store and exit `0` after the operator closes
the main window without hardware actions. Every baseline entry, including
canonical Settings, must then report `OK`.

### 7. Re-run the zero-command safety tests on the Pi

```bash
"$validation_python" -m pytest -q \
  tests/test_controller_saved_target_authorization.py \
  tests/test_app_machine_data_bootstrap.py
```

Both files must pass. They exercise the defense-in-depth Controller gate and
prove denied Camera/rack/plate and failed/cancelled bootstrap paths queue zero
machine commands.

Record the commit, paths, exit codes, test result, screenshot filename, and
`evidence-sha256.txt` in the Milestone 3 validation record. Keep the disposable
root until the evidence has been reviewed. Then remove the worktree with
`git worktree remove "$second_checkout"`, unset the override with
`unset LABCRAFT_MACHINE_DATA_ROOT`, and arrange support-reviewed cleanup of the
exact printed `validation_parent`. Never delete or edit either Milestone 0
backup or the real production machine-data root.

### If the initial evidence snapshot was missed

Do not create a later file and describe it as the original baseline. Preserve
the reason the snapshot was missed, re-run hardware-free bootstrap validation,
confirm any restored file against its byte-for-byte recovery copy, and create a
separately named closeout snapshot. Qualification must explicitly review and
record that exception before accepting it; otherwise repeat the entire
disposable validation from a fresh root.

### If startup prints a message but no window appears

Do not enable or reconnect hardware. Record the deployed commit, validation
root, process ID, and terminal output before terminating the process. Commit
`08d41bc2` fixes the target-Pi Qt/Python race in which a worker result closed the
dialog before `QThread.finished`; earlier commits must not be used to complete
this validation. Update both the primary checkout and any detached validation
worktree to the same corrected commit before retrying.

## Cancel, interruption, and recovery

- **Cancel before work starts:** the app exits without constructing the normal
  hardware-capable application.
- **Cancel during a write:** cancellation is honored at a durable checkpoint.
  The worker is not force-terminated, and evidence is preserved for resume.
- **Power loss after identity assignment:** reselect the same source. rc.2
  reuses the durable machine UUID, activation ID, and migration ID.
- **Copied-unverified or activation-staged state:** use the offered resume path;
  do not start a second migration.
- **Recovery required, hash mismatch, unknown file, multiple machine roots, or
  identity conflict:** stop. Copy the displayed diagnostic text and preserve
  the entire external machine-data directory plus both Milestone 0 backups.
  Do not delete lock, journal, receipt, temporary, or active-pointer files to
  make the warning disappear.
- **Configuration lock unavailable:** close the other LabCraft process or
  support tool, then relaunch. Never run two checkouts against the same active
  store.

Startup exit codes are: `1` already running, `2` operator cancellation, `3`
bootstrap/startup failure, `4` evidence recovery required, and `5` canonical
configuration lock unavailable.

## Rollback warning

Before fleet deployment, the Milestone 3 code commit can be reverted while the
untouched legacy `local/` source is still authoritative. After rc.2 has been
used for production and canonical values may have changed, do not simply
install rc.6 or rc.1: those versions cannot see later canonical edits. Preserve
all data and use the Milestone 6 hash-verified compatibility-export/support
procedure.
