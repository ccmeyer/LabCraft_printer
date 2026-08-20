# Milestone 7 rc.4 Exact-Restore Correction Plan

Status: `implementation_complete` - the corrective code and pre-commit Windows
gates pass; the exact candidate commit, clean-commit Windows SIL,
disposable-Pi, tag, and attended LC-001 gates remain.

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

Exact-candidate clean-worktree SIL, disposable-Pi, tag, and attended recovery
results will be appended without rewriting this finding.
