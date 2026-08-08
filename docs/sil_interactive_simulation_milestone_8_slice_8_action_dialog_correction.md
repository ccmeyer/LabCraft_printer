# Milestone 8 Slice 8 Action-Dialog Focused Correction

## Trigger and root cause

The first complete default pytest gate reached 4,058 passes but failed the
in-process standard smoke when the Start Array button produced no activation.
The message-box driver immediately reported zero handled dialogs. Its recursive
`QTimer.singleShot` polling then remained live after the action failed and could
inspect or reject unrelated dialogs in later tests, producing cascading Qt and
simulation-session failures.

The affected call path is:

`QTest Start Array` -> normal View start callback -> ordered confirmation
`QMessageBox` dialogs -> Controller -> Model -> `SimulatedMachine`.

The initial failure occurred before the View callback reached Controller or
Model. No production MVC, simulator, protocol, firmware, Pi configuration, or
hardware behavior changes.

## Correction contract

- The action button uses the shared mouse-only bounded activation helper.
- Exactly one retry is permitted only after a proven zero-activation attempt.
- Success requires the entire exact, ordered message-box sequence.
- An activation without the ordered postcondition remains an ambiguous write
  and fails immediately.
- Modal polling uses one owned 5 ms `QTimer` that is stopped and disposed on
  every exit path; no recursive single-shot callback can outlive the action.
- Focused tests prove swallowed-first-click recovery and prove that a later
  unrelated modal remains untouched after exhausted retries.

Because this driver is an execution input, all Slice 8 Windows aggregates,
visible evidence, coverage, focused gates, and the complete default suite are
rerun. Rollback restores the prior single-click and recursive polling code and
removes the focused tests and this record.
