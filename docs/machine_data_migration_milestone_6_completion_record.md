# Machine Data Migration Milestone 6 Completion Record

Status: `verified`

Completed: 2026-08-20

Implementation commit:
`9e666291bd3145c6073077c3d68a1a206da74710`

Parent documents:

- [Machine Data Migration and Location Safety Plan](machine_data_migration_and_location_safety_plan.md)
- [Milestone 6 Implementation Plan](machine_data_migration_milestone_6_implementation_plan.md)
- [Machine Data Update and Rollback Runbook](machine_data_update_and_rollback_runbook.md)

## Outcome

Milestone 6 is verified. Updates from an M6-capable release now require an
exact authorized machine/root binding, a reopened and verified external backup
before Git mutation, exact post-update protected bytes unless a reviewed schema
transition is declared, immutable external receipts, a deployment anchor, and
receipt-gated relaunch. Legacy rollback remains support-guided and is limited
to the three exact cataloged releases.

This verification does not create or tag `v1.3.0-rc.2`, change firmware, or
qualify physical motion. Those remain Milestone 7 responsibilities.

## Local implementation validation

Before the implementation commit, the Windows development checkout passed:

- 331 focused tests;
- 5,402 full-suite tests with 156 skipped;
- release metadata validation;
- compilation of every changed Python module;
- `git diff --check`; and
- contained, hardware-disabled `virtual_print_array_96_v1` at 96/96.

One discarded full-suite attempt placed pytest temporary data inside the
repository. Isolation tests correctly rejected that topology. A fresh run with
an external OS-temporary root produced the recorded 5,402-test pass.

## Target-Pi qualification boundary

The Pi production checkout was clean, had no running `App.py` process, and was
fast-forwarded from the verified Milestone 5 documentation commit to exact M6
implementation commit `9e666291`. Qualification used only fresh paths beneath
`/tmp/labcraft-m6-qualification.6v9xqqdd` and a copy of the verified M5
sequence-zero machine-data baseline.

The procedure did not launch production `App.py`, select the default
machine-data root, connect serial/camera/balance/GPIO, enable or home motors,
send firmware commands, change firmware, or flash the controller.

## Pi results

The disposable qualification passed:

- constrained rc.2 genesis deployment-anchor enrollment;
- identical external root, identity, and protected fingerprint when reopened
  from two detached checkouts;
- real-Git online fast-forward update with verified backup before merge,
  exact post-update bytes, immutable terminal receipt, deployment-anchor
  authorization, and detached reopen;
- the equivalent release-aware offline-bundle update with the same evidence
  shape and protected fingerprint;
- focused fault, recovery, schema-transition, exact legacy-profile/export,
  legacy-return conflict, updater/UI, bootstrap, transaction, writer-inventory,
  and zero-command construction gates: 331 passed with 120 warnings in
  34.74 seconds;
- contained hardware-disabled `virtual_print_array_96_v1`: 96/96 completions;
- release metadata validation, changed-module compilation, and `git diff
  --check`; and
- unchanged clean production commit and zero running `App.py` processes at
  closeout.

The online and offline lanes produced the same protected fingerprint:
`b60f95df133957f4c1f27f959c1458626c29cb66aa8fbf417d9690c269c867c8`.

## Pi measurements

- Verified baseline: 19 files, 912,080 bytes.
- Online verified backup: 939,492 bytes.
- Offline verified backup: 939,494 bytes.
- Available filesystem space during closeout: 160,416,075,776 bytes.
- Archive limits retained: 100,000 files; 4 GiB/member; 20 GiB total;
  compression ratio 200.
- Automatic deletion of backups or audit history remains disabled.

These measurements confirm substantial headroom for the qualified baseline;
they do not establish a universal fleet-sizing guarantee or relax any archive
limit.

## Evidence

The clean archive has 52 members: 40 payload files covered by
`evidence-sha256.txt`, the manifest and its successful recheck, plus directory
entries. It contains sanitized environment/results, the compatibility policy,
baseline hashes, updater logs, both verified update archives, immutable stage
records and terminal receipts, deployment anchors, SIL report, test output,
and closeout measurements.

Ignored local archive:
`verification_reports/labcraft-milestone6-pi-qualification-9e666291.tar.gz`

SHA-256:
`25a8b06906bfb4c8208db046172476303ec68b681b7a35cecc8bd6d3b679d7a8`

The archive hash was recomputed after transfer from the Pi and matched the
Pi-generated sidecar exactly. Generated evidence and credentials remain
ignored and are not part of either tracked Milestone 6 commit.

## Qualification-process notes

Pre-final attempts stopped on qualification-only harness assumptions: copied
tag hashes, a missing active-machine API argument, planned-versus-implemented
receipt filenames, and a release-candidate fixture passed to the stable-only
offline bundle generator. The final harness corrected those assumptions and
started from a new disposable root. A closeout pointer-key assumption and a
PowerShell remote-quoting mistake also stopped without changing product state;
partial closeout copies were moved outside the clean final evidence directory
before resealing.

No application defect was found during these stopped attempts. They did not
touch the production checkout beyond the authorized clean fast-forward, did
not use default machine data, and did not perform hardware actions.

## Remaining release work

Milestone 7 must still:

1. create and validate exact rc.2 release metadata and its machine-data
   declaration;
2. qualify controlled first-start migration from both deployed source cohorts;
3. verify genesis deployment anchors for those real migration paths;
4. perform attended firmware pairing and physical safety qualification; and
5. stage rollout without moving an existing release tag.

Until that work passes, this milestone verifies the preservation mechanism but
does not authorize deployment of rc.2 to physical machines.
