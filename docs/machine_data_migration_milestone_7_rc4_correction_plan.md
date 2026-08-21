# Milestone 7 rc.4 Exact-Restore Correction Plan

Status: `attended_recovery_complete` - the immutable local rc.4 tag targets
qualified commit `25d1b541`; LC-001 completed the protected update and exact
restore with matching closed-app evidence. Publication and staged rollout
remain separately authorized gates.

Prepared: 2026-08-20

Target release: `v1.3.0-rc.4`

Superseded release target: immutable `v1.3.0-rc.3` tag at `d965927e`

## Finding and safe production state

During the attended Milestone 7 guarded-change exercise on LC-001, the
operator added the disposable location `qualification-unverified`. The change
was committed and audited, its exact pre-change `Locations.json` was backed up,
and the new target was revoked from saved-target motion. The independent
no-command probe then proved that routing the revoked target issued zero route
or motion calls and opened no protected device.

The operator selected that committed event and requested **Restore Selected
Backup**. The guard rejected the preview because its import protection also
blanket-rejected removal of any saved location. That is correct for an
operator-selected import but incorrect for a restore of an already verified,
immutable pre-change backup whose purpose is to undo an added target.

The rejection was safe and auditable. It created one rejected event, changed
no governed configuration bytes, left no pending transaction, and left the
disposable target revoked. Camera coordinates and authorization were not
changed. The live rc.3 app and production machine data must remain in that
state until the corrected release has passed disposable qualification and an
attended protected update is explicitly authorized.

Private failure evidence was sealed before implementation. The retrieved
archive is
`verification_reports/machine_data_m7/d965927e88a9ce10217a0bf56a69789e9b0bd9f0/labcraft-rc3-restore-deletion-defect-evidence.tar.gz`
with SHA-256
`36100C35493591F3366AADE95FCD00DD9F72BC350694CCD54A1A0010A673E435`.

## Affected call path

```text
Configuration History -> Restore Selected Backup
-> View.ConfigurationHistoryWindow.restore_selected
-> Controller.prepare_configuration_restore
-> ConfigurationTransactionService.read_restore_preview
-> ConfigurationChangeGuard.assess
-> ConfigurationChangePreviewDialog
-> Controller.commit_guarded_configuration_proposal
-> ConfigurationTransactionService.restore_transaction
-> normal exact-byte journal/event/backup commit
```

The correction changes no firmware, device protocol, machine communication,
motion command, pressure, coordinate, obstacle, or timing behavior.

## Corrective contract

1. Coordinate deletion remains prohibited for governed imports.
2. A restore may preview a removed location or removed plate calibration only
   when it carries validated restore-precondition evidence.
3. That evidence binds the preview to the source transaction, machine ID,
   machine UUID, activation ID, immutable source-event manifest reference and
   SHA-256, backup fingerprint, and each backup member's filename, size, raw
   SHA-256, and semantic JSON SHA-256.
4. Restore loading obtains the manifest reference from the one immutable
   source event. It does not trust a hash recomputed from the current manifest.
5. Commit reopens the source event, manifest, and members and requires the
   result to equal the preview evidence. Missing, ambiguous, modified, stale,
   wrong-machine, or relabeled evidence fails before configuration mutation.
6. Exact raw backup bytes continue through the existing transaction journal,
   pre-change backup, event-chain, recovery, and reopen path.
7. Removed coordinates are displayed explicitly. The action identifies an
   exact-backup restore and the fact that changed targets are revoked.
8. Restored changed targets remain motion-blocked until a separate audited
   exact-value verification. A target removed by the backup is absent and
   therefore cannot be routed as a saved target.

## Files in scope

- `FreeRTOS-interface/ConfigurationSafetyPolicy.py`
- `FreeRTOS-interface/MachineDataTransactions.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/View.py`
- focused transaction, guarded-workflow, and preview tests
- `VERSION`, `CHANGELOG.md`, `releases/latest.json`, and
  `releases/v1.3.0-rc.4.json`
- Milestone 7 live plan, completion record, and support runbook

Firmware, protocol, Model, machine communication, coordinate values, and
production machine data are out of scope.

## Sequential implementation and qualification

1. Preserve and hash the rc.3 failure evidence; keep LC-001 unchanged.
2. Add a versioned restore-precondition schema and bind it to the immutable
   source event and verified backup inventory.
3. Permit removal previews only for that bound restore workflow; keep import
   deletion fail-closed.
4. Revalidate the source event, manifest, members, machine identity, proposal,
   policy, and current configuration at commit.
5. Make removal and exact-backup consequences explicit in the review UI.
6. Test add -> revoke -> preview removal -> exact restore, import deletion,
   missing evidence, substituted manifest evidence, post-preview backup
   tampering, exact raw bytes, revocation, and audit persistence.
7. Prepare rc.4 metadata and run focused, full, static, release, firmware
   identity, and contained Windows SIL gates.
8. Freeze one candidate commit and qualify it over SSH in a disposable Pi
   checkout/root. Exercise the exact defect without opening production data or
   hardware, then run private-device contained SIL.
9. Request explicit authorization before creating the rc.4 tag or changing
   the live Pi. After authorization, perform the protected rc.3 -> rc.4 update,
   reopen normally, and restore the selected rc.3 backup under motor
   inhibition. Prove exact original bytes, an immutable restore event, no
   pending transaction, absence of `qualification-unverified`, unchanged
   Camera evidence, and zero motion.

## Stop and rollback rules

- Do not manually delete the disposable target or edit `Locations.json`.
- Do not retry the rejected restore under rc.3.
- Do not create, move, delete, or retarget rc.2 or rc.3 tags.
- Do not tag rc.4 or update LC-001 until exact-commit Windows and disposable-Pi
  gates pass and the operator explicitly authorizes the next attended step.
- Any backup/event/identity mismatch, protected-byte drift, pending journal,
  hardware access, unexpected motion call, test timeout, or ambiguous evidence
  stops qualification with evidence preserved.
- Before a tag or attended update, rollback is a normal revert of the rc.4
  candidate commit. After an update transaction, use only the qualified M6
  receipt-gated recovery/rollback path; never edit the deployment anchor or
  external history by hand.

## Current implementation evidence

The first focused Windows gate passed 59 tests covering guarded workflows,
preview UI, and the transaction engine. The broader configuration,
authorization, update, and release group then passed 336 tests. The complete
suite passed 5,434 tests with 156 skipped and 605 warnings. A contained
simulation-only 96-well workflow completed 96/96 with exit code zero. Release
metadata validation, every release JSON, changed-file compilation,
`git diff --check`, and the unchanged-firmware check passed; the firmware
artifact remains SHA-256
`EDA070CE734D5167F0795FAF30DF461C8A07341E09CA698DE9D850315B0D5884`.

The regression set includes the attended failure's exact add/remove shape,
ordinary-import deletion rejection, required restore evidence,
substituted-manifest rejection, and backup tamper rejection. It also proves
the Controller path commits the original noncanonical raw bytes and stores the
restore evidence in the immutable audit event.

The exact-candidate and disposable-Pi results are recorded below. Tag and
attended recovery results remain pending and will be appended without
rewriting this finding.

## First candidate and disposable-Pi validation record

The first frozen rc.4 candidate was
`3e451c01e23f2957d12c8242c9c664bf8974aeae` (`fix: bind exact restore target
removal`). It is clean and untagged. On that exact commit:

- the narrow guarded-workflow/preview/transaction group passed 59 tests on
  Windows and again on the Pi;
- release metadata validation passed, firmware remained unchanged from rc.3,
  and clean-commit Windows contained SIL completed 96/96;
- the 52,114,801-byte complete Git transport bundle verified at SHA-256
  `C71CF5E9...C665A35D`;
- a detached clean Pi checkout under
  `/tmp/labcraft-m7-rc4-qualification.XIslw0` used only an ignored symlink to
  the already-qualified production interpreter;
- an independent disposable store committed an added revoked
  `qualification-unverified` target at sequence 1, previewed its explicit
  removal with source-event/manifest evidence, restored the exact original raw
  `Locations.json` bytes at sequence 2, removed only that target, and left no
  pending transaction without constructing hardware or the normal MVC;
- Pi private-device contained SIL completed 96/96, reported a clean candidate,
  private `/dev`, unshared network, read-only system/repository boundaries, and
  zero forbidden hardware access;
- the retrieved 3,395,318-byte SIL archive matched at SHA-256
  `71347FEC...7FCA74F4`; and
- the separate 3,814-byte focused/restore/postflight evidence archive matched
  at SHA-256 `1B46D436...C22C908D`.

The first disposable setup stopped after clone because its read-only
postflight named the deployment anchor under `metadata/` rather than
`update_history/`; no test, production write, or hardware action occurred. The
corrected setup used a fresh disposable directory. Windows execution policy,
then sandboxed child-SSH access, stopped two SIL-wrapper launches before a
remote test began. The first connected SIL launch identified the intentionally
absent candidate venv; adding the ignored interpreter shim resolved it. These
were harness/setup findings, not candidate failures.

Production postflight proved the rc.3 checkout remained clean at `d965927e`,
the normal app remained PID 14283, and the active pointer, deployment anchor,
and all 25 protected preflight files remained byte-identical. The preflight
already contained audit sequence 4: the fourth event is the operator's
cancelled rc.3 restore preview after the recorded sequence-3 rejection. That
event was not created by disposable qualification. Production remains at
sequence 4, with `qualification-unverified` still present and revoked, no
pending transaction, unchanged Camera evidence, and no rc.4 tag.

The post-qualification coverage review found that the correction's location
removal had a direct regression, while its parallel added-plate calibration
removal relied only on shared implementation and broader tests. A new focused
test now commits a calibrated disposable plate, verifies four explicit corner
removals in the bound restore preview, restores exact raw `Plates.json` bytes,
removes its authorization target, and leaves no pending transaction. The
narrow group passes 60 tests.

Because tracked test coverage changes the release tree, `3e451c01` is no
longer the tag target even though its runtime results remain valid evidence.
The coverage-complete candidate and its repeated gates are recorded next.

## Coverage-complete final candidate qualification

The final untagged rc.4 candidate is
`25d1b541f62de15dc6f8e09036b5d588fcc95920`. It contains the runtime
correction plus direct location- and calibrated-plate-removal exact-restore
coverage. On that exact commit:

- the Windows narrow group passed 60 tests, and the complete suite passed
  5,435 tests with 156 skipped and 605 warnings;
- an external unique pytest base was required because the default Windows
  temporary tree was inaccessible and an in-repository base correctly
  triggered simulation-containment failures; neither environmental attempt
  is counted as a candidate failure;
- release metadata validation, unchanged-firmware identity, clean-worktree
  checks, and Windows contained SIL 96/96 passed;
- the complete transport bundle verified at SHA-256
  `4445AC03BD55890D67A22C02B6E5C6B801F20615A8BCA4735A4E97E9AEB9A6E4`;
- a clean disposable Pi checkout at
  `/tmp/labcraft-m7-rc4-final.zORGEp/candidate` passed the same 60 tests;
- the independent Pi defect exercise added and revoked
  `qualification-unverified`, previewed its removal from immutable
  source-event/manifest evidence, restored exact original `Locations.json`
  bytes at sequence 2, and left no pending transaction without constructing
  hardware or the normal MVC;
- Pi private-device contained SIL completed 96/96 with functional status
  `pass`, acceptable noise, zero injected stalls, and a clean candidate;
- the retrieved 3,395,955-byte SIL archive matched at SHA-256
  `2309DA64E80AF7E7A6BA8D186A9401187B3B1B01CB669C0CAB3E82C3FCBC94E8`;
- the retrieved 3,773-byte focused/restore/postflight archive matched at
  SHA-256
  `0FB89AD6B77514BDE625E0554A9C0F7A2E380BC6B4B220691D62000FBEDCF561`;
  and
- postflight matched the active pointer, deployment anchor, and every one of
  the 25 protected production files. Production remained clean at rc.3
  `d965927e`, app PID 14283 and audit sequence 4 were unchanged, and no
  production pending transaction was created.

The implementation and exact-candidate disposable gates are complete. The
subsequently authorized local tag and attended production recovery are
recorded next.

## Attended tag, update, and exact-restore record

The annotated local `v1.3.0-rc.4` tag was created at and peeled exactly to
`25d1b541f62de15dc6f8e09036b5d588fcc95920`; tag-aware release validation
passed. The tag and reachable objects were staged directly in the LC-001
repository without publishing the tag or moving production `HEAD`.

With operator `Conary-Codex` attending, motor power inhibited, the motion
envelope clear, and the emergency stop immediately reachable, the normal
running-app updater moved clean rc.3 `d965927e` to tagged rc.4. Update
transaction `534bde87...`:

- preserved the active pointer and all 25 protected pre-update files
  byte-for-byte;
- wrote a `relaunch_authorized` receipt and rc.4 deployment anchor with no
  recovery requirement;
- reopened normally at rc.4 while audit sequence 4 and zero pending
  transactions remained; and
- left current Camera evidence identical to the immutable source backup.

The operator selected committed sequence-2 import transaction `50577384...`.
The rc.4 review displayed only `qualification-unverified` as **removed by
exact backup**, bound it to the verified source transaction/manifest, and
reported `hard_validation_passed`. The accepted restore created committed
sequence-5 restore transaction `53d4ede8...` and then:

- restored exact original `Locations.json` bytes at SHA-256
  `3E5B4DE97877C467395A9A63E1B8FC444359144BFA6AA395837EA99C5F3C7D02`;
- changed no other governed file;
- preserved lowercase `camera` semantic SHA-256
  `FC7040A4449092C24834225EC7FA208981756E59C3ED77DF9388C2BDAE9190B0`;
- removed both the disposable location and its authorization entry;
- created and verified the restore's pre-change backup; and
- left zero pending transactions.

After normal window closure, a hardware-free rc.4 bootstrap reopened the
external store as `ready`, validated the complete event chain at sequence 5,
and reconfirmed the clean tagged checkout, exact bytes, Camera, deployment
anchor, and update receipt. The operator explicitly attested that no physical
movement, pressure action, or unexpected device activity was observed during
the update or restore.

The final 4,689-byte private evidence archive matched on Pi and Windows at
SHA-256
`198C533C740C8C588C01B3224B74D5ABEEB0A798363134E833B302BEF8FB9A17`.
Production is clean and closed at rc.4. Do not move or retarget the rc.4 tag;
publication and staged rollout remain separately authorized.
