# Milestone 7 rc.3 Protected-Update Correction Plan

Status: `in_progress`

Prepared: 2026-08-20

Target release: `v1.3.0-rc.3`

Superseded release target: immutable `v1.3.0-rc.2` tag at `d59f73be`

## Finding and safety boundary

The attended LC-001 update from enrolled rc.2 stopped before Git with
`source_binding_mismatch`. The running app supplied the historical
12-character commit `5f54a4a174cd`; the updater compared it literally with the
same Git `HEAD` expressed as a full 40-character commit. No preservation
transaction was created, and production `HEAD`, the active pointer, deployment
anchor, and all protected machine-data bytes remained unchanged.

The affected call path is:

```text
Firmware tab
-> View update action
-> Controller._build_app_updater_base_command
-> AppVersion.get_app_commit
-> tools/update_and_restart._begin_machine_data_protection
-> MachineDataUpdate deployment-anchor and preservation transaction
```

The failure is before Model, machine communications, firmware, pressure, or
motion. This plan changes no device protocol, firmware, route, coordinate, or
timing behavior.

## Required implementation sequence

1. Add regression tests for full app commit binding, the exact historical
   12-character rc.2 prefix, unsafe prefix rejection, and target bootstrap
   after a full deployment anchor is written.
2. Make new app launch bindings use the full canonical Git commit.
3. Permit only an exact 12-character lowercase hexadecimal historical prefix
   to match a full commit that starts with it; canonicalize all new transaction
   evidence to the full commit.
4. Allow an existing short rc.2 genesis anchor to validate against its exact
   full commit without rewriting that immutable historical evidence.
5. Add a narrow attended rc.2 recovery launch mode. It must derive machine
   identity from the authorized store, require the retained
   `source_binding_mismatch` log, prohibit manually supplied identity fields,
   and require a clean separate updater checkout whose commit equals the exact
   requested target tag. Permit direct legacy-to-rc.3 first-start genesis only
   when activation and
   verification evidence were created by that exact rc.3 app; do not allow rc.3
   to recreate a missing rc.2 deployment anchor.
6. Prepare rc.3 metadata without moving or deleting the rc.2 tag, then run the
   focused, full, release, static, and contained Windows gates.
7. Qualify the exact rc.3 commit on the Pi in disposable roots, including the
   recovery-binding lane and target reopen, while proving production Git,
   machine data, and hardware remain untouched.
8. After explicit tag authorization, create and verify the immutable rc.3 tag,
   stage it on LC-001, close the retained rc.2 error window, and run the
   attended recovery UI. Verify the pre-update archive, exact protected-byte
   preservation, target `HEAD`, full deployment anchor, immutable receipts,
   manual normal-app reopen, and unchanged location/Camera evidence.

## Files in scope

- `FreeRTOS-interface/AppVersion.py`
- `FreeRTOS-interface/MachineDataUpdate.py`
- `tools/update_and_restart.py`
- focused app-version, deployment-anchor, preservation, updater, Controller,
  and updater-window tests
- `VERSION`, `CHANGELOG.md`, `releases/latest.json`, and
  `releases/v1.3.0-rc.3.json`
- the machine-data live plan, Milestone 7 implementation/completion records,
  and update/recovery runbook

`Controller.py`, `View.py`, `Model.py`, `Machine_FreeRTOS.py`, firmware,
protocol, motion, pressure, and configuration coordinates are out of scope.

## Qualification gates

- Exact legacy prefixes match only their corresponding full commit.
- Shorter, uppercase, non-hexadecimal, and mismatched bindings fail before a
  transaction or Git command.
- A short rc.2 genesis anchor permits a protected update whose new intent and
  target anchor contain full commits.
- The target bootstrap reopens using the new full anchor.
- Direct legacy-to-rc.3 first start creates a genesis anchor bound to rc.3's
  exact activation/verification evidence; rc.3 rejects a missing rc.2 anchor.
- Recovery mode rejects a wrong source version, non-genesis/full anchor,
  missing failure evidence, supplied identity, dirty candidate, candidate/tag
  mismatch, rollback, offline mode, wait-PID launch, and automatic relaunch.
- The normal app-generated rc.3 command contains a full source commit.
- Focused and full Python suites, release metadata, JSON parsing,
  `git diff --check`, changed-file compilation, firmware identity, Windows SIL,
  disposable Pi focused tests, and private-device Pi SIL pass.
- The attended LC-001 transaction proves exact protected-byte preservation and
  manual target reopen before any remaining HIL or Camera-route work.

## Rollback and stop rules

Before attended deployment, leave LC-001 on its unchanged rc.2 checkout and
preserve the failed updater/launcher logs. Do not edit the deployment anchor,
copy files into the canonical store, or mutate production Git directly.

After a successful protected update, use only the Milestone 6 receipt-gated
rollback/compatibility workflow. Any target mismatch, backup failure,
protected-byte drift, recovery-only result, startup authorization error, or
unexpected hardware access stops the sequence and preserves all evidence.

## Implementation and Windows validation record

Implementation is complete pending the dedicated candidate commit and
disposable Pi qualification.

- New app-generated bindings use full 40-character Git commits.
- Historical compatibility accepts only the exact 12-lowercase-hex prefix and
  canonicalizes the live transaction binding to full `HEAD`.
- Existing rc.2 short genesis anchors validate against that exact full commit;
  all new update anchors remain full.
- The recovery launcher derives all machine identity fields from the external
  authorized store and checks the retained failure log, source version/anchor,
  clean target checkout, target VERSION, and exact target tag commit.
- Direct legacy-to-rc.3 first start is permitted only when activation and
  verification receipts bind to the exact rc.3 app; a missing rc.2 anchor is
  rejected.
- Firmware, protocol, Controller, View, Model, machine communication, motion,
  pressure, coordinates, and machine-data schema were not changed.

Final pre-commit Windows gates on this code/release tree passed:

- focused M1-M7 matrix: 602 passed, 1 skipped, 130 warnings;
- complete Python suite: 5,430 passed, 156 skipped, 605 warnings;
- contained `virtual_print_array_96_v1`: 96/96, exit 0;
- changed Python compilation, release metadata validation, every release JSON,
  `git diff --check`, and the rc.2-to-rc.3 firmware diff passed;
- firmware artifact remained SHA-256
  `EDA070CE734D5167F0795FAF30DF461C8A07341E09CA698DE9D850315B0D5884`.

The complete suite and SIL were rerun after adding the direct rc.3 genesis
evidence gate; earlier passing runs are diagnostic only and are not counted as
the final candidate gate.
