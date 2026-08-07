# Milestone 7 Slice 8 Visible Rack Focused Correction Plan

Status: `implemented and verified on 2026-08-07`

## Purpose

Close the remaining Slice 8 visible-Windows blocker without changing the
application MVC, simulator, protocol, firmware, or hardware behavior. The
failing call path is:

```text
RackDriver.swap_unassigned_head()
  -> shared bounded combobox mouse interaction
  -> RackBox.create_swap_callback() via QComboBox.currentIndexChanged
  -> Controller.swap_printer_head()
  -> PrinterHeadManager.swap_printer_head()
```

The two retained visible failures stopped before the rack callback. Both
failed at 1,536 completions while selecting `Virtual Stock 05 - 10 x`: no
activation was observed, the expected rack postcondition was false, and the
popup remained visible after both attempts. Their reports and SHA-256 values
are:

```text
verification_reports/milestone7-slice8-visible/virtual_print_array_384x10_v1/
  20260807T190354302230Z_composed/report.json
    f19e26154db55fc7dc9315807248eb21c96065fc25eaad0242149e06774e59ba
  20260807T190635866661Z_composed/report.json
    9f0a8bd7e9a680bc15ac0c982e3ea2dd2888371228ed1295ea6754deacf232ef
```

## Approved Correction

- Keep selection QTest mouse-only. Do not use `setCurrentIndex`, keyboard
  shortcuts, direct callback invocation, or Model mutation for UI coverage.
- Close and wait out stale popups, reacquire the popup and target after each
  model reset, wait for target geometry, and separate mouse press/release with
  bounded event processing.
- Wait for the authoritative rack postcondition rather than sampling
  immediately. An activation without the rack write fails as ambiguous.
- Permit one retry only when neither activation nor the postcondition occurs.
- Add detailed popup, target, activation, active-window, and postcondition
  diagnostics to a terminal failure.
- Add a short real-session regression that uses Model mutation only to seed
  ten heads, then truthfully exercises six consecutive swaps through the real
  rack UI. It performs no volume entry, calibration, array start, or printing.

## Exact Files

- `tools/virtual_workflows/page_drivers.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/system/test_virtual_workflow_rack_swap.py`
- this plan
- `docs/sil_interactive_simulation_milestone_7_slice_8_completion_record.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `README.md`

## Gates

Run the fast gates before any 384x10 execution:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_virtual_workflow_page_drivers.py -k "rack or combo"
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle tests/system/test_virtual_workflow_rack_swap.py
$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe -m pytest -q -s --run-sil-lifecycle tests/system/test_virtual_workflow_rack_swap.py
```

The visible rack-only node must pass in three fresh processes. Only then run
the focused composed 384x10 node, one visible 384x10 command, and that report's
exact emitted replay. Slice 8 closes only if both visible full-workflow runs
complete 3,840 operations with all required assertions, no unexpected dialog,
no starvation, and clean teardown. The full pytest suite remains deferred to
the final Milestone 7 validation.

## Implementation And Validation Record

The focused visible test proved that the popup geometry and target were
correct: the viewport owned the global target point, the target resolved to
row 1, and the list focus/current index moved to row 1. Qt nevertheless
suppressed the item release because it occurred inside the popup container's
post-open mouse-release guard. The reusable driver now waits out the bounded
application double-click interval plus 25 ms (capped at 750 ms) before sending
the distinct item press/release.

Validation completed as follows:

- 4 focused rack/combobox unit tests passed;
- the rack-only real-session node passed headlessly in 6.68 seconds;
- three fresh visible Windows rack-only processes passed all six swaps in
  8.71, 8.66, and 8.65 seconds;
- the targeted offscreen composed 384x10 node passed in 396.33 seconds; and
- the visible workflow and its exact emitted replay each completed
  3,840/3,840 operations with zero failed actions, failed assertions, or
  starvation, and with drained terminal queues.

The two visible reports are retained at:

```text
verification_reports/milestone7-slice8-visible-rack-correction/
  virtual_print_array_384x10_v1/
    20260807T193041485627Z_composed/report.json
    20260807T193834049228Z_composed/report.json
```

Their SHA-256 values are
`e1572ac7f0456661c3eba4d3e8f50aa661512763af6019a342947a6fd686dd69`
and
`598e88bbcfe91b608ba3d8784d4f81ca8307d01ffd8e2878d555fad40508bea1`.
Both reports are warnings only because informational candidate performance
observations fired; neither contains a functional or evidence failure.

## Risks And Rollback

A timing allowance could hide a failed click, so success still requires the
authoritative rack postcondition, retries remain capped at one, and ambiguous
activation fails closed. If the correction is ineffective, revert the shared
combobox synchronization, focused tests, and documentation. No production
data format, MVC behavior, simulator timing, protocol, firmware, or hardware
state is changed.
