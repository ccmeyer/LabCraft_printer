# Milestone 11A Slice 3 Completion Record

Status: complete

Date: 2026-08-08

Commit boundary: `test: add five-stock calibrated session rotation`

## Delivered

- Reused the clean authoritative session-rotation phase without adding a
  scenario-specific lifecycle branch.
- Closed session 1 after Range A calibration, created a genuinely new Qt
  application composition, loaded revision 3 from authoritative files while
  inactive, and activated it explicitly through the UI.
- Proved session 1 and session 2 use different application, observer, model,
  controller, and assertion identities, with no execution dispatched before
  activation.
- Generalized the joined rotation and remaining-calibration assertions to use
  case-owned stock IDs, printer-head IDs, revisions, calibration order, and
  literal count checkpoints.
- Applied Range B, Range C, Range D, and Water in order at 12.6, 14.4, 16.2,
  and 18.0 nL, respectively, and reconciled every checkpoint by
  `(stock_id, well_id)`.
- Joined all five calibration records to the corresponding stock, printer
  head, pulse width, effective volume, active-plan revision, and progress
  reference at revision 7.
- Preserved the existing Milestone 11 wrapper, assertion IDs, revision chain,
  fixtures, and three-stock behavior.

## Validation

- Focused contract/assertion/case suite: 46 passed.
- Real Windows offscreen fresh-session and five-calibration chain: 1 passed.
- Existing Milestone 11 real lifecycle compatibility scenario: 1 passed.
- Both real Qt checks completed cleanly with no session lock retained.
- No production MVC, protocol, firmware, physical hardware, or Pi behavior was
  changed or accessed.

## Deferred

The five stock execution passes, 1,800-intent and 46,208-droplet
reconciliation, terminal revision-8 reload, scenario registration, retained
direct/replay qualification, visible qualification, regression suites, and
complete Python suite remain in Slices 4-5.
