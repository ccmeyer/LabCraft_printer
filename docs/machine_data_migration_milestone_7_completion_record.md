# Machine Data Migration Milestone 7 Completion Record

> Current correction: rc.4 completed the protected update and exact restore,
> then legitimate calibration activity exposed an overly broad immutable
> migration-manifest rule and array printing exposed derived numeric types that
> the motion guard rejected. Rc.5 owns both corrections and the isolated
> development workflow needed to test future commits without rebinding the
> production machine-data store.

Status: `in_progress` - rc.5 tag `34841fe0` is published and the attended
protected rc.4-to-rc.5 update, first launch, closed-app postflight, and evidence
seal passed on LC-001. Controlled source-cohort rollout and physical Camera/HIL
gates remain.

Started: 2026-08-20

Current target release: `v1.3.0-rc.5`

Parent documents:

- [Machine Data Migration and Location Safety Plan](machine_data_migration_and_location_safety_plan.md)
- [Milestone 7 Implementation Plan](machine_data_migration_milestone_7_implementation_plan.md)
- [Machine Data Update and Rollback Runbook](machine_data_update_and_rollback_runbook.md)
- [Release Process](release_process.md)

## Current boundary

The verified M1-M6 branch has been merged into local `main`, and the untagged
rc.2 release commit is being constructed there. This record does not claim
that exact-commit Windows, target-Pi, attended hardware, local-tag,
publication, or rollout gates have passed. No `v1.3.0-rc.2` tag exists.

Physical Camera-route approval, firmware flashing, HIL, release publication,
and fleet rollout remain separate attended or operator-authorized gates.

## Slice 0 traceability audit

Every required parent-plan scenario has direct existing automated coverage.
No new runtime or test-code change is justified at candidate construction.
The exact collected node IDs and results will replace `pending execution` after
the focused gate runs.

| Requirement | Direct evidence | Status |
| --- | --- | --- |
| Exact rc.6 and rc.1 layouts | `test_machine_data_migration.py::test_historical_catalog_recognizes_both_reviewed_source_cohorts`; `test_machine_data_bootstrap.py::test_first_start_migrates_activates_and_reuses_from_second_checkout`; compatibility catalog tests | Mapped; pending execution |
| Machine-specific non-preset Camera | `test_machine_data_migration.py::test_custom_camera_is_not_mistaken_for_historical_camera`; Camera confirmation and authorizer tests | Mapped; pending execution |
| Camera-only/full-preset similarity | `test_machine_data_verification.py::test_camera_confirmation_and_preset_service_rules_fail_closed`; `test_machine_data_bootstrap_dialog.py::test_preset_like_candidate_surfaces_independent_service_requirement` | Mapped; pending execution |
| Folder layouts and ZIP | parametrized explicit shallow-layout test; missing/ambiguous layout test; selected-ZIP semantic-equality test | Mapped; pending execution |
| Duplicate/conflicting candidates | candidate comparison and bootstrap-dialog duplicate/conflict tests | Mapped; pending execution |
| Missing/malformed/partial data | invalid required/safety and incomplete calibration tests; archive and persisted-evidence parser tests | Mapped; pending execution |
| Existing canonical and new checkout | existing-canonical inspection, second-checkout bootstrap, and deployment-anchor reopen tests | Mapped; pending execution |
| Permission/disk/lock/interruption | insufficient-space, lock-contention, migration-recovery, transaction-fault, and update-recovery tests | Mapped; pending execution |
| Verification cancellation/revocation | bootstrap worker cancellation, cancelled transaction, target authorizer, and revoked legacy-export tests | Mapped; pending execution |
| Named/rack/plate history | named-location transaction and rack-pair/plate-quartet aggregate transaction tests | Mapped; pending execution |
| Guarded edits | safety-policy, preview, guarded-workflow, capture-precondition, and adapter tests | Mapped; pending execution |
| Update preservation | preservation, recovery, deployment-anchor, updater, window, and app-launch tests | Mapped; pending execution |
| Legacy rollback/re-upgrade | compatibility export, exact return, Camera conflict, and keep-canonical tests | Mapped; pending execution |
| Simulation/no hardware | App bootstrap ordering, safe construction, send-path guards, Pi hardware proof, and contained SIL | Mapped; pending execution |
| Release metadata/tag/bundle | release validator, candidate-series update check, bundle, and tag-validation tests | Mapped; pending execution |

## Read-only target-Pi Slice 0 preflight

On 2026-08-20, authorized read-only SSH inspection of
`labcraft@192.168.0.33` recorded:

- clean `update_bug_fix` checkout at `0ee3e50a`;
- `VERSION` `v1.3.0-rc.1`;
- no running `FreeRTOS-interface/App.py` process;
- no `LABCRAFT_MACHINE_DATA_ROOT` environment override;
- Desktop backup wrapper present for the rc.1 cohort;
- 148 backed-up `local/` files totaling 746,658 bytes;
- backup and live `Locations.json` hashes matched at truncated SHA-256
  `3e5b4de9...c5f3c7d02`;
- backup and expected Settings evidence matched at truncated SHA-256
  `69a5f4b9...a7646a`;
- hardware profile `current`; and
- resolved default external root below Qt application-local data, outside the
  Git checkout.

The exact Camera value, paths, and checklist state are retained only in ignored
private evidence. The prior external-drive backup is operator-attested but was
not mounted during this read-only inspection; it must be refreshed and opened
again before attended qualification.

## Candidate implementation

Working-tree changes prepared on local `main` on 2026-08-20:

- `VERSION` advanced to `v1.3.0-rc.2`;
- release index points to rc.2 while stable remains `v1.2.0`;
- rc.2 manifest declares the exact M6 machine-data preservation contract with
  `transition: none`;
- lineage is rc.1 to rc.2 with reviewed rollback target `v1.2.0`;
- the explicit v1.3 firmware requirement is retained for direct rc.6/v1.2.0
  upgrades while documenting byte identity with rc.1; and
- changelog/release notes cover external data, migration, verification,
  history, guarded changes, update preservation, support-guided rollback, and
  firmware pairing.

No application runtime, firmware, protocol, motion, pressure, or updater source
changed in this candidate-construction slice. Qualification found and corrected
one Pi SIL shell mount-order gap, with one focused regression assertion and
operator documentation.

## Windows validation

Status: `passed` for exact candidate
`5f54a4a174cd50f145e1bfa98aa61535b7aa59e9` (tree
`4dc25df5a7b0b206dc40f0bce8c75d085c2d2bc0`).

Pre-candidate checks on the same application/release tree passed 570 focused
tests with one skip, release-metadata and release-JSON validation, firmware
identity checks, and one contained 96/96 SIL journey. The discarded first
pytest attempt executed no test bodies because the sandbox denied its default
temporary directory; the successful rerun used a unique OS-temporary base
outside the repository. Final full-suite and clean-commit evidence must be
collected again against the exact release commit.

The initial target-Pi sandbox attempt found that the private `/tmp` mount hid a
candidate checkout located below `/tmp`. Candidate execution stopped before
Python, the application, or hardware access. The Pi SIL shell now re-binds only
the candidate repository read-only after mounting the private `/tmp`, then
overlays only its evidence output writable. A regression assertion fixes that
mount order. The candidate was re-frozen and every exact-commit gate was rerun.

Final exact-candidate evidence:

- focused M1-M7 group: 592 passed, 1 skipped, 130 warnings in 93.37 seconds;
- complete suite: 5,402 passed, 156 skipped, 605 warnings in 343.14 seconds;
- changed Python regression module compiled and executed successfully;
- release metadata validation and parsing of every release JSON passed;
- contained Windows SIL completed 96/96 with exit code 0;
- `git diff --check`, clean-worktree, no-rc.2-tag, and no-firmware-diff checks
  passed;
- firmware artifact remained 343,064 bytes, Git blob
  `526bc6ffbe980bbbebc67a8cf4b1db04ec8f263a`, SHA-256
  `EDA070CE...B0D5884`; and
- qualification bundle verified as complete at 52,075,353 bytes and SHA-256
  `B135BE8D...7EB408ED`.

## Target-Pi unattended qualification

Status: `passed` for the unattended/no-hardware boundary.

Final workspace: `/tmp/labcraft-m7-qualification.nqzNos`.

- The transferred bundle hash, candidate commit, and peeled rc.6, v1.2.0, and
  rc.1 commits matched the Windows record.
- The candidate was detached and clean; the verified production venv was
  exposed only through an ignored disposable shim.
- Focused groups passed 199 migration/bootstrap, 101 transaction/guard/routing,
  and 275 update/rollback/release tests.
- A verbose 33-case matrix independently showed both exact source cohorts,
  non-preset Camera preservation, supported folder/ZIP layouts, malformed and
  preset-like failure modes, cancellation, target revocation, transactional
  recovery, backup failure, exact return, and synthetic Camera-conflict paths.
- Bubblewrap/strace SIL completed 96/96. Its report bound commit `5f54a4a1`,
  showed a clean worktree, private `/dev`, unshared network, read-only root,
  simulation-only interfaces, and zero forbidden hardware-device matches.
- Production Pi HEAD `0ee3e50a`, tree `5db5adb4`, VERSION, interpreter/prefix,
  clean status, and no-App-process state matched before and after. The default
  production machine-data root was not read or written.
- The Pi-side evidence manifest verified 48 files. The archive contained 63
  safe relative members, excluded the venv, and matched locally at SHA-256
  `09D68B3C...0E98A0B7` after SCP.

The superseded diagnostic workspace
`/tmp/labcraft-m7-qualification.3Z7R15` remains retained. Its failed SIL
attempt exposed the private-`/tmp` visibility gap and reached neither Python
nor hardware; none of its results are counted as final qualification evidence.

## Attended designated-machine qualification

Status: `in_progress` — attended preflight, candidate installation,
cancellation, source review, migration, activation, and genesis enrollment
passed on `5f54a4a1`; a release-blocking bootstrap UI correction was then found.

On LC-001, operator `Conary-Codex` confirmed motor inhibition, clear motion
envelope, immediate emergency-stop access, and recovery understanding. The
Desktop and disconnected external-drive copies each matched the deployed rc.1
`local/` and `VERSION` exactly. The clean production checkout fast-forwarded
from `0ee3e50a` to `5f54a4a1` without relaunch; all 148 legacy files and
746,658 bytes remained unchanged. A first-start cancellation produced only the
bootstrap startup line, created no canonical root, and constructed no normal
MVC/hardware components.

The operator selected the verified Desktop rc.1 wrapper and reviewed all nine
saved locations and three plates without an unexplained discrepancy. The
candidate was assigned to LC-001, had complete CalibrationMemory, had no full
preset or Camera-preset match, and classified all 136 legacy `update_logs/**`
entries through the reviewed archive-only ownership rule. Activation then:

- reopened a verified 149-member source ZIP;
- proved all 11 canonical configuration/calibration files byte-identical and
  semantically equal to the selected source;
- retained the expected Locations and Settings hashes;
- authorized 12 targets with Camera recorded as custom/non-preset;
- began configuration history at sequence zero; and
- created a genesis deployment anchor for rc.2 commit `5f54a4a174cd`.

The main app opened under motor inhibition, its captured startup log contained
no textual motion-command or error marker, and the operator closed it normally.
Private evidence retains exact coordinates, UUIDs, full hashes, receipts, and
operator attestations.

Attended use also exposed two connected human-interface defects before any
motion qualification:

1. `App.py` supplied the direct checkout `local/`, while the dialog classified
   that path using repository-root semantics and attempted to inspect
   `local/local`. The failure was safe and occurred before migration/hardware,
   but the offered source was unusable without browsing to another wrapper.
2. Requiring operators to retype displayed Camera coordinates added
   transcription risk without independent physical knowledge. Operators would
   normally copy the displayed value rather than validate it independently.

The correction treats the prefilled path as a direct local candidate, displays
Camera coordinates read-only from immutable candidate evidence, requires a
dedicated preserve-exactly approval, and clears approvals when the candidate
changes. Candidate `5f54a4a1` and all exact-candidate release evidence are now
historical/superseded for tagging. Its on-machine migration evidence remains
valid and must not be removed or rewritten. A corrected candidate must pass
affected Windows/Pi/release gates and reach this enrolled machine through the
authorized M6 update path; direct Git mutation is no longer permitted.

The correction is frozen as exact candidate
`d59f73be498b695db47872a4b7a01bb95ded2d8e`. Exact-commit Windows
qualification passed 571 tests with one skip in the M1-M7 focused group and
5,403 tests with 156 skips in the complete suite. Python compilation,
release-metadata validation, release-JSON parsing, `git diff --check`, clean
worktree, no-rc.2-tag, no-firmware-diff, and a contained 96/96 SIL run also
passed. The verified 52,083,845-byte transport bundle has SHA-256
`B0D151E5...185BB6C1`.

The affected target-Pi group passed 196 migration/bootstrap/UI tests in the
detached candidate checkout. Contained Pi SIL completed 96/96 and independently
proved private `/dev`, unshared network, read-only root and repository, and
zero forbidden hardware matches. Its 3,393,454-byte evidence archive has
SHA-256 `B38B738A...7DA87CC` and binds source commit `d59f73be`. Production
postflight remained clean at `5f54a4a1`, with no app process and the original
genesis deployment anchor still intact. Two preliminary disposable clones
stopped before Python when qualification commands confused annotated tag
objects with peeled commits; both were retained, the assertion was corrected,
and neither production nor hardware was reached.

No firmware, protocol, Controller, Model, communication, motion, pressure,
timing, production checkout, or canonical machine-data file changed during
the correction or its isolated qualification. The corrected enrolled-machine
update cannot start while the candidate is untagged: M6 deliberately resolves
and verifies a release tag and has no commit-only bypass. Direct Git mutation
remains prohibited. Creating the final local `v1.3.0-rc.2` tag therefore
remains the explicit next authorization/pre-tag decision.

That rc.2 tag was subsequently created locally and verified without being
pushed. The attended enrolled-machine update then stopped before Git with
`source_binding_mismatch`: rc.2's app-generated command recorded source commit
`5f54a4a174cd`, while the updater resolved the same `HEAD` as full commit
`5f54a4a174cd50f145e1bfa98aa61535b7aa59e9` and compared them literally.
No update transaction directory was created. Read-only postflight proved the
production checkout remained clean at the same commit and that the active
pointer, genesis deployment anchor, and all protected machine-data bytes were
unchanged. The updater and launcher logs are retained in the external update
history; the operator left the error window open for evidence preservation.

Because the immutable rc.2 tag contains both the short app binding and the
literal full updater comparison, it cannot safely complete the next protected
update or validate a full target anchor after relaunch. It will not be moved or
retargeted. `v1.3.0-rc.3` supersedes it with full new bindings, exact
compatibility for only rc.2's 12-lowercase-hex historical prefix, full new
transaction/anchor evidence, and a narrowly gated attended recovery launcher.
The implementation and qualification sequence is recorded in the linked rc.3
correction plan.

The rc.3 correction code and release metadata then passed the final Windows
pre-commit gates: 602 focused tests with one skip, 5,430 complete-suite tests
with 156 skips, contained SIL at 96/96, changed-file compilation, release
metadata/JSON validation, static diff checks, and unchanged firmware SHA-256
`EDA070CE...B0D5884`. The candidate remains untagged and has not changed
LC-001. Its exact commit and disposable Pi results are recorded below.

The exact candidate is now
`d965927e88a9ce10217a0bf56a69789e9b0bd9f0`. Disposable Pi qualification
passed 270 focused tests, contained 96/96 SIL with private-device isolation,
and a fresh real-Git rc.2 recovery update that preserved 19 protected members
and 63,616 bytes, wrote a full rc.3 target anchor/stage chain, authorized
relaunch, and reopened rc.3. The retrieved Pi SIL archive is 3,402,813 bytes
with SHA-256 `992EFE5A...99CD2AB8`; the separate 110,492-byte focused/recovery
evidence archive matched at `0447F9BC...81C1AC`.

The rc.3 tag was subsequently created and the attended rc.2 recovery update
completed successfully. Its verified pre-update archive, exact protected-byte
preservation, full target deployment anchor, immutable terminal receipts,
manual shortcut launch, and post-update result popup all passed. LC-001 now
runs the clean immutable rc.3 commit `d965927e`; the normal app reopened and
the update popup was acknowledged.

The guarded-change qualification then recorded a cancelled attempt, followed
by an accepted addition of disposable location `qualification-unverified`.
The new target was revoked. A real-authorizer no-command probe returned
`target_revoked`, made zero route/motion calls, opened no protected device, and
left every protected byte unchanged. Camera remained unchanged and trusted.

Selecting the accepted event's exact pre-change backup exposed a new safe
defect: rc.3's guard rejected the restore because it applied the import ban on
removed locations to exact restore as well. The rejection was recorded as the
next immutable event, changed no configuration, left no pending transaction,
and retained the disposable target in its revoked state. The operator was
instructed not to retry or edit configuration manually. Private evidence was
sealed and copied with matching SHA-256 `36100C35...A673E435`.

Rc.4 now owns the narrow correction. Its restore preview is bound to the
unique immutable source event, machine identity, source manifest hash, backup
fingerprint, and exact member hashes. Only a bound exact restore may remove an
added target; governed imports remain deletion-prohibited. Pre-commit Windows
gates passed 59 narrow tests, 336 broader affected tests, 5,434 full-suite
tests with 156 skips, and contained SIL 96/96, plus release/static/firmware
identity checks.

Candidate `3e451c01e23f2957d12c8242c9c664bf8974aeae` passed
clean-commit 59-test and Windows 96/96 gates. A detached clean Pi
checkout passed the same 59 tests, an independent add/revoke/exact-restore
exercise with exact original bytes and no pending transaction, and
private-device contained SIL 96/96. The retrieved SIL archive SHA-256 is
`71347FEC...7FCA74F4`; focused/restore/postflight evidence is
`1B46D436...C22C908D`.

Read-only postflight matched the active pointer, deployment anchor, and all 25
protected preflight files. Production remained clean at rc.3 commit
`d965927e`, with the normal app still running. Audit sequence 4 was already in
the preflight snapshot and is the operator-cancelled restore preview after the
sequence-3 rejection; disposable qualification created no production event.
The disposable target remains revoked and no production pending transaction
exists. Rc.4 remains untagged.

A final coverage audit then added a direct regression for exact restoration
that removes an added calibrated plate. It verifies all four previewed corner
removals, exact raw `Plates.json` restoration, target removal, and no pending
transaction; the narrow group now passes 60 tests. Since this changes the
tracked release tree, `3e451c01` is retained as passing evidence but is
superseded as the tag target.

Coverage-complete candidate
`25d1b541f62de15dc6f8e09036b5d588fcc95920` repeated the exact-commit gates.
Windows passed the 60-test narrow group, 5,435 full-suite tests with 156
skipped, release/static/unchanged-firmware checks, and contained SIL 96/96.
The two preceding full-suite attempts were environmental only: the default
temporary tree denied access, while an in-repository base correctly violated
simulation containment. The passing run used a unique external temporary
base.

The final disposable Pi checkout passed the same 60 tests, independent
add/revoke/exact-location restoration with byte-identical original data and
no pending transaction, and private-device contained SIL 96/96 with zero
injected stalls. The retrieved SIL archive is 3,395,955 bytes with SHA-256
`2309DA64...FCBC94E8`; focused/restore/postflight evidence is 3,773 bytes with
SHA-256 `0FB89AD6...BEDCF561`. Postflight matched the active pointer,
deployment anchor, and all 25 protected production files; rc.3 commit
`d965927e`, PID 14283, audit sequence 4, and the no-pending state were
unchanged. This was the final disposable gate before the subsequently
authorized attended operation.

The annotated local `v1.3.0-rc.4` tag was then created and verified at exact
commit `25d1b541f62de15dc6f8e09036b5d588fcc95920` without publication. The
normal running-app updater advanced LC-001 from rc.3 `d965927e` to rc.4,
preserved the active pointer and all 25 protected files byte-for-byte, and
wrote update `534bde87...` with `relaunch_authorized`, no recovery required,
and an exact rc.4 deployment anchor.

After normal reopen, the operator selected committed source event 2,
transaction `50577384...`. The review showed only
`qualification-unverified` as removed by exact backup and passed hard
validation. Accepted restore transaction `53d4ede8...` created committed
event 5, restored raw `Locations.json` SHA-256 `3E5B4DE9...F3C7D02`, changed
no other governed file, preserved Camera semantic SHA-256
`FC7040A4...E9190B0`, removed the disposable target and authorization, and
left no pending transaction.

The closed-app hardware-free bootstrap reopened `ready`, validated sequence 5,
the exact bytes, event chain, source/restore manifests, deployment anchor, and
update receipt. The operator attested to no observed motion, pressure action,
or unexpected device activity. The final 4,689-byte private archive matched
on Pi and Windows at SHA-256 `198C533C...8FB9A17`. Production is clean and
closed at tagged rc.4.

## Post-rc.4 calibration, array, and development correction

After rc.4, a successful printer-head calibration updated only runtime-owned
`updated_at_utc` fields in active `CalibrationMemory/config.json` and
`CalibrationMemory/entities/reagents.json`. The production bootstrap rejected
the next launch because the migration tree manifest had classified every
migrated byte as permanently immutable. Separately, an array run reached its
pause position before well F2 was rejected because mathematically integral
NumPy-derived coordinates were not built-in Python integers. Both failures
were safe, but the array failure occurred too late in the command sequence.

The rc.5 behavior correction:

- keeps copied, staged, and unverified migration data byte-exact;
- treats validated active `CalibrationMemory/` and `calibration/` payloads as
  runtime-owned while retaining exact schema and required-seed checks;
- leaves governed configuration, target authorization, history, identity,
  activation, and deployment anchors under their existing protection;
- normalizes only already-integral derived well coordinates and rejects
  fractional, non-finite, or Boolean values; and
- preflights every remaining well and row-entry approach before locking the
  execution plan or queueing any hardware command.

An external development workflow was added so development does not require a
release per commit. It makes a new byte-verified clone outside the production
store, marks that clone as development-only, binds every launch to the exact
commit and operator, and defaults to `SimulatedMachine`. Hardware development
requires the exact attended confirmation; updater and firmware/DFU controls
remain blocked in both development modes. The normal production path and
deployment-anchor gate are unchanged.

Behavior commit `65ba38df2476812dcf70c850b99cbbb80fd22b46` passed:

- 73 migration-focused, 36 development/composition, and 282
  updater/deployment tests;
- the complete Windows suite: 5,461 passed and 156 skipped;
- Windows contained `virtual_print_array_96_v1`: 96/96;
- target-Pi focused tests: 53 passed;
- target-Pi external development clone/reopen with `SimulatedMachine`, blocked
  updater access, no physical interface, and commit-bound session evidence;
- target-Pi contained private-device SIL: 96/96; and
- read-only production inspection that accepted the runtime calibration files,
  reported only the expected pre-release rc.4 deployment-anchor mismatch, and
  left the complete 56-file production-tree fingerprint unchanged at
  `b31394ac...0ad64a`.

The first full-suite run against the rc.5 metadata tree had one balance-worker
cleanup timing failure after 5,460 other passes. Rc.5 does not change that
service or test. The failed case immediately passed alone, its complete
17-test module passed, and the required clean full rerun passed all 5,461
tests with 156 skipped.

Rc.5 release metadata commit
`34841fe0c9f54c6e1c1ceaad2b797ab661084430` passed 419 focused tests,
the clean 5,461-pass/156-skip full rerun, release/static checks, and the prior
Windows/Pi contained qualification. The annotated `v1.3.0-rc.5` tag was
published before `main`, peels exactly to that commit, and does not move any
earlier release tag.

For the enrolled rc.4 machine, support preserved the current runtime files
outside the production tree, proved that each differed from its verified
migration source only in `updated_at_utc`, and restored the exact source bytes:

- `CalibrationMemory/config.json` SHA-256
  `e616677c...de69a0`;
- `CalibrationMemory/entities/reagents.json` SHA-256
  `8af705f7...2ea41`; and
- unchanged active pointer SHA-256 `392c8aa8...6ac80`.

The restored tagged rc.4 bootstrap returned `ready`. Its first update check
then failed safely because a detached tag has no Git upstream. No Git or
machine-data mutation occurred. Support created local branch
`protected-update-rc5` at the same rc.4 commit and attached only its upstream
to `origin/main`; the commit and tree remained exact and the worktree clean.

Protected update `3255339d-8d1c-4274-b1ad-e159219d811b` then advanced rc.4
`25d1b541` to rc.5 `34841fe0`. Its terminal receipt and latest-result pointer
both authorized relaunch with recovery false, and the new deployment anchor
binds the exact rc.5 version/commit and update authorization. Normal first
launch displayed the successful rc.5 result. Live and closed postflights found
no process after close, clean Git state, bootstrap `ready`, history sequence
and event count 8/8, zero pending configuration files, unchanged
`Locations.json` SHA-256 `3e5b4de9...c5f3c7d02`, and no startup failure
marker.

Operator `Conary-Codex` confirmed no observed physical movement, pressure
action, or unexpected device activity during the update and first launch. The
technical archive and separately sealed operator attestation are recorded in
the evidence section below.

## Local tag, updater, and rollback qualification

Status: `passed` for the published rc.5 tag and attended protected rc.4-to-rc.5
update. Rc.2, rc.3, and rc.4 remain immutable; rc.5 peels exactly to
`34841fe0`. The update created a verified backup, preserved protected bytes,
wrote a relaunch-authorized terminal receipt and exact deployment anchor, and
reopened normally. Exact rc.6/rc.1 pilot and rollback lanes remain separate
open gates.

## Publication and rollout

Status: rc.5 release publication passed; staged fleet rollout is not yet
authorized.

The immutable rc.5 tag was pushed first, followed by the `main` release-index
commit, so no client could observe an advertised tag before the tag existed.
Remote rc.5 peels to `34841fe0`. LC-001 completed the attended protected
rc.4-to-rc.5 update. Rc.6 and rc.1 representative pilots, evidence reviews,
fleet batches, and the final rollout decision remain pending.

## Evidence

Private evidence root:
`verification_reports/machine_data_m7/`

No private evidence is tracked by Git. Final archives require a Pi-side and
post-transfer checksum match before their truncated hash is recorded here.

Final ignored evidence roots:

- `verification_reports/machine_data_m7/5f54a4a174cd50f145e1bfa98aa61535b7aa59e9/`;
- retrieved Pi SIL archive SHA-256 `4E4B6C16...9804C8C8`; and
- retrieved unattended archive SHA-256 `09D68B3C...0E98A0B7`.
- final rc.4 attended archive:
  `verification_reports/machine_data_m7/25d1b541f62de15dc6f8e09036b5d588fcc95920/labcraft-m7-rc4-attended-final-evidence.tar.gz`,
  SHA-256 `198C533C...8FB9A17`.
- final rc.5 technical archive:
  `verification_reports/machine_data_m7/34841fe0c9f54c6e1c1ceaad2b797ab661084430/labcraft-rc5-attended-34841fe0-evidence.tar.gz`,
  175,365 bytes, 79 safe members, SHA-256
  `FD74FEDE...14784CD2`;
- linked rc.5 operator attestation:
  `verification_reports/machine_data_m7/34841fe0c9f54c6e1c1ceaad2b797ab661084430/labcraft-rc5-attended-34841fe0-operator-attestation.json`,
  SHA-256 `3F037F7B...6F48AB6D`.

## Open gates

- Private operator, rc.6 pilot, rc.1 pilot, fixtures, and Camera-route approval.
- Attended firmware, HIL, and physical Camera-route qualification.
- Exact legacy updater/rollback qualification beyond the completed enrolled
  rc.3 -> rc.4 and rc.4 -> rc.5 forward-update lanes.
- Representative rc.6/rc.1 pilots and staged fleet rollout.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-20 | Published immutable rc.5 tag `34841fe0` before its `main` advertisement; preserved and exactly restored the two timestamp-only rc.4 runtime files from verified evidence; completed the attended protected rc.4 -> rc.5 update, normal first launch, ready/clean 8-event closed postflight, no-activity operator attestation, and matching technical archive SHA-256 `FD74FEDE...14784CD2` plus attestation SHA-256 `3F037F7B...6F48AB6D`. |
| 2026-08-20 | Recorded rc.5 behavior commit `65ba38df`, Windows and disposable-Pi qualification, unchanged production fingerprint, the isolated development lane, and the exact evidence-restoration/protected-update boundary required to recover from rc.4's overly broad runtime manifest rule. |
| 2026-08-20 | Created immutable local rc.4 tag at `25d1b541`; completed the normal protected rc.3 -> rc.4 update, exact sequence-5 restore of the disposable target, byte-identical Camera-safe closed-app postflight, zero-pending/no-motion attestation, and matching final archive SHA-256 `198C533C...8FB9A17`; retained publication and rollout gates. |
| 2026-08-20 | Froze coverage-complete rc.4 candidate `25d1b541`; passed exact-commit Windows 60-test/full-suite/release/SIL gates, Pi 60-test/independent exact-restore/private-device SIL gates, matching archives, and byte-identical production postflight; retained tag and attended update/restore as explicit authorization gates. |
| 2026-08-20 | Added direct calibrated-plate removal/exact-restore regression coverage after the first rc.4 disposable qualification; retained `3e451c01` as passing runtime evidence but reopened the exact-candidate gate because the tracked release tree changed. |
| 2026-08-20 | Froze rc.4 candidate `3e451c01`; passed exact-commit Windows and Pi focused tests, independent exact-restore, Windows/Pi contained SIL 96/96, private-device proof, matching evidence archives, and byte-identical production postflight; retained tag and attended recovery as explicit gates. |
| 2026-08-20 | Recorded the successful rc.3 protected recovery update and normal reopen, the guarded cancellation/addition/revocation/no-command passes, and the safe exact-restore deletion rejection; began the narrow rc.4 source-event/backup-bound correction and recorded its first 59 passing focused tests. |
| 2026-08-20 | Froze exact rc.3 candidate `d965927e`; passed 270 affected Pi tests, 96/96 private-device SIL, and a fresh disposable real-Git short-anchor rc.2 recovery/full-anchor rc.3 reopen; rechecked unchanged production and sealed two matching evidence archives. |
| 2026-08-20 | Implemented the rc.3 full-commit binding, exact rc.2 prefix compatibility, candidate-side recovery updater, exact-evidence rc.3 genesis enrollment, release metadata, and runbook; final Windows gates passed 602 focused/1 skipped, 5,430 full/156 skipped, and 96/96 contained SIL. |
| 2026-08-20 | Recorded the immutable rc.2 tag and fail-safe attended `source_binding_mismatch`, proved no Git/protected-data mutation, and began the rc.3 full-commit compatibility and attended recovery correction plan. |
| 2026-08-20 | Froze correction candidate `d59f73be`; passed exact-commit Windows focused/full/static/release/SIL and affected target-Pi focused/private-device SIL gates; proved production remained unchanged; stopped the enrolled update at the intentional release-tag boundary. |
| 2026-08-20 | Recorded passing attended backup/install/cancel/review/migration/activation/genesis gates on LC-001, then superseded `5f54a4a1` for release after its prefilled source failed closed and manual Camera transcription was judged unsafe; began the direct-source/read-only-Camera correction and required affected requalification. |
| 2026-08-20 | Created the in-progress completion record, closed the software traceability audit without a code change, recorded sanitized read-only Pi preflight evidence, and documented the untagged rc.2 candidate changes and remaining gates. |
| 2026-08-20 | Recorded the local `main` integration boundary and the passing pre-candidate focused, metadata, firmware-identity, and contained-SIL checks without claiming the exact-commit gate. |
| 2026-08-20 | Recorded and corrected the Pi SIL private-`/tmp` visibility gap; the failed attempt reached neither Python nor hardware, and exact-candidate qualification restarted. |
| 2026-08-20 | Recorded final candidate `5f54a4a1`, passing Windows focused/full/static/SIL gates, passing fresh target-Pi focused/cohort/private-device SIL gates, unchanged production state, and the independently rechecked evidence archives; retained attended/tag/publication/rollout gates. |
