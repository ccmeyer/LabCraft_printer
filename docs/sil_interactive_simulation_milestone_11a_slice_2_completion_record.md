# Milestone 11A Slice 2 Completion Record

Status: complete

Date: 2026-08-08

Commit boundary: `test: qualify optimizer 360 editor and first requantization`

## Delivered

- Compared the case with the authoritative user-created
  `SIL_test_example-20260808_185108` experiment and corrected the test oracle
  rather than changing production optimizer behavior.
- Set the case to 2,000 nL and retained custom A–O well selection plus seed 4321.
- Froze optimized stocks 222.22222222222223/100/555.5555555555555/20 and the
  corresponding displayed stock IDs.
- Froze seven nearest-achievable targets and zero unreachable targets. Range A
  and Range C are exact; Range B achieves 0.45/1.8/4.05/8.1 and Range D achieves
  0.09/0.54/1.98.
- Drove blank fixed-stock fields and literal maxima through the real Qt editor,
  production optimizer, finalization, authoritative design/plan/progress/key
  files, and exact identity-keyed prepared count reconciliation.
- Applied Range A through the real calibration dialog at 1400 microseconds and
  10.8 nL, producing revisions 2–3 with zero progress and the literal
  post-calibration oracle.
- Preserved the existing Milestone 11 assertion wrapper and all production MVC,
  protocol, firmware, persisted-schema, and hardware behavior.

## Corrected aggregate contract

| Checkpoint | Range A | Range B | Range C | Range D | Water | Total |
|---|---:|---:|---:|---:|---:|---:|
| Prepared | 8,316 | 2,880 | 20,640 | 3,480 | 44,604 | 79,920 |
| Range A calibrated | 6,948 | 2,880 | 20,640 | 3,480 | 44,676 | 78,624 |
| Range B calibrated | 6,948 | 2,070 | 20,640 | 3,480 | 44,640 | 77,778 |
| Range C calibrated | 6,948 | 2,070 | 12,960 | 3,480 | 44,550 | 70,008 |
| Range D calibrated | 6,948 | 2,070 | 12,960 | 1,920 | 44,568 | 68,466 |
| Water calibrated/final | 6,948 | 2,070 | 12,960 | 1,920 | 22,310 | 46,208 |

## Validation

- Focused contract/assertion/Milestone 11 compatibility suite: 53 passed.
- Real Windows offscreen Qt editor and first-calibration checkpoint: 1 passed.
- The real checkpoint completed in 4.35 seconds at the focused 1000x test speed.
- No physical hardware or Pi lane was accessed.

## Deferred

Fresh-session rotation, remaining four calibrations, five stock passes, terminal
reload, scenario registration, retained direct/replay evidence, visible
qualification, regression suites, and the complete Python suite remain in
Slices 3–5.
