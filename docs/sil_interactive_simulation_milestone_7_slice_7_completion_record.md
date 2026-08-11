# Milestone 7 Slice 7 Completion Record

Status: `complete - targeted validation passed`

Completed against baseline
`af4ae5a7f5e5df7d7932b3f9936e164007b84715` on 2026-08-06 local time.
The complete Python suite remains intentionally deferred to final Milestone 7
validation.

## Outcome

Only `virtual_print_array_96_v1` moved from registry family
`virtual_print_array` to `composed_journey`. It now uses the same one-stock
body, normal Qt page drivers, semantic UI actions, stock-pass phase, payload,
generic report/evidence lifecycle, and teardown as the deterministic 24-well
smoke. Its definition contributes identity, the frozen schema-v1 fixture, a
48-completion midpoint, six screenshots, ten assertions, and an optional
regression evidence profile.

The profile reuses `ExecutionObserver` and owns bounded install, snapshot, and
reverse restoration for phase/persistence/progress observation, event-loop and
resource probes, queue-starvation evidence, pressure rendering, injected-stall
evidence, paired local Pi identity, and `stall_stacks.txt`. It does not select
wells, start printing, mutate an execution plan, or decide journey order.

Registry dispatch has no 96-well scenario-ID branch. The 384x10 stress and
disconnect work remain untouched. The direct
`run_virtual_print_array_scenario()` remains callable as a parity oracle.

## Preserved Inputs

- `virtual_print_array_96_v1.json` SHA-256:
  `25BEC67BE06A73D4C43766C328CE218731E577C75F8AEAE08021B81CD9FE8FF1`
- Windows accepted baseline SHA-256:
  `5EF1C4953727C614F8C4A9D5C861675B1CBC211E936EF9CA546B9A9037827229`
- Pi accepted baseline SHA-256:
  `5D0320E1666FE140259223976DAE070072FFBA1B2AF0BBB3A0EB91B35DB017F7`

The fixture and both accepted baselines remained byte-identical. No production
MVC, synthetic response, Pi script, firmware, protocol, or hardware file was
changed.

## Normal-UI Result

The composed path constructs the real application with hardware access
disabled and connects only to `SIMULATED`. It creates the 96-well design in
Experiment Editor, retains exact A-D serpentine execution order, stages the
head, uses the normal synthetic-calibration dialog, starts through the normal
array control, captures the midpoint at completion 48, and settles at exactly
96 completions, one `array_complete`, zero queue-starvation events, clean
terminal persistence, and restored observers.

The fixture's prepared ejection value is 5 nL and its design target is 10 nL.
The application-owned pulse-aware SIL model deterministically measures 9 nL
at the frozen 1300 us setting, so the real calibration dialog applies 9 nL.
This corrects the implementation plan's assumption that the normal UI would
apply the legacy shortcut's canned 10 nL value. A shared runtime assertion
requires the selected source volume, measured/applied volume, 1300 us pulse,
and 1.2 psi pressure to match the deterministic model. The fixture remains
unchanged and this evidence makes no physical volume-accuracy claim.

The exact visible milestones are:

```text
editor_opened
generated
ready
printing
mid_array
completed
```

Visual inspection exposed an early screenshot race: the authoritative run was
complete while the retained header still displayed 92/96. The shared
execution-boundary wait now requires the visible Experiment Guide projection
to show the exact terminal count before capture. The final visible screenshot
shows 96/96 and all four selected rows complete.

## Focused Validation

- reusable profile/composition/report/manifest/comparison/Pi contracts:
  `175 passed` in 89.11 seconds;
- composed success/parity/injected-stall/timeout plus retained direct oracle:
  `14 passed` in 31.85 seconds;
- unchanged 24-well smoke: `2 passed` in 4.44 seconds;
- post-settle focused composed success and injected-stall retry:
  `2 passed` in 20.89 seconds;
- final post-documentation assertion/phase/manifest/composed/direct/smoke
  sanity gate: `131 passed` in 36.75 seconds;
- `py_compile`, CLI `--help`, manifest validation, report-set generation, and
  comparison metric extraction passed;
- normal, injected-stall, and timeout reports all retained their expected
  evidence; failure paths retained traceback, screenshot, ledgers, event
  trace, manifest, and best-effort teardown.

The planned smoke command initially failed before collection because
`--run-sil-smoke` is not a registered option. The corrected direct module
command produced the two passing smoke tests.

One visible run failed closed when the normal calibration dialog did not open
within its bounded wait. Its immediate fresh-root retry passed, as did the
exact emitted replay. The two final retained reports are under:

```text
verification_reports/milestone7-slice7-visible-final-retry/
```

Their stable projection is equal for fixture hash/seed, ordered action IDs and
surfaces, assertion decisions, dialogs, well/completion order, calibration,
milestones/screenshots, persistence counts, metric shape, classification, and
cleanup. Generated identities, timestamps, paths, measured timings, and
identity-bearing fingerprints differ as expected.

No remote Pi operation and no full Python suite were run.

## Code Shape

Measured touched-runtime net growth is `+904` physical lines against the planned
`+550` gate. The 96-well definition remains a thin data composition: it shares
the 24-well body, action set, UI surfaces, and payload; its fixture/profile
loaders are six lines combined, schema-v1 projection is ten lines, and it adds
no QTest driver or registry scenario-ID conditional. The reusable regression
profile plus report projection is net +424, within the planned +450 sub-gate.

The variance consists of reusable evidence/profile ownership, shared
fail-closed assertions, schema-v1/v2 projection, legacy-compatible metric
projection, optional harness/config/replay fields, and visible UI-settle
evidence. It does not add a second workflow body, observer family, persistence
parser, report envelope, production path, or migrated scenario. Further line
reduction would require extracting large inline legacy-report blocks from the
still-shared 384x10 runner, which is intentionally deferred with that runner's
migration rather than risk a broad refactor in Slice 7.

## Risks And Rollback

- Synthetic 9 nL application evidence differs from the legacy canned 10 nL
  shortcut; both values are explicit and the fixture remains authoritative for
  its design target.
- The visible calibration dialog retains the known isolated timing retry
  policy; repeated failure blocks use rather than increasing timeouts.
- Optional observers must remain reverse-restored; success and injected tests
  assert restoration and shutdown state.
- Accepted timing baselines remain compatibility inputs, not newly accepted
  performance claims.

Rollback is limited to restoring `virtual_print_array_96_v1` in the registry
and manifest to `virtual_print_array`, then removing its composed definition
and focused tests. Independently reusable schema, profile, assertion, and
visible-settle helpers may remain only if the 24-well smoke and direct oracle
continue to pass. No production, firmware, protocol, simulator, Pi-host, or
hardware rollback is required.

## Next Boundary

Stop before 384x10 stress migration, disconnect work, performance remediation,
active parameter matrices, seeded sequence exploration, new product/simulator
fault injection, remote Pi work, firmware/protocol work, or hardware work. The
next slice requires a separately reviewed implementation plan. The full Python
suite remains reserved for the final Milestone 7 validation.
