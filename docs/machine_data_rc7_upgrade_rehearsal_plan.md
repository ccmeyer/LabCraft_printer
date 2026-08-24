# Exact-Tag Pi Upgrade Rehearsal

Status: `implemented - focused Windows validation passed; Pi qualification pending`

This runbook proves the public online update and first-start migration path from
two preserved legacy cohorts to one exact release. It never rolls back either
established Pi worktree and never removes or repoints an existing machine-data
store.

Implementation validation on 2026-08-24 passed 229 focused Windows tests
covering the supervisor, bootstrap-only runner, migration/bootstrap services,
update preservation, and legacy updater. The initial harness passed Pi dry-run,
exact development sync/validation, and 222 Pi tests with two Windows-only
skips. The corrected harness must be republished and requalified before a fresh
rc.1 run; the real rc.6 source-wrapper path is still pending.

The first rc.1 `Prepare` attempt, run
`6b974bd5-74fe-4c54-a557-8a62a86ca5a4`, failed before preparation because the
supervisor expected a persisted `production_ready` firmware field. Firmware
state v1 derives that value from `role == released`. The failed root remains
quarantined; the corrected harness validates the real schema and derives the
readiness result without altering firmware state.

Fresh rc.1 run `2b9668d7-ed43-4883-9c65-9a6782a23362` then failed closed
because the Pi Git version reports a missing ref as exit 128 unless
`show-ref --quiet` is used. The run is also quarantined. The corrected harness
uses Git's quiet exact-ref predicate so an absent target tag passes while a
present tag or any other command failure remains blocking.

Fresh rc.1 run `8007ee51-bb73-4c89-9e9c-6afc29cd4c17` prepared and updated
successfully, proving the exact legacy updater path and protected invariants.
Its cancellation gate then failed before opening a window because the
bootstrap-only runner compared the migration service's normalized
`wrapper/local` source with the wrapper directory itself. The run remains
quarantined at `updated`. The corrected runner binds both the selected wrapper
kind and its exact normalized `local/` directory before any UI is shown.

For the rc.7 campaign the required source and target bindings are:

| Role | Tag | Peeled commit |
| --- | --- | --- |
| Legacy cohort 1 | `v1.2.0-rc.6` | `199807eea95a238896137bddb2a83d3d892e2aab` |
| Legacy cohort 2 | `v1.3.0-rc.1` | `922f2ac65eab2ff1f63ffc0719a98b777bc2128f` |
| Target | `v1.3.0-rc.7` | `b6138f9d029289385812fe80c276e0eddea90c23` |

Each source must be a genuine preserved wrapper containing exactly the
applicable `VERSION` and a complete `local/`. Synthetic fixtures remain useful
for automated regression, but they do not satisfy this campaign's source-data
gate.

## Safety and isolation contract

The workflow creates a standalone clone and two fresh external destination
roots for each cohort. It does not change:

- `/home/labcraft/LabCraft_printer`;
- `/home/labcraft/LabCraft_printer-dev`;
- the production or development machine-data stores;
- the development-workflow binding or shared Python environment; or
- installed firmware or durable firmware state.

Every mutation stays below:

```text
/home/labcraft/.local/share/LabCraft/LabCraft Printer/
  development-workflow/upgrade-rehearsals/<run-id>/
```

A new run ID is the reset mechanism. There is deliberately no cleanup action.
Failed and successful roots remain available for review. Never delete an
existing external store to repeat a rehearsal.

The visible process constructs only `MachineDataBootstrapDialog` and
`MachineDataBootstrap`. It closes the authorized context after activation and
never imports the main App, MVC, machine communications, physical factories,
updater UI, or firmware tools.

## Prerequisites

Before `Prepare`:

1. Commit and push the exact Windows harness revision; the worktree must be
   clean and attached to a configured upstream.
2. Close the production and development applications and every updater, DFU,
   flash, and HIL process.
3. Confirm the Pi production and development checkouts are clean.
4. Confirm durable firmware state is `released` and `production_ready=true`.
5. Mount the medium containing the source wrapper, or use a preserved Desktop
   copy. Record its absolute Pi path and expected machine ID.
6. Keep private paths and coordinates out of tickets and tracked documents.

The source medium may be ejected after `Prepare` reports a matching owned-copy
tree hash. All later actions use that private owned copy.

## Common command values

Run commands from the Windows repository root. Substitute the source path,
machine ID, and operator. The identity path below is the established Pi
development identity.

```powershell
$piHost = "192.168.0.33"
$identity = "verification_reports\pi_sil_codex_network_ed25519"
$operator = "Operator Name"
$target = "v1.3.0-rc.7"
```

Preview any action by adding `-DryRun`. Dry-run performs no SSH, Git mutation,
evidence write, bootstrap, or hardware action.

## Cohort sequence

Run the complete sequence once for rc.6 and once for rc.1. Do not reuse a run
ID or a migrated root across cohorts.

### 1. Prepare

Rc.6 example:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Prepare `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -SourceRelease "v1.2.0-rc.6" `
  -TargetRelease $target `
  -SourceWrapper "/absolute/pi/path/to/rc6-preserved-wrapper" `
  -ExpectedMachineId "EXPECTED-MACHINE-ID" `
  -Operator $operator
```

For rc.1, change `-SourceRelease` to `v1.3.0-rc.1`, select that
cohort's wrapper, and provide its expected machine ID.

Record the returned run ID. `Prepare` proves the public annotated tags, copies
the source privately, creates a no-tags standalone clone at the old release,
binds its temporary branch to `origin/main`, copies the ignored `local/`, and
proves the target tag is absent before update.

### 2. Inspect status

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Status `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -RunId "<run-id>"
```

Require stage `prepared`, matching protected invariants, and zero related
processes.

### 3. Run the old updater

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Update `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -RunId "<run-id>" `
  -Operator $operator
```

The old tag's own `tools/update_and_restart.py` must fetch and advance to the
exact target tag. It uses `--no-relaunch`; its log and result are outside the
clone. Both copies of the legacy source must remain byte-identical.

### 4. Pass the cancellation gate

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Cancel `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -RunId "<run-id>" `
  -Operator $operator
```

In the visible bootstrap window:

1. Confirm the title identifies the expected target and `CANCEL` outcome.
2. Click **Inspect selected source** and review that the correct cohort is
   shown.
3. Press the dialog's **Cancel** button. Do not press **Create verified backup
   and activate**.

The action passes only when no active pointer, canonical machine, or durable
migration file was created in the cancellation destination. Activating by
mistake fails this gate and preserves the attempt for investigation.

### 5. Activate the separate success root

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Activate `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -RunId "<run-id>" `
  -Operator $operator
```

The source, machine ID, operator, and reason are bound by the harness. Inspect
the source and review every location, Camera coordinate, rack, plate, Settings
value, version, ownership finding, and preset warning. Supply a genuine
independent service-record reference when the dialog requires one. Check the
Camera-preservation and complete-source acknowledgements, then click **Create
verified backup and activate**.

After activation the dialog closes. The main application must not appear.

### 6. Verify and seal the cohort

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Verify `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -RunId "<run-id>" `
  -Operator $operator
```

This performs headless ready reopens from the updated clone and a second clean,
detached target checkout. It validates all migration/activation evidence,
raw copied members, semantic configuration, Camera and other safety values,
target authorization, deployment binding, source immutability, and protected
postflight invariants. Passing state is `verified` with a private Pi seal.

## Aggregate the rc.7 campaign

After both cohorts reach `verified`:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_upgrade_rehearsal.ps1 `
  -Action Summarize `
  -PiHost $piHost `
  -SshIdentityFile $identity `
  -RunId "<rc6-run-id>","<rc1-run-id>" `
  -Operator $operator
```

The campaign passes only when the sources are distinct, both runs share one
exact target tag and commit, both are sealed, and their protected invariants
still match. The Windows report contains only hashes, counts, tags, commits,
states, and the private Pi report path.

## Evidence and failure handling

Private Pi evidence includes complete source copies, clones, logs, receipts,
machine data, and exact coordinates. Sanitized Windows evidence is written
beneath ignored `verification_reports/upgrade-rehearsal/`.

If any action fails:

- stop the affected and downstream actions;
- do not edit its state, receipts, source, clone, or machine data;
- use `Status` for read-only diagnosis, but do not rerun any mutating action on
  a run that has a failure receipt;
- preserve the run root and its failure receipt; and
- diagnose the named gate before preparing a new run ID.

The rehearsal proves the updater and data migration mechanism with real source
bytes. It does not prove that a position is physically correct for another
printer and it does not deploy target firmware. Fleet rollout still requires a
paused pilot from each cohort, exact firmware pairing, and machine-specific
physical review before expansion.
