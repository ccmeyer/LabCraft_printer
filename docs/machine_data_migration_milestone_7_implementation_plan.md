# Machine Data Migration Milestone 7: Qualification, Release, and Staged Deployment

Status: `in_progress` — Slices 1-4 passed on candidate `5f54a4a1`; Slice 0
attended assignments and Slices 5-7 remain.

Prepared: 2026-08-20

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Depends on:

- Milestone 0 off-device recovery copies (`verified`)
- Milestone 1 external machine-data contract `9b882141` (`verified`)
- Milestone 2 migration and backup engine `157db800` (`verified`)
- Milestone 3 production bootstrap `b3cf12ad` and lifecycle correction
  `08d41bc2` (`verified`)
- Milestone 4 configuration history `6925d029` and exact-byte restore
  correction `f6d65fd9` (`verified`)
- Milestone 5 guarded configuration changes `8b50872d` (`verified`)
- Milestone 6 update preservation `9e666291` and verification record
  `0ee3e50a` (`verified`)

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 7 converts the verified Milestones 0-6 implementation into one exact,
qualified, immutable release and then introduces that release to the fleet in
controlled stages. It is primarily a release-construction, system-
qualification, hardware-pairing, and deployment milestone. No new runtime
feature or safety policy is assumed necessary.

At completion:

- every required scenario is mapped to passing automated evidence;
- the exact release commit, release metadata, application version, and firmware
  requirement agree;
- the application is exercised from exact `v1.2.0-rc.6` and
  `v1.3.0-rc.1` source layouts through the real legacy updater boundary and the
  rc.2 first-start migration;
- disposable qualification on the target Pi passes through SSH without
  changing its production checkout, production machine-data root, or hardware;
- an attended designated-machine qualification proves app/firmware pairing,
  fail-closed target authorization, and the approved Camera route;
- support-guided legacy rollback and re-upgrade are rehearsed without adopting
  synthetic legacy changes;
- a local `v1.3.0-rc.2` tag and release-aware bundle pass their tag-dependent
  gates before anything is published;
- one controlled test machine, one deployed rc.6 machine, and one deployed
  rc.1 machine pass before the remaining fleet is offered rc.2; and
- private evidence is sealed outside Git while a sanitized completion record
  updates the parent plan.

Qualification is attached to an exact commit, not merely to a matching source
tree or version string. Any code, test, release-metadata, runbook, or firmware
change after candidate freeze creates a new candidate commit and invalidates
the affected evidence.

## Scope

### In scope

- Audit and close every Milestone 7 automated-scenario row.
- Add narrowly scoped regression tests only when the audit finds a real gap.
- Integrate the verified milestone branch into the release line.
- Create `v1.3.0-rc.2` version, changelog, release index, and manifest data.
- Validate online/local-remote and release-aware offline update behavior.
- Exercise exact rc.6 and rc.1 legacy updater processes against the local rc.2
  tag in disposable Pi repositories.
- Exercise first-start migration, activation, external-store reuse, update
  preservation, legacy rollback, and re-upgrade conflict behavior.
- Run Windows full-suite and release gates.
- Run focused tests and contained SIL on `labcraft@192.168.0.33` through SSH.
- Seal Windows and Pi evidence under ignored `verification_reports/`.
- Conduct attended app/firmware, fail-closed motion, and Camera-route checks on
  the designated machine.
- Publish the immutable tag and stage the fleet after all pre-publication gates.
- Create the Milestone 7 completion record and mark the parent plan verified.

### Out of scope

- New machine-data schemas or a `bootstrap_recovery` transition for rc.2.
- Accepting semantic-only preservation when the release declares
  `transition: none`.
- Altering configuration thresholds, target-verification policy, movement
  routes, speed, pressure, timing, protocol, or firmware handlers.
- Reconstructing a shortened updater or rollback command by hand.
- Automatically flashing or downgrading firmware.
- Moving, deleting, or retargeting an existing remote release tag.
- Treating a disposable/sanitized cohort fixture as a substitute for the real
  representative rc.6 and rc.1 deployment pilots.
- Committing raw machine configuration, coordinates, credentials, SSH keys,
  logs, update archives, HIL reports, or evidence bundles.
- Automatically deleting a failed Pi qualification workspace or evidence.

If qualification reveals a runtime defect, pause this milestone, record the
finding, implement the smallest separately reviewable correction, and restart
the affected gates from the new candidate commit. If a firmware or protocol
change appears necessary, stop and obtain separate scope approval before
editing it.

## Audited call paths

### First start and legacy migration

```text
FreeRTOS-interface/App.py
-> acquire application-global lock
-> resolve checkout-independent machine-data base
-> MachineDataBootstrap.inspect()
-> MachineDataBootstrapDialog.run_bootstrap_dialog()
-> candidate discovery / archive / migration / verification / activation
-> MachineDataBootstrap.open_ready()
-> validate deployment anchor and update/legacy-session state
-> AuthorizedMachineContext with lifetime configuration lock
-> ApplicationComposition creates Settings, Model, Controller, View, comms,
   and hardware adapters
```

Cancellation, invalid evidence, unresolved migration, revoked targets,
deployment-anchor mismatch, or unfinished update state exits before normal MVC
or hardware construction.

### Update check and apply

```text
Firmware tab in FreeRTOS-interface/View.py
-> Controller.start_app_update_check()
-> AppUpdateCheckWorker / run_update_check()
-> release index, exact tag, manifest, and online/offline source validation
-> View enables Update App only for the fresh resolved result
-> Controller.launch_app_updater()
-> exact UpdateLaunchBinding from AuthorizedMachineContext
-> tools/update_window.py
-> tools/update_and_restart.py
-> update.lock then configuration.lock
-> verified external backup
-> verified Git operation
-> protected-byte post-check
-> relaunch receipt and deployment-anchor advance
```

The first transition from rc.6, v1.2.0, or rc.1 is the documented exception:
the old updater cannot execute M6 preflight. Milestone 0 recovery copies and the
M2/M3 first-start migration protect that transition; the first valid rc.2
startup creates the one permitted genesis deployment anchor.

### Guarded edit and audit

```text
View captures proposed location/rack/plate/calibration values
-> Controller creates a hash-bound guarded proposal
-> ConfigurationChangePreviewDialog displays exact deltas and policy result
-> operator confirmation, including strong phrase when required
-> Controller.commit_guarded_configuration_proposal()
-> ConfigurationTransactionService acquires lock and rechecks snapshot
-> backup + pending journal + exact config replace + immutable event + head
-> Model refreshes only after committed success
```

Milestone 7 verifies this path; it does not change its policy.

### Saved-location motion

```text
View requests a named target
-> Controller.move_to_location()
-> authorize exact current target before any safe-height or dogleg command
-> route validation and global endpoint bounds
-> Model / Machine_FreeRTOS queues the existing command
-> existing protocol serialization
-> existing firmware motion handler
```

The attended Camera test must prove both the stored target and this route. The
firmware Camera-transition self-test does not, by itself, prove the
application's machine-specific saved Camera coordinate.

### Firmware qualification boundary

```text
tracked firmware source + versioned LabCraft_firmware.bin
-> local firmware checks and artifact fingerprint
-> attended flash only when pairing requires it
-> SAFE self-test bracket
-> approved focused FULL selectors
-> normalized qualification reports and operator observations
```

No unattended SSH step may flash firmware, enable/home a motor, connect the
production application to the controller, or run a FULL motion selector.

## Frozen source and artifact facts

Recheck every value at candidate freeze. At planning time:

| Item | Frozen value |
| --- | --- |
| rc.6 source commit | `199807eea95a238896137bddb2a83d3d892e2aab` |
| rc.1 source commit | `922f2ac65eab2ff1f63ffc0719a98b777bc2128f` |
| accepted stable commit | `177986e4243dd8db2faadd7453dbbfdd4514aaf2` (`v1.2.0`) |
| verified M6 implementation | `9e666291bd3145c6073077c3d68a1a206da74710` |
| verified M6 documentation HEAD | `0ee3e50a6890dd066f1f8addfbd9e0264ef3e652` |
| production firmware artifact | `firmware/artifacts/LabCraft_firmware.bin` |
| firmware file size | `343064` bytes |
| firmware Git blob | `526bc6ffbe980bbbebc67a8cf4b1db04ec8f263a` |
| firmware SHA-256 | `EDA070CE734D5167F0795FAF30DF461C8A07341E09CA698DE9D850315B0D5884` |
| firmware difference from rc.1 | none at planning time |
| target Pi | `labcraft@192.168.0.33` |
| target Pi repository | `/home/labcraft/LabCraft_printer` |
| target Pi interpreter | `/home/labcraft/LabCraft_printer/env/bin/python` |
| SSH identity | `verification_reports\pi_sil_codex_network_ed25519` |

The rc.2 manifest retains an explicit v1.3 firmware requirement even if this
artifact remains byte-identical to rc.1, because an rc.6 machine may update
directly to rc.2. An rc.1 pilot may use reviewed existing provenance for this
exact artifact or redeploy it; an rc.6 pilot must receive and verify the
required v1.3 pairing before attended application motion.

## Fixed safety invariants

1. Migration and recovery run before normal MVC, comms, camera, balance, GPIO,
   or motion-capable application construction.
2. A missing external root, pointer, config, receipt, or deployment anchor
   never selects a tracked preset as production fallback.
3. Migration acceptance requires exact copied bytes plus semantic safety
   equality. There is no coordinate tolerance for migration.
4. The Camera coordinate in the selected source, verified backup, canonical
   destination, activation evidence, and operator checklist must agree.
5. Preset similarity is a review signal, never evidence that the value is
   correct for the machine.
6. No unverified or revoked saved target may issue even an intermediate
   safe-height or dogleg command.
7. A normal update must verify an external pre-change backup before Git
   mutation and exact protected bytes after it.
8. The first legacy-to-rc.2 update may use genesis enrollment only once; every
   later update requires M6 evidence.
9. Legacy rollback is support-only, exact-target-only, firmware-attested, and
   export-before-Git. No force or bypass flag exists.
10. Canonical data remains frozen during a legacy session; legacy differences
    are never copied back automatically.
11. Qualification evidence is immutable, hash-sealed, private, and tied to an
    exact candidate commit and machine/cohort label.
12. Any unexplained coordinate, identity, root, hash, firmware, authorization,
    or motion discrepancy stops qualification and fleet rollout.
13. A local unpushed tag may be discarded after a failed tag-dependent gate;
    a pushed tag is never moved or reused.
14. The remote `stable` branch remains on the accepted stable release during
    this RC workflow.

## Qualification state machine

```text
planned
-> coverage_frozen
-> candidate_committed
-> windows_passed
-> pi_unattended_passed
-> attended_test_machine_passed
-> local_tag_validated
-> tag_dependent_update_and_rollback_passed
-> published
-> rc6_pilot_passed
-> rc1_pilot_passed
-> fleet_rollout_accepted
-> verified
```

The milestone may advance by one state only when the prior gate's evidence is
sealed. A failure records `qualification_failed`, preserves its workspace, and
returns work to a new candidate commit. It must not be converted into a warning
to keep the release moving.

## Private evidence layout

Windows evidence remains in ignored storage:

```text
verification_reports/
  machine_data_m7/
    <candidate-commit>/
      candidate/
      windows/
      pi-unattended/
        rc6/
        rc1/
        existing-canonical/
        updater/
        rollback/
        sil/
      attended-test-machine/
      local-tag/
      rollout/
        controlled/
        rc6-pilot/
        rc1-pilot/
      evidence-manifest-sha256.txt
      evidence-manifest-check.txt
```

The Pi uses only a random disposable parent such as:

```text
/tmp/labcraft-m7-qualification.XXXXXX/
  candidate.bundle
  candidate-repo/
  local-remote.git/
  cohorts/
    rc6-checkout/
    rc1-checkout/
  machine-data/
    rc6/
    rc1/
    existing-canonical/
  logs/
  evidence/
```

The random absolute path is written to
`/tmp/labcraft-m7-qualification.latest` and included in every log. Failed
workspaces remain in place until their evidence is copied and reviewed. Any
later cleanup resolves and prints the exact `/tmp/labcraft-m7-qualification.*`
path first; cleanup never targets `/tmp`, the production repository, the
default external machine-data root, a home directory, or a path derived from
an unset variable.

Each evidence package records at minimum:

- candidate commit and tree, source tag/commit, Git status, Python/Git/OS;
- release index and manifest hashes;
- firmware artifact size, Git blob, SHA-256, and pairing decision;
- source, verified-backup, canonical, pointer, identity, activation,
  verification, migration, history, and deployment-anchor hashes;
- exact private Camera value comparison and a sanitized pass/fail summary;
- update/rollback transaction IDs, stage receipts, and protected inventories;
- test commands, stdout/stderr, exit codes, durations, and counts;
- process/device preflight and zero-command/hardware-isolation proof;
- attended operator, fixture, stop-condition, and observation records; and
- archive SHA-256 plus a second successful checksum recheck after copying.

Raw coordinates, machine configuration, service attestations, and operator
identifiers remain private. The tracked completion record contains only
non-sensitive totals, identifiers already intended for release records, and
truncated evidence hashes.

## Required automated coverage matrix

Before candidate freeze, record the exact collected node IDs and result for
each row. Existing tests are the expected starting coverage; absence of a
direct assertion requires a focused test rather than an unsupported claim.

| Requirement | Expected direct evidence |
| --- | --- |
| Exact rc.6 and rc.1 layouts | `test_historical_catalog_recognizes_both_reviewed_source_cohorts`; cohort fixture rules; exact-tag compatibility tests |
| Machine-specific non-preset Camera | `test_custom_camera_is_not_mistaken_for_historical_camera`; Camera confirmation and authorizer tests |
| Camera-only/full-preset similarity | migration inspection, verification, and bootstrap-dialog preset-service tests |
| Desktop/external/parent/direct-local selection | parametrized explicit shallow-layout candidate test and bootstrap-dialog folder review |
| ZIP selection | `test_selected_zip_candidate_has_same_semantic_evidence_as_directory` plus bounded archive tests |
| Duplicate/conflicting candidates | candidate comparison and bootstrap-dialog duplicate/conflict tests |
| Missing/malformed/partial data | invalid required/safety, incomplete calibration, malformed persisted evidence, and hostile archive tests |
| Existing canonical data | existing-canonical inspection plus ready bootstrap/reopen tests |
| New checkout/worktree | second-checkout bootstrap and deployment-anchor reopen tests plus Pi detached clone lane |
| Permission/disk/lock/interruption | insufficient-space, lock contention, archive/transaction fault injection, and update recovery tests |
| Verification cancel/revoke | worker cancellation, cancelled transaction, target authorizer, and revoked compatibility fixtures |
| Named/rack/plate audit | named-location, rack-pair, and plate-quartet aggregate transaction tests |
| Guarded edit UI/policy | safety-policy, change-preview, guarded-workflow, capture-precondition, and adapter tests |
| Update preservation | machine-data preservation/recovery/deployment-anchor plus real-Git online/offline updater tests |
| Compatibility rollback/re-upgrade | legacy export and exact/changed return recovery tests plus disposable Pi Git lane |
| Simulation/no-hardware paths | App bootstrap ordering, safe construction, send-path guards, Pi hardware proof, and contained SIL |
| Release metadata and tag | release metadata validator, update discovery, bundle, and `--check-tags` gates |

The final traceability table belongs in the completion record and uses test
node IDs or evidence paths, not only filenames.

## Implementation sequence

Milestone 7 is executed in eight reviewable slices. Release/tag/rollout work is
not combined with an unrelated runtime change.

### Slice 0: Freeze coverage, operators, cohorts, and routes

- Re-read the parent plan, release process, M6 rollback runbook, firmware
  operator guidance, and both exact source-tag layouts.
- Convert the automated matrix above to exact test node IDs.
- Name the designated test machine, rc.6 pilot, rc.1 pilot, release operator,
  support operator, and evidence reviewer in private qualification records.
- Refresh Milestone 0 backup requirements for each real machine.
- Freeze the app-level Camera checklist from that machine's accepted source
  value. Record safe homing state, clearance, allowed route, expected endpoint,
  emergency stop, and abort observations. Do not place its coordinates in Git.
- Confirm the current stable/RC index and firmware fingerprint.

Gate: every automated row has direct evidence or an explicit missing-test task;
each attended machine has an approved private Camera/fixture checklist; no
release file or tag changed.

### Slice 1: Close automated gaps and freeze the candidate tree

- Add only tests required by the Slice 0 traceability audit.
- Run their focused groups until clean.
- Confirm writer and Git-mutation inventories still cover every authority path.
- Confirm no firmware/protocol file changed.
- Commit any test-only correction separately before release construction.
- Record the exact application tree that is eligible to enter `main`.

Gate: all gap tests pass, existing M1-M6 focused regressions pass, the worktree
is clean, and the candidate contains no unreviewed runtime or firmware change.

### Slice 2: Construct the rc.2 release commit without a tag

- Re-read `docs/release_process.md` immediately before editing release files.
- Refresh `main` from `origin/main` and confirm it is an ancestor of the
  milestone branch. Merge the milestone branch according to the documented RC
  workflow; stop on unexpected divergence.
- Update `VERSION`, `CHANGELOG.md`, `releases/latest.json`, and add
  `releases/v1.3.0-rc.2.json`.
- Include operator-facing external-data, migration, backup, verification,
  audit, guarded-change, updater-preservation, rollback, and firmware-pairing
  notes.
- Commit release metadata and record the exact candidate commit.
- Do not create or push a tag and do not push `main` yet.

Required release values, subject only to a reviewed release-index change before
execution:

```text
VERSION: v1.3.0-rc.2
channel: release_candidate
previous_version: v1.3.0-rc.1
rollback_version: v1.2.0
latest stable: v1.2.0
latest release_candidate: v1.3.0-rc.2
release_candidate_series prefix: v1.3.0-rc.
release_candidate_series minimum: v1.3.0-rc.1
requires_firmware artifact: firmware/artifacts/LabCraft_firmware.bin
machine_data preservation_contract: labcraft.machine_data_update.v1
machine_data data_schema_version: 1
machine_data transition: none
machine_data transition_id: null
```

Gate: release metadata validates without tag checking, all four release files
describe the same version/lineage, and the clean candidate commit is recorded.

### Slice 3: Windows candidate qualification

- Run the complete focused machine-data/configuration/update/release group.
- Run the complete Python suite with an OS-temporary pytest base outside the
  repository and a timeout of at least 15 minutes.
- Run release metadata, JSON parsing, changed-module compilation, writer/Git
  inventories, and diff checks.
- Run one contained hardware-disabled `virtual_print_array_96_v1` journey at
  96/96.
- Verify the firmware artifact fingerprint and no firmware diff from rc.1.
- Create and verify a Git bundle containing the candidate commit and exact
  source tags for Pi transfer. This is a qualification transport bundle, not a
  release/update bundle.

Gate: all Windows evidence passes on the exact candidate commit and the
qualification bundle verifies before SCP.

### Slice 4: SSH target-Pi unattended qualification

- Use SSH/SCP with the configured identity and `BatchMode=yes`.
- Record the production Pi checkout and process state read-only; do not move its
  branch/HEAD or start/stop its production app automatically.
- Create a random `/tmp` parent and clone the candidate transport bundle there.
  Reuse the production virtual environment only through a verified interpreter
  path or ignored symlink; do not copy or modify that environment.
- Run the focused groups on the Pi from the candidate clone.
- Run rc.6, rc.1, and existing-canonical bootstrap/migration fixtures against
  three distinct disposable machine-data roots.
- Prove exact source/backup/destination Camera and configuration equality,
  activation evidence, genesis enrollment, detached-checkout reuse, and zero
  production hardware access.
- Run contained SIL through `tools/run_pi_virtual_workflow.ps1` against the
  candidate clone with one measured 96/96 run and collect the bwrap/strace
  hardware-isolation proof.
- Seal, recheck, and SCP the evidence archive to ignored local storage.

Gate: both source cohorts and canonical reuse pass; focused tests and SIL pass;
the archive rechecks locally; the Pi production checkout/root/HEAD and hardware
state remain unchanged.

### Slice 5: Attended designated-machine qualification

- Refresh the machine's Desktop and external-drive `local/` plus `VERSION`
  copies immediately before changing the application.
- Record the production source commit, app version, machine identity, external
  root, configuration hashes, Camera value, and firmware provenance.
- Keep motion inhibited while the exact candidate is installed and first-start
  migration/activation evidence is reviewed.
- Verify machine ID, hardware profile, all required locations, Camera, racks,
  plate calibration, source/destination hashes, and deployment anchor before
  connecting motion.
- Exercise an unverified disposable target and prove zero dispatch.
- Exercise guarded preview/audit/restore with a simulator or explicitly
  non-hazardous test values before physical Camera motion.
- Verify required firmware pairing. Any flash or FULL selector is separately
  attended and starts only after the operator confirms the named fixture and
  clear envelope.
- Run SAFE-bracketed approved HIL, then the private app-level Camera checklist.

Gate: the designated machine passes migration, pairing, no-command, audit,
restore, HIL, and app-level Camera route with no unexplained discrepancy. Seal
and review its evidence before creating the local release tag.

### Slice 6: Local tag, exact legacy updater, bundle, and rollback gates

- Create annotated tag `v1.3.0-rc.2` locally on the exact qualified candidate
  commit. Do not push it.
- Run release validation with `--check-tags` and prove the tag peels to the
  candidate commit.
- Create and verify the full release-aware rc.2 update bundle.
- Transfer tag/bundle evidence to the Pi disposable workspace.
- Create a disposable local bare remote advertising the local rc.2 tag and
  candidate release index.
- From exact rc.6 and rc.1 disposable checkouts, run each old version's own
  `tools/update_and_restart.py --target-release v1.3.0-rc.2 --no-relaunch`
  against that remote. Prove fast-forward to the exact tag and preservation of
  the checkout-local legacy source for first start.
- Run target-side first-start migration for each cohort with separate external
  roots; verify genesis anchors and detached reopen.
- Exercise release-aware offline update equivalence.
- Rehearse support-guided rollback to `v1.2.0`, unchanged re-upgrade, and a
  separate synthetic Camera-Y legacy conflict that remains recovery-only.
- Seal and retrieve the tag-dependent Pi evidence.

Gate: tag, online/local-remote, offline, rollback, and re-upgrade lanes all
pass. If a gate fails, delete only the unpushed local tag, fix on a new commit,
and restart the affected and downstream gates. Never retarget a remote tag.

### Slice 7: Publish, staged rollout, and closeout

- Recheck remote refs in a coordinated release window and confirm no unexpected
  `main` advance.
- Push the immutable rc.2 tag before the branch that advertises it, or use a
  verified atomic push. Keep `stable` unchanged.
- Upgrade the controlled test machine from the public tag and review evidence.
- Upgrade one real rc.6 machine, including required firmware pairing, and pause
  for evidence review.
- Upgrade one real rc.1 machine, including explicit preset-like Camera review
  and firmware provenance, and pause for evidence review.
- Expand to the remaining fleet only after both pilot records are accepted.
- Seal the final rollout archive, create the completion record, update the
  parent plan, and commit only sanitized documentation after the release tag.

Gate: every definition-of-done item passes, no safety-critical issue remains,
all intended rollout machines have refreshed recovery copies and accepted
evidence, and the tag still points to the qualified candidate commit.

## Files expected to change during execution

### Release files

- `VERSION`
- `CHANGELOG.md`
- `releases/latest.json`
- new `releases/v1.3.0-rc.2.json`

### Tests, only if Slice 0 finds a direct gap

- existing machine-data migration, verification, bootstrap, transaction,
  guarded-change, update, rollback, updater, and release-metadata test modules;
- a new focused M7 system test only when the required behavior cannot be
  expressed clearly in an existing owner module.

### Documentation

- this implementation plan;
- `docs/machine_data_migration_and_location_safety_plan.md`;
- `docs/machine_data_update_and_rollback_runbook.md` only if qualification
  discovers an operator/support ambiguity;
- `docs/release_process.md` only if the release workflow itself needs a
  correction before tagging;
- new `docs/machine_data_migration_milestone_7_completion_record.md` after all
  gates pass; and
- operator-facing README wording only if the final release instructions are
  otherwise incomplete.

### Explicitly not expected

- `FreeRTOS-interface/App.py`, `Controller.py`, `Model.py`, `View.py`,
  `Machine_FreeRTOS.py`, machine-data authority modules, or updater code;
- any device protocol file;
- any file under `firmware/`; or
- a new automatic firmware flasher or automatic physical-motion harness.

An unexpected runtime or firmware edit is a qualification finding, not a
routine M7 file. Stop, document the expanded call path, write a focused plan,
and create a new candidate before continuing.

## Windows validation gates

Run the focused group first:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_machine_data_contract.py `
  tests\test_machine_data_archive.py `
  tests\test_machine_data_migration.py `
  tests\test_machine_data_migration_recovery.py `
  tests\test_machine_data_verification.py `
  tests\test_machine_data_bootstrap.py `
  tests\test_machine_data_bootstrap_recovery.py `
  tests\test_machine_data_bootstrap_dialog.py `
  tests\test_app_machine_data_bootstrap.py `
  tests\test_machine_data_transactions.py `
  tests\test_configuration_history_reader.py `
  tests\test_configuration_safety_policy.py `
  tests\test_configuration_change_preview.py `
  tests\test_configuration_guarded_workflows.py `
  tests\test_configuration_capture_preconditions.py `
  tests\test_configuration_mutation_adapters.py `
  tests\test_machine_data_update_preservation.py `
  tests\test_machine_data_update_recovery.py `
  tests\test_machine_data_legacy_compatibility.py `
  tests\test_machine_data_deployment_anchor.py `
  tests\test_update_and_restart.py `
  tests\test_update_window.py `
  tests\test_app_update_request.py `
  tests\test_create_update_bundle.py `
  tests\test_validate_release_metadata.py `
  tests\test_configuration_writer_inventory.py `
  tests\test_controller_static_guards.py `
  tests\test_machine_send_path_guards.py `
  tests\test_controller_move_to_location.py `
  tests\test_safe_application_construction.py
```

Then run the final gates:

```powershell
.\env\Scripts\python.exe -m pytest -q

.\env\Scripts\python.exe tools\validate_release_metadata.py

Get-ChildItem releases\*.json | ForEach-Object {
    Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null
}

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root <absolute-os-temporary-output-root> `
  --warmup-runs 0 `
  --measured-runs 1 `
  --host-label windows-m7-rc2-candidate

Get-FileHash firmware\artifacts\LabCraft_firmware.bin -Algorithm SHA256
git diff --exit-code v1.3.0-rc.1 -- firmware
git diff --check
git status --short
```

Use at least 900,000 ms for the complete pytest suite. The pytest base and SIL
output root must be absolute OS-temporary locations outside the repository;
an in-repository base invalidates isolation tests and is not release evidence.

Compile every Python file changed since the verified M6 documentation commit.
Record exit codes and outputs. Do not count a killed, timed-out, partially
collected, or isolation-invalid run as a pass.

## Candidate transport to the Pi

The exact untagged candidate is transported without pushing `main` or creating
a remote release tag. From the clean candidate commit, create an ignored bundle
containing `HEAD` and the exact source tags:

```powershell
$candidateCommit = git rev-parse HEAD
$candidateEvidence = Join-Path `
  "verification_reports\machine_data_m7" `
  $candidateCommit
New-Item -ItemType Directory -Force $candidateEvidence | Out-Null

$candidateBundle = Join-Path $candidateEvidence "candidate.bundle"
git bundle create $candidateBundle `
  HEAD `
  v1.2.0-rc.6 `
  v1.2.0 `
  v1.3.0-rc.1
git bundle verify $candidateBundle
```

Copy it to a unique `/tmp` filename using the configured identity. The SSH
preflight first records, without changing state:

```text
/home/labcraft/LabCraft_printer HEAD and status
VERSION
Python and Git versions
running App.py processes
current LABCRAFT_MACHINE_DATA_ROOT display only
free space for the planned disposable archive
candidate bundle SHA-256 after SCP
```

If the production checkout is dirty, the candidate hash differs, an App
process is unexpectedly running, the bundle hash differs, or free space is
insufficient, stop before creating cohort data. Do not terminate a production
process through an unattended qualification command.

## Target-Pi unattended SSH qualification

Use:

- host: `labcraft@192.168.0.33`;
- identity: `verification_reports\pi_sil_codex_network_ed25519`;
- `ssh -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=8`;
- the absolute production interpreter only after verifying its real path; and
- a candidate clone and all machine-data/evidence below the random `/tmp`
  qualification parent.

The unattended phase must not:

- change the production repository branch, HEAD, index, or worktree;
- read from or write to the default production machine-data root;
- launch production `FreeRTOS-interface/App.py`;
- open serial, camera, balance, GPIO, `/dev/gpiomem`, or `/dev/mem`;
- flash firmware, enable/home motors, send motion/pressure commands, or run FULL
  HIL; or
- remove a failed workspace.

Required sequence:

1. Clone the candidate transport bundle into the random parent, detach at the
   exact candidate commit, verify all three source-tag commits, and confirm a
   clean status.
2. If the Pi SIL wrapper needs a repository-local interpreter, create an
   ignored `env/` shim inside the disposable clone with read-only links to the
   verified production venv's launcher, library directory, and `pyvenv.cfg`.
   A top-level `env` symlink is not sufficient because the repository's
   `env/` ignore rule applies to directories, not symlinks. Invoke the absolute
   production launcher
   `/home/labcraft/LabCraft_printer/env/bin/python`, confirm it is executable,
   and require Python's reported `sys.prefix` to equal
   `/home/labcraft/LabCraft_printer/env`. Do not compare `readlink -f` of the
   launcher to the launcher path: a valid venv commonly resolves that symlink
   to the underlying `/usr/bin/python3.11` executable.
3. Create independent rc.6, rc.1, and existing-canonical roots. Never reuse a
   migrated root as proof of another cohort.
4. Run the same focused pytest file list used on Windows, split into migration,
   transaction/guard, and update/rollback groups so each group has its own log
   and exit code.
5. Run exact source-layout journeys from the tracked sanitized fixtures. For
   each cohort prove candidate discovery, verified archive, staged copy,
   activation, Camera equality, genesis anchor, and second-checkout reopen.
6. Exercise missing/malformed source, preset-like Camera, revoked target,
   cancellation, lock contention, failed backup, interrupted publication,
   active-pointer drift, and post-Git drift lanes. Assert zero commands or
   hardware imports in all fail-closed lanes.
7. Run one contained Pi SIL journey from Windows against the disposable
   candidate repository:

   ```powershell
   .\tools\run_pi_virtual_workflow.ps1 `
     -PiHost 192.168.0.33 `
     -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
     -RemoteRepo <disposable-candidate-repo> `
     -Scenario virtual_print_array_96_v1 `
     -WarmupRuns 0 `
     -MeasuredRuns 1 `
     -HostLabel pi5-m7-rc2-candidate `
     -LocalArchiveRoot <candidate-evidence-pi-sil-root>
   ```

8. Require 96/96 completion, `sil.host_hardware_disabled`, valid Pi preflight,
   private-device trace proof, zero production device access, and a clean
   candidate checkout after the run.
9. Capture the production checkout/root hashes again and compare them with the
   preflight. Any change fails qualification.
10. Create a read-only evidence manifest, verify it on the Pi, archive the
    workspace evidence without the virtual environment, SCP it to ignored
    local storage, and re-run checksum verification locally.

The local completion record stores the archive SHA-256 and counts. It does not
store private configuration or coordinates.

## Local-tag exact updater and rollback qualification on the Pi

After the attended pre-tag gate passes, create the annotated tag locally and
build a release-aware bundle. Transfer it into the existing disposable Pi
parent or a fresh one. Do not use the production repository as the Git remote.

The exact-tag Pi lane must:

1. create a disposable bare remote from the verified release bundle;
2. create separate checkouts at exact rc.6 and rc.1 tags;
3. install the matching tracked sanitized legacy `local/` fixture in each;
4. use the old tag's own `tools/update_and_restart.py` process with
   `--target-release v1.3.0-rc.2 --no-relaunch --record-result`;
5. prove the old updater fast-forwards to the exact local tag and does not
   rewrite the legacy `local/` before target first start;
6. launch target bootstrap services without normal MVC/hardware, migrate to a
   separate external root, verify the archive/copy/Camera, activate, create the
   genesis anchor, and reopen from a second detached checkout;
7. repeat the target update through the release-aware offline bundle and prove
   equivalent release/commit/config evidence;
8. from a disposable rc.2 canonical copy, generate the full authorized
   support-only rollback binding, attest the exact machine/target/firmware,
   export verified v1.2.0 `local/`, and only then execute the Git reset;
9. return unchanged to rc.2 and prove automatic exact reauthorization; and
10. repeat on a fresh copy with one synthetic legacy Camera-Y edit, prove
    explicit conflict/recovery before MVC/hardware, preserve comparison
    evidence, and do not adopt the synthetic value.

The rollback command is intentionally not copied as a static command into this
plan. It contains unique root, identity, activation, pointer, source commit,
request, operator, reason, service-record, and firmware-attestation bindings
and must be generated from the authorized disposable context. A shortened or
manually reconstructed command is a failed gate.

## Attended designated-machine qualification

This phase is separate from unattended SSH. The operator remains physically at
the machine, confirms every prompt, observes every motion, and has immediate
access to emergency stop. SSH may collect evidence and start an already
approved test, but it does not provide attendance.

### Pre-mutation checklist

- Machine is idle; no print, calibration, capture, firmware, update, or
  maintenance operation is active.
- Application is closed and `pgrep` confirms no `App.py` process.
- Active `local/` and `VERSION` are freshly copied to Desktop and an external
  drive; both copies open successfully.
- Source tag/commit, Git status, machine ID/UUID, hardware profile, firmware
  provenance, and expected external root are recorded.
- Private source hashes and Camera/rack/plate/location values are recorded.
- Candidate commit, release manifest hash, and firmware artifact hash match
  the qualified Windows/Pi records.
- Motor power remains inhibited during candidate installation and migration
  review where the machine permits this independently.
- Complete motion envelope and required fixtures are visually clear.
- Emergency stop and recovery procedure are confirmed.

### Migration and no-command gate

1. Install the exact candidate commit without an uncontrolled automatic
   hardware-capable relaunch.
2. Start rc.2 bootstrap and exercise at least one cancellation before final
   activation; confirm no normal application or movement starts.
3. Select the live legacy source or its named off-device copy. The private
   record says which was used and why.
4. Review machine identity, hardware profile, all named locations, Camera,
   racks, plate calibration, calibration ownership, preset similarity, and
   source version.
5. Create the verified backup and canonical copy; compare source, archive, and
   destination raw hashes plus semantic safety values.
6. Complete source/machine/required target verification and activation.
7. Verify active pointer, identity, migration/verification/activation receipts,
   required target authorizations, and genesis deployment anchor.
8. Before enabling motion, attempt a controlled request for an explicitly
   unverified disposable target and prove zero Controller/Machine commands.
9. Close and reopen from the production checkout and a second checkout; prove
   the same external store is reused with no import or preset seeding.

### Guarded edit, audit, and restore gate

Use simulation or explicitly non-hazardous values first:

1. preview one named-location change and record exact deltas/policy result;
2. cancel and prove no bytes, backup, event, or head changed;
3. commit an approved non-hazardous change with required confirmation;
4. verify one immutable event, one backup, head advance, and target revocation;
5. reverify or restore through the approved guarded path;
6. prove exact configured bytes and target authorization are restored; and
7. inspect the history UI/reader without editing evidence files.

Rack-pair and four-corner plate aggregation remain automated/SIL gates unless
the operator checklist identifies a safe machine-specific reason to repeat
them physically. Milestone 7 does not create physical motion merely to produce
an audit event.

### Firmware pairing and HIL

If the designated machine lacks reviewed provenance for the exact required
artifact, an attended operator may use the existing wrapper to flash and run a
SAFE gate:

```powershell
powershell -ExecutionPolicy Bypass `
  -File firmware/scripts/run_fw_hil_windows.ps1 `
  -PiHost 192.168.0.33 `
  -IdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Profile SAFE
```

This command is not part of unattended qualification because it flashes the
device. If existing rc.1 provenance already binds the physical machine to the
same exact artifact, record that provenance and do not reflash solely to create
a newer timestamp.

After a passing SAFE inventory and explicit fixture/envelope confirmation, run
only the approved focused rows over SSH from the candidate repository:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --normal-xy-route-suite --out hil_reports/m7_normal_xy_route.json
python3 tools/run_qualification.py --manifest normal_xy_route_v1 --operator-prompts --fixture coordinated_xy_physical_limit_v1 --machine-id LC-001 --raw-report hil_reports/m7_normal_xy_route.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --direct-xyz-lut-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/m7_direct_xyz_lut.json
python3 tools/run_qualification.py --manifest direct_xyz_lut_v1 --operator-prompts --fixture direct_xyz_lut_envelope_clear --machine-id LC-001 --raw-report hil_reports/m7_direct_xyz_lut.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-production-mres3-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/m7_coordinated_xy_production_mres3_v5.json
python3 tools/run_qualification.py --manifest coordinated_xy_production_mres3_v5 --operator-prompts --fixture coordinated_xy_production_mres3_envelope_clear --machine-id LC-001 --raw-report hil_reports/m7_coordinated_xy_production_mres3_v5.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-camera-transition-suite --timeout-ms 180000 --status-only-timeout-ms 120000 --out hil_reports/m7_coordinated_xy_camera_transition_v4.json
python3 tools/run_qualification.py --manifest coordinated_xy_camera_transition_v4 --operator-prompts --fixture coordinated_xy_camera_transition_envelope_clear --machine-id LC-001 --raw-report hil_reports/m7_coordinated_xy_camera_transition_v4.json
```

Use the repository virtual-environment Python in execution; `python3` above
matches the maintained operator examples. Bracket the focused rows with SAFE
inventories and compare reset, watchdog, boot/fault, endpoint, and P/R state.
No application process may hold the serial device during self-test.

### App-level Camera route gate

The private machine checklist supplies exact accepted values and clearance.
The common sequence is:

1. prove source backup, canonical config, current Model value, verification
   evidence, and previewed target all contain the same Camera coordinates;
2. confirm Camera is authorized and not revoked;
3. establish the approved home/reference state;
4. verify the Controller preview and safe route without using override or
   `ignore_safe_height` as a bypass;
5. execute the approved intermediate/approach sequence while the operator
   watches all axes;
6. stop before the final approach if position, direction, sound, clearance,
   limit, status cadence, or expected route differs;
7. confirm the final physical Camera position and record the observation; and
8. return using the approved route, close/reopen the app, and prove the stored
   coordinate and authorization remain unchanged.

No global distance threshold can approve this gate. The coordinate must match
the accepted machine-specific source exactly, and the operator must approve the
physical route independently.

## Stop conditions

Stop the current phase and all downstream release/rollout work when:

- source, backup, destination, active pointer, identity, or protected hashes do
  not match their required relationship;
- Camera or another safety target differs by any unexplained amount;
- a preset-like value is accepted without the required explicit review;
- an unverified/revoked target dispatches or begins an intermediate command;
- a candidate starts MVC/hardware before completing recovery/migration;
- an update lacks a verified backup, post-check, receipt, or correct target
  commit;
- a rollback command lacks any binding/attestation or changes Git before a
  verified compatibility export;
- an unfinished transaction, deployment-anchor mismatch, or legacy conflict
  is bypassed;
- production Pi state changes during disposable qualification;
- firmware provenance/artifact/manifest pairing is uncertain;
- homing, limits, route, endpoint, reset, watchdog, pressure, sound, or physical
  motion differs from the approved checklist;
- a test is killed, times out, skips a required capability, or leaves ambiguous
  evidence;
- an evidence archive fails either checksum verification; or
- `origin/main`, release index, accepted stable, or existing tags change in a
  way that invalidates the frozen release lineage.

Preserve the complete failure workspace, logs, receipts, process state, and
hashes. Do not retry by deleting evidence, copying backup data over canonical
data, removing locks, changing checkout manually, lowering a gate, or moving a
tag.

## Release tag and publication procedure

After Slices 0-5 pass on the exact candidate commit:

```powershell
git status --short
git rev-parse HEAD
git tag -a v1.3.0-rc.2 -m "LabCraft v1.3.0 release candidate 2"
.\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
git rev-parse "v1.3.0-rc.2^{commit}"
.\env\Scripts\python.exe tools\create_update_bundle.py --release v1.3.0-rc.2
```

The peeled tag commit must equal the candidate commit in every Windows, Pi,
attended, and release record. Run Slice 6 before publishing.

Immediately before publication:

1. fetch remote refs/tags;
2. prove no remote `v1.3.0-rc.2` exists;
3. prove remote `main` has not advanced unexpectedly;
4. re-run metadata/tag validation and bundle hashes;
5. review all stop conditions and open findings; and
6. obtain the release decision.

Publish the tag before the branch/index that advertises it:

```powershell
git push origin v1.3.0-rc.2
git push origin main
```

A supported atomic push may replace those two commands. Do not push `stable`.
If publication fails between refs, stop and inspect the remote state; do not
retarget a tag that was accepted remotely.

## Staged rollout procedure

### Common per-machine preflight

For every machine, including the controlled test machine:

- refresh the Milestone 0 Desktop and external-drive `local/` plus `VERSION`
  copies immediately before update;
- verify both copies can be opened;
- record source tag/commit, status, machine identity, expected Camera and other
  required locations, calibration ownership, firmware provenance, and operator;
- close the app and confirm no busy operation/process;
- verify the intended external root is permanent and is not a prior `/tmp`
  qualification root;
- verify the release check resolves exactly `v1.3.0-rc.2`, its tag/manifest,
  machine-data contract, and firmware requirement; and
- retain motor inhibition until migration and configuration evidence passes.

### Controlled public-tag machine

- Repeat the public online or release-aware offline update through the normal
  UI, not a developer checkout shortcut.
- Confirm first-start or M6 preservation behavior appropriate to its source.
- Repeat the signed app-level Camera checklist and a limited approved
  operational check.
- Review update/migration archive, deployment anchor, audit, firmware, restart,
  and operator evidence before advancing.

### Representative rc.6 pilot

- Select/verify its own live rc.6 `local/` or named fresh off-device copy.
- Require the v1.3 firmware artifact to be deployed and operationally verified
  before application motion.
- Complete migration, exact Camera/config comparison, genesis anchor, restart,
  no-command gate, and approved physical route.
- Seal and independently review its evidence. Do not use the controlled
  machine's result as its acceptance.

### Representative rc.1 pilot

- Select/verify its own live rc.1 `local/` or named fresh off-device copy.
- Require explicit review of Camera and every preset-similarity signal.
- Bind existing firmware provenance to the exact rc.2-required artifact or
  redeploy it under attendance.
- Complete migration, genesis anchor, restart, no-command gate, and approved
  physical route.
- Seal and independently review its evidence.

### Remaining fleet

Only after the controlled, rc.6, and rc.1 records are accepted:

- deploy in small named batches;
- apply the same per-machine preflight and evidence requirements;
- review each batch before starting the next; and
- pause the entire fleet on any unexplained coordinate, identity, root, hash,
  firmware, updater, or motion discrepancy.

## Rollback and failed-release strategy

### Before a local tag exists

Do not publish. Preserve evidence, fix on a new commit, and repeat the affected
and downstream candidate gates. The previous deployed releases and Milestone 0
copies remain untouched.

### After a local tag but before push

If a tag-dependent gate fails, preserve the tag identity in the failed record,
delete only the local unpushed tag, correct the candidate, and recreate the tag
after all affected gates pass. Never reuse failed evidence for the new commit.

### After remote publication but before fleet expansion

Never move or delete the remote tag. Stop advertising/deploying it according to
the release process, preserve pilot evidence, and prepare a new version/tag.
Use the qualified support-guided rollback only for a machine that needs it.

### Deployed pilot recovery

Keep hardware stopped. Collect the external update/migration transaction,
deployment anchor, pointer, release manifest, Git/firmware state, and logs
before deciding recovery. Do not use ad hoc `git reset --hard`, copy a saved
`local/` over canonical data, remove locks/receipts, or bypass bootstrap from a
second checkout. Follow `docs/machine_data_update_and_rollback_runbook.md`.

## Definition of done

Milestone 7 is `verified` only when:

- the automated traceability matrix has direct passing evidence for every row;
- any coverage gap was fixed and all M1-M6 regressions still pass;
- one exact clean rc.2 release commit contains approved release metadata;
- Windows focused/full/SIL/release/static gates pass;
- unattended SSH Pi qualification passes both source cohorts, canonical reuse,
  focused tests, 96/96 contained SIL, and hardware-isolation proof;
- the Pi production checkout, production data, and hardware remain unchanged
  by disposable qualification;
- the designated test machine passes migration, target authorization, guarded
  audit/restore, app/firmware pairing, focused HIL, and Camera route;
- the local tag peels to the qualified commit and metadata/tag validation
  passes;
- exact rc.6 and rc.1 old-updater paths reach the local tag in disposable Pi
  repositories and first-start migration/genesis enrollment pass;
- online/local-remote and release-aware offline evidence agree;
- legacy rollback, unchanged return, and synthetic Camera-conflict re-upgrade
  are rehearsed without automatic adoption;
- the public tag and `main` release index are published in safe order and
  `stable` is unchanged;
- controlled, real rc.6, and real rc.1 pilots pass and are independently
  reviewed before remaining fleet expansion;
- every rollout machine has refreshed off-device recovery copies;
- no known safety-critical issue is open;
- private evidence archives pass a second checksum recheck; and
- the completion record and parent plan contain commits, commands, counts,
  evidence hashes, decisions, findings, risks, and rollout result without
  exposing private machine data.

## Progress checklist

- [x] Audit startup, update, guarded-change, motion, release, and Pi-runner paths.
- [x] Freeze M7 scope, invariants, eight slices, evidence layout, SSH target,
  attended boundaries, release sequence, rollback, and definition of done.
- [ ] Complete Slice 0 traceability and private operator/cohort/route records
  (software mapping and LC-001 backup preflight complete; attended approvals
  and rc.6 pilot identity pending).
- [x] Complete Slice 1 gap tests and candidate-tree freeze.
- [x] Create the Slice 2 rc.2 release commit without a tag.
- [x] Pass Slice 3 Windows qualification and candidate-bundle verification.
- [x] Pass Slice 4 unattended SSH Pi qualification and archive recheck.
- [x] Freeze the corrected rc.2 candidate and repeat affected Slice 3/4 gates
  after the attended prefilled-source and Camera-transcription findings.
- [ ] Pass Slice 5 attended designated-machine and Camera qualification.
- [ ] Pass Slice 6 local-tag, exact old-updater, offline, rollback, and re-upgrade gates.
- [ ] Publish and complete Slice 7 staged rollout.
- [ ] Create the completion record and mark both plans `verified`.

## Planning findings

1. Both exact deployed source tags already contain updater CLI support for
   `--target-release`, `--release-channel`, `--offline-manifest`, and
   `--no-relaunch`. Their own updater processes can therefore be qualified
   against a disposable local remote without publishing rc.2.
2. The initial legacy-to-rc.2 path cannot produce M6 preflight evidence because
   the old process predates M6. M0 plus M2/M3 and constrained genesis remain
   the only honest bridge.
3. `main` was an ancestor of the milestone branch by 20 commits at planning
   time. This is not a permanent assumption; refresh remote refs immediately
   before release integration.
4. The current production firmware file is byte-identical to rc.1 and has no
   source/artifact diff from rc.1. The rc.2 requirement remains explicit for
   direct rc.6 upgrades.
5. The existing Pi SIL wrapper performs preflight and a private-device
   bwrap/strace proof over SSH. Reusing it against a disposable candidate repo
   provides stronger evidence than an ad hoc direct GUI launch.
6. The Pi SIL wrapper expects a repository-local virtual environment. Because
   the repository ignores `env/` directories but not a top-level `env`
   symlink, the disposable clone uses an ignored directory containing
   read-only links to the verified production venv. The direct production
   launcher/prefix and each shim target are recorded; the environment is not
   modified.
7. A candidate below `/tmp` was initially hidden by the runner's private
   `/tmp` mount. The runner now re-binds only `REPO_ROOT` read-only after that
   mount and overlays only its evidence root writable. The failed discovery
   attempt reached neither Python nor hardware, and a mount-order regression
   test now guards the correction.
8. The firmware Camera-transition selector verifies a firmware motion pattern,
   not the machine-specific application Camera value that caused the original
   incident. Both checks are independently required.
9. Migration equality and intentional-edit thresholds answer different
   questions. Migration allows no unexplained coordinate delta; M5 thresholds
   only select confirmation strength for a deliberate guarded proposal.
10. A realistic exact-tag legacy updater/rollback gate depends on a local tag.
   The tag is created only after all non-tag-dependent safety gates and remains
   unpushed during these tests. If a later gate fails, preserve the tag and
   prepare a new version; never move, delete, or retarget it.
11. A sanitized fixture proves software behavior but cannot establish the
    physical correctness of a real machine's configuration or firmware. Both
    deployed source cohorts still require representative pilots.
12. Attended LC-001 first start found that the prefilled direct `local/` was
    incorrectly interpreted with repository-root `local/local` semantics. It
    failed before mutation or hardware construction. The same review showed
    that retyping displayed Camera coordinates adds transcription risk without
    independent knowledge. The correction uses direct-local classification,
    read-only Camera values from inspected evidence, a separate preserve-exact
    approval, and stale-approval reset. The prior exact candidate is
    superseded, while its enrolled machine-data evidence remains immutable.

## Frozen planning decisions

| Decision | Milestone 7 direction |
| --- | --- |
| Release candidate | One exact commit; all evidence binds its SHA |
| rc.2 data transition | `transition: none`; exact protected bytes |
| Firmware | Explicit existing v1.3 artifact requirement; no automatic flash |
| Candidate transport | Verified Git bundle and SCP to disposable Pi `/tmp` |
| Unattended Pi work | SSH/SCP only; production checkout/root/hardware immutable |
| Pi SIL | Existing bwrap/strace runner, one measured 96/96 run |
| Source cohorts | Separate rc.6 and rc.1 checkouts and external roots |
| Preset similarity | Explicit review signal; never automatic acceptance |
| Camera migration | Exact equality plus independent physical route approval |
| Local tag | Created only after pre-tag gates; remains unpushed for tag-dependent tests |
| Legacy updater proof | Each exact old updater against a disposable local remote |
| Rollback proof | Support-generated bound command in disposable store; no static shortcut |
| Evidence | Private ignored archives; sanitized tracked summary only |
| Publication | Tag before advertising branch, stable unchanged |
| Rollout | Controlled machine, rc.6 pilot, rc.1 pilot, review, then fleet |
| Failure | Stop, preserve, new commit/version as applicable; never lower gate |

## Implementation record

- Concrete planning completed on `update_bug_fix` at pre-plan HEAD
  `0ee3e50a6890dd066f1f8addfbd9e0264ef3e652`.
- Slice 0 located direct existing automated coverage for every required
  scenario; no runtime or test-code change is justified by the coverage audit.
- Read-only SSH preflight found a clean LC-001 rc.1 checkout, matching backup
  and live Locations evidence, current hardware profile, no running App, and no
  machine-data environment override. Exact values remain in ignored private
  evidence; attended approvals and the rc.6 pilot identity remain pending.
- M1-M6 were merged into local `main`; untagged rc.2 candidate
  `5f54a4a174cd50f145e1bfa98aa61535b7aa59e9` contains the release metadata,
  M7 documents, and the minimal Pi SIL read-only-rebind correction.
- Windows focused/full/static/release/SIL and fresh unattended target-Pi
  focused/cohort/private-device SIL/archive gates passed on that exact commit.
- Corrected candidate `d59f73be498b695db47872a4b7a01bb95ded2d8e`
  passed its exact-commit Windows focused/full/static/release/SIL and affected
  Pi migration/bootstrap/private-device SIL gates. Production remained clean
  at the superseded candidate and its genesis anchor was unchanged. M6 update
  preparation stopped at the required, still-uncreated rc.2 release tag.
- Attended hardware work, the local tag and exact old-updater/rollback lanes,
  publication, pilots, and rollout have not completed.

## Validation record

- Planning-document structure, referenced-file, diff, and pre-rc.2 metadata
  validation passed before implementation began.
- Read-only Pi preflight changed no checkout, machine-data, process, or hardware
  state.
- Exact-candidate Windows results: 592 passed/1 skipped focused; 5,402
  passed/156 skipped full; release/static checks passed; contained SIL 96/96;
  verified bundle SHA-256 `B135BE8D...7EB408ED`.
- Exact-candidate Pi results: 199 + 101 + 275 focused tests and a 33-case named
  matrix passed; private-device SIL completed 96/96 with zero forbidden
  hardware matches; production pre/post state was identical.
- Pi evidence manifest/archive passed on-Pi and local rechecks at archive
  SHA-256 `09D68B3C...0E98A0B7`.
- The correction changed only the first-start dialog and its tests/docs; it did
  not change Controller, Model, communication, motion, pressure, timing,
  firmware, protocol, tag, production checkout, production machine-data, or
  deployed hardware state.
- Correction results: 571 passed/1 skipped focused and 5,403 passed/156 skipped
  full on Windows; 96/96 Windows SIL; 196 affected Pi tests; 96/96 Pi SIL with
  zero forbidden hardware matches; bundle SHA-256 `B0D151E5...185BB6C1`; Pi
  SIL archive SHA-256 `B38B738A...7DA87CC`.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-20 | Froze corrected candidate `d59f73be`, repeated the exact Windows and affected isolated Pi gates successfully, preserved unchanged production state, and stopped before enrolled M6 update because the required final rc.2 tag is not yet authorized or created. |
| 2026-08-20 | Attended LC-001 migration and genesis enrollment passed on `5f54a4a1`, then safely exposed the prefilled direct-local classification defect and unnecessary Camera transcription risk; superseded that release candidate and added a corrected-candidate requalification gate. |
| 2026-08-20 | Created the concrete eight-slice rc.2 coverage, candidate, Windows, SSH/Pi, attended Camera/HIL, local-tag updater/rollback, publication, staged-rollout, evidence, stop-condition, and closeout plan. |
| 2026-08-20 | Began implementation: closed the software coverage audit without a code change, captured private LC-001 read-only backup/Camera preflight over SSH, prepared untagged rc.2 release metadata and the in-progress completion record, and retained attended approval as the HIL/tag blocker. |
| 2026-08-20 | Froze candidate `5f54a4a1`; corrected the Pi runner's private-`/tmp` checkout visibility with a read-only repo rebind and regression test; passed Windows focused/full/static/SIL and fresh SSH/Pi focused/cohort/private-device SIL/archive gates; left attended, tag-dependent, publication, and rollout work open. |
