# Audit Remediation Roadmap v2

## Summary
- Objective: close all open audit issues in `FreeRTOS-interface/` with hardware-free tests first and minimal production refactors.
- Scope: open IDs from `docs/audit/ISSUES.md` only.
- Strategy: each milestone closes explicit issue IDs with verification gates and named test deliverables.

## Milestone M1: Model File Integrity and Reset Semantics
- Closes IDs: `AUD-2026-006`, `AUD-2026-010`, `AUD-2026-018`
- Status: Done
- Commit: `<commit-hash-placeholder>`
- Focus:
  - Atomic/transactional writes for experiment/progress artifacts.
  - Correct exclusion reset behavior in well plate clearing.
  - Profile-correct defaults during experiment model reset.
- Primary test deliverables:
  - Fault-injection write interruption tests.
  - Exclusion set reset regression.
  - Legacy/current reset-default tests.
- Verification gate:
  - Corruption injection leaves parseable artifacts.
  - Clear/reset paths preserve expected eligibility/default invariants.
- Completed files:
  - `FreeRTOS-interface/Model.py`
  - `tests/test_model_atomic_writes.py`
  - `tests/test_wellplate_clear_all_wells.py`
  - `tests/test_experiment_model_reset_defaults.py`
- Notes:
  - Added atomic JSON write helper and routed design/progress writes through it.
  - Fixed exclusion reset typo in `clear_all_wells`.
  - Made reset defaults profile-aware (`legacy` vs `current` fill droplet defaults).
  - Preserved `excluded_wells` across `load_experiment_from_model` reload path to keep manual assignment exclusion behavior stable.

## Milestone M2: Protocol Parsing and ACK Contract Hardening
- Closes IDs: `AUD-2026-015`, `AUD-2026-019`
- Status: Done
- Commit: `<commit-hash-placeholder>`
- Focus:
  - Explicit malformed TLV diagnostics and envelope size guard behavior.
  - Deterministic ACK seq32/seq8 fallback cleanup matrix.
- Primary test deliverables:
  - Malformed TLV coverage (bad lengths/unknown tags).
  - Payload length boundary (`<=255`) enforcement tests.
  - ACK matching matrix tests (seq32 present/absent/mismatch/duplicate).
- Verification gate:
  - No silent protocol parse drops for known malformed cases.
  - Pending ACK map transitions are deterministic across ACK variants.
- Completed files:
  - `FreeRTOS-interface/Machine_FreeRTOS.py`
  - `tests/test_protocol_tlv_parser.py`
  - `tests/test_machine_ack_matching.py`
  - `tests/test_protocol_frame.py`
- Notes:
  - Added warning-level diagnostics for malformed/unknown/mismatched TLVs in parser path.
  - Added explicit payload envelope guards (`len(payload) <= 255`) in both `build_frame` and `Command.__init__`.
  - Added ACK matching matrix coverage for seq32/seq8 and duplicate ACK behaviors.

## Milestone M3: Controller Robustness and Static Guardrails
- Closes IDs: `AUD-2026-012`, `AUD-2026-013`, `AUD-2026-016`
- Focus:
  - Port classification correctness under descriptor/casing variants.
  - Signal disconnection scope safety.
  - Duplicate-method detection as static guard.
- Primary test deliverables:
  - Parameterized `_classify_port` variant tests.
  - Multi-subscriber disconnect-scoping test.
  - AST/static duplicate-method guard test.
- Verification gate:
  - Port selection behavior stable across realistic Windows descriptors.
  - Controller disconnect does not remove non-controller listeners.

## Milestone M4: View Designer Regression Coverage
- Closes IDs: none directly (coverage debt), reduces risk linked to active runtime workflows.
- Focus:
  - Designer lock precedence matrix (uploaded/manual/gripper).
  - Reopen/close cycle under active runtime state with no implicit apply/reset.
- Primary test deliverables:
  - Lock-state matrix tests.
  - Reopen integration-lite regression tests.
- Verification gate:
  - Reopen/close is view-safe during active print context.
  - Control enablement follows deterministic precedence rules.

## Milestone M5: Motion Semantics Documentation + Legacy Routing Coverage
- Closes IDs: `AUD-2026-020`
- Focus:
  - Explicit Z-axis convention guardrails in movement logic.
  - Legacy-profile safe-height routing coverage.
- Primary test deliverables:
  - Legacy safe-height route ordering test (`safe_z=5000`).
  - Convention assertion test(s)/documentation checks.
- Verification gate:
  - Current and legacy routing semantics are both asserted in tests.
  - Convention ambiguity removed for future maintainers.

## Milestone M6: App Startup and Disconnect Timing Resilience
- Closes IDs: `AUD-2026-011`, `AUD-2026-014`
- Focus:
  - Robust startup settings fallback behavior.
  - Non-blocking disconnect path timing behavior.
- Primary test deliverables:
  - Invalid/missing settings startup tests.
  - Disconnect responsiveness timing test.
- Verification gate:
  - Startup does not hard-fail on malformed settings.
  - Disconnect path remains responsive under event loop constraints.

## Exit Criteria (Roadmap v2 Complete)
- All open IDs in `docs/audit/ISSUES.md` marked resolved with code + test references.
- `docs/audit/TEST_GAPS.md` has no remaining high/medium hardware-free gaps.
- `pytest -q` passes hardware-free with deterministic outcomes.
