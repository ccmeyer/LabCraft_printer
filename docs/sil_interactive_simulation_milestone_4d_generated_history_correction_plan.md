# Milestone 4D Generated Calibration History-Surface Correction

Baseline: clean worktree at `525bf9f713e45c8d3de348d8850dd9b658911ac6`,
with the Milestone 4D implementation intentionally uncommitted.

## Frozen behavior

Every distinct canonical synthetic calibration artifact remains visible after
subsequent generation, calibration-dialog reopening, and retained-root reload.
Rows are classified as `pending_apply`, `generated_unapplied`, or
`applied_history` and deduplicated by result fingerprint. Schema-v3 generated
rows may be applied later only when their exact application identity and the
normal idle/queue safety conditions still match. Pre-v3 evidence remains
read-only.

```text
Calibrate All
  -> persist canonical request/result once
  -> validate and rehydrate all retained artifact pairs
  -> classify and deduplicate retained results
  -> register the current pending candidate
  -> real summary, preview, and Apply path
  -> authoritative execution-calibration persistence
  -> promote the matching row without duplication
```

Generated evidence is not authoritative applied state.
`execution_calibrations.json` and SIL state projection continue to count only
applied records. Physical `calibration.json`, provider schemas, canonical
fingerprints, Controller, SimMachine, firmware, protocol, and hardware paths do
not change.

## Retained failure evidence

Session `20260805T161818192822Z-349c99f33bc9` is preserved unchanged. It proves
that three canonical result artifacts survived, while only the Droplet to
Stream and Stream to Droplet results reached authoritative Apply. The nominal
droplet result disappeared from the table because the manager owned one
transient candidate, not because any retained artifact was overwritten.

## Gates

Focused manager, adapter, UI, table, and normal-UI lifecycle tests must prove
multi-result retention, exact-fingerprint deduplication, applied-state
promotion, retained-root rehydration, reusable schema-v3 evidence, read-only
pre-v3 evidence, stale-identity rejection, idle/queue enforcement, strict
artifact-pair validation, and unchanged production behavior. Run Python
compilation, `git diff --check`, and `git status --short`; do not run the full
pytest suite for this correction.

The visible gate generates an unapplied 18 nL droplet result, applies a 60 nL
Droplet to Stream result, applies a 9 nL Stream to Droplet result, and verifies
all three rows across dialog reopen and retained-root reload. The retained
unapplied droplet result is then applied and promoted without duplication.

## Rollback

Rollback removes the retained generated-history classification and focused
regressions, restoring the single pending-candidate surface. No artifact,
experiment, schema, firmware, protocol, or hardware migration is required.
