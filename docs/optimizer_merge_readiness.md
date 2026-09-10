# Optimizer merge-readiness checks

This bounded lane complements the optimizer, calibration, persistence and Qt
worker suites. It does not replace them or certify the entire realistic timing
matrix. Final measurements, screenshots and protected-state receipts belong in
an external report bound to the tested SHA and its fetched `origin/main` base.

## Stock CSV ejection-volume contract

The stock CSV parser in the original `main` base and in this branch uses the
printing-mode default: 9 nL for Droplet and the configured Stream-mode default.
It does not import per-stock ejection volumes. The wizard displays the effective
value in **Ejection Vol (nL)** and transfers that value with the allocation to
the editor. Stock concentrations are upper bounds, not fixed-stock selections.

Nonempty `droplet_volume_nL`, `droplet_nL`, or `ejection_volume_nL` columns now
produce an explicit warning (normal column-name normalization also accepts
spaces/capitalization). They do not override the mode default. Errors remain
the primary wizard status when an import is infeasible. To use another volume,
apply a feasible design, edit **Ejection Vol (nL)** in the editor, and recalculate
before saving or finalizing. Adding CSV volume overrides is a separate feature;
this check does not infer calibration from nominal CSV values.

## Dense single-stock feasibility

For the catalog's `dense_384_10` fixture, every reagent's smallest positive
target must remain nonzero. Under the current nearest-integer-drop rule, a
single stock's delivered concentration per drop must be below twice that
smallest target. Using the limiting largest step independently for every
reagent gives the smallest possible counts for this fixture's level schedule.

An exact-rational calculation gives a lower bound of **1,251 nL at well M22**
with 9 nL drops, versus the 1,000 nL budget. A concrete set of concentrations
just below those limits attains that bound and stays below the stock bounds.
At 10 nL the corresponding lower bound is **1,390 nL**. Thus the selected
1,323 nL single-stock rejection is not evidence of a missed feasible allocation:
even the limiting alternative cannot fit while preserving positive targets.
Two-stock mode can make this fixture feasible. The proof is specific to these
inputs and quantization rules, not a general optimality claim about the search.

The UI check also uses a fixed-stock example where requested 0.5 and 0.55 mM
both achieve 0.5 mM. It verifies the grouped-level status, achieved-concentration
tooltip, and Save Draft/reload preservation. Approximation is permitted and
displayed; this lane does not add a new acknowledgment or change saved results.

## Bounded visible walkthrough

```powershell
.\env\Scripts\python.exe -B -m pytest -q tests/test_optimizer_merge_readiness.py `
  --basetemp "$env:TEMP\optimizer-merge-tests-<unique-id>"
.\env\Scripts\python.exe -B tools/qualify_optimizer_merge_readiness.py --visible `
  --output "$env:TEMP\optimizer-merge-ui-<unique-id>.json"
```

Use absolute external output paths and a unique prefix. Without `--visible`,
the same script is an offscreen qualification probe. The script uses real Qt
editor/wizard controls and the actual queued worker, with simulated dependencies.
It is a scripted visual inspection aid, not a claim of human operator acceptance.
No experiments are saved by the walkthrough and no hardware is opened.

Scenes cover a manual grouped design, explicit grouped import and Apply, a dense
384-row import/recalculation, slow Auto switching to explicit recalculation,
cancellation retaining committed outputs, explicit retry, close while active,
and reopening. Evidence includes phase/status text, window/display dimensions,
PNG captures, terminal outcomes and clean worker shutdown. The external
supervisor caps the campaign at ten minutes, requests cooperative cancellation,
and only escalates against its owned process tree. It never terminates a Qt
thread. Timing values are observations, not comparative performance gates.

On Pi, first push the exact candidate and follow the existing wrapper
**Status -> Sync -> Validate** workflow. Run focused integration tests and this
script from the validated development checkout with the shared interpreter
read-only, bytecode disabled, and external output/cache directories. `--visible`
requires an existing Pi desktop session and rejects a headless Qt platform.
Use wrapper `Launch -LaunchMode Visible` for the full application smoke check,
then the offscreen lane and final Status/protected-state comparison. Do not
invoke the production application or install packages to make this check pass.

## Integration and accepted limitations

Run the Windows full suite on the final candidate incorporating fetched `main`.
Set `LABCRAFT_OPTIMIZER_FIXTURE_ROOT` to the external, hash-verified fixture root
for qualification, including the manifest's two `additional_files`. Six legacy
recipe tests previously depended on ignored checkout-local experiments; they now
use this explicit lane. Without the variable they are separately reported as
skipped; with it, absent or mismatched files fail rather than silently skipping.
Pi integration covers optimizer/worker/editor/import, calibration persistence,
execution-plan revisions, interlocks, and virtual-workflow assertions. Review
snapshot isolation, stale-result rejection, post-publication continuations,
calibration/save/reload/finalization, and progress guards together. Compiler-only
native experiments remain opt-in and are not imported by the application.

The previously measured Pi 263-354 ms worker-completion pauses remain failures
of the existing 250 ms diagnostic qualification gate. Given the operator's
accepted tradeoff, these are a documented nonblocking merge limitation; the
gate and raw results are not weakened or relabeled as passing. Cancellation
and correct publication remain required. The bounded memory test passed on
Windows/Pi with modest RSS drift and nearly steady Python-block counts; it
does not prove unlimited-session leak freedom. Native acceleration and further
cleanup tuning remain deferred. Do not claim full realistic timing qualification.

The subsequent full Pi matrix on reviewed application revision
`cb9a54bc5c631bc7cc7dfbca5039c380932f2f65` recorded **16 passed and 33 blocked**
across 49 routes. Fifteen routes exceeded 250 ms, with a maximum **372.7 ms**;
other overlapping blockers were 14 infeasible single-stock/Apply prerequisites
and eight unsupported requested import-volume cases. The operator reviewed these
results and explicitly accepted the remaining large-calculation pauses as
nonblocking for merge and RC preparation. This extends the earlier acceptance
to the current measurements without changing the gate or calling it a pass.
All 380 exercised cancellation checks were below 41.6 ms, with no cancellation
state failure or two-stock rank regression. Successful allocations matched the
synchronous reference calculations.

The current bounded Pi memory lane passed two warm-up and six measured rounds:
median RSS growth was **21.2 MiB** against a **32 MiB** allowance, with zero live
closed editors at every idle endpoint. The positive RSS slope remains an
observation for longer sessions, not proof of a leak or of unlimited stability.
Wrapper smoke and protected-state postflight passed. The subsequent attended
hardware-capable launch on `fd0e94c0` passed with operator-reported expected
behavior, normal exit, exact released restore, complete SAFE validation and
production-ready postflight. Specific connected motion or printing scenarios
were not recorded and are not claimed as qualified. The operator authorized
merge and RC publication with the recorded limitations. Software timing
acceptance does not qualify physical operation. Full evidence and release status
are summarized in `docs/mcu_liveness_editor_milestone.md`.

Rollback the warning/check commit with a normal revert and synchronize the
development checkout through the wrapper. No data migration, calibration-history
rewrite, firmware update or production-environment change is required.
Current rc.13 preparation retains rc.12's version-4 execution-calibration records
and both execution-data compatibility requirements. Its release rollback target
remains null until an exact compatible target is qualified. Preserve original
history and use the protected current-version or qualified compatible-bundle
recovery route; do not strip audit fields, rewrite calibration files, or manually
switch production code to force an older application to load them.
