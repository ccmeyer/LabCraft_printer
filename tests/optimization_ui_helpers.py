"""Immediate job adapter for existing presentation-only tests with model doubles.

Thread ownership, isolation and asynchronous completion use the real dispatcher
in test_optimization_jobs; these tests isolate input validation and UI rendering.
"""
import copy
import pytest
import View
from OptimizationJobs import OptimizationOutcome


@pytest.fixture(autouse=True)
def immediate_optimization_jobs(monkeypatch):
    def submit(owner, kind, options, widgets, status, restore, completed, guard):
        outcome = OptimizationOutcome("presentation-test", "succeeded")
        message = getattr(owner, "_test_busy_message", None) or (
            "Calculating feasibility... this may take a moment on Raspberry Pi."
            if kind == "import" else "Updating reactions and stock solutions…"
        )
        with View._BusyUiContext(owner, message, widgets=widgets, status_setter=status, show_dialog=False):
            try:
                if kind == "import":
                    outcome.result = owner.model.build_import_feasibility_report(**options)
                else:
                    if kind == "import_apply":
                        reuse = owner.model.prepare_import_application(options["payload"], options["metadata"])
                        options = dict(options, reuse_allocation=bool(reuse.get("reused")),
                                       previous_result=reuse.get("result"))
                    if options.get("reuse_allocation"):
                        outcome.result = copy.deepcopy(options.get("previous_result") or {})
                        outcome.result.update(best=True, stock_allocation_reused=True)
                    else:
                        outcome.result = owner.model.optimize_stock_solutions(
                            quantum=0.1, max_refine=60, two_max_refine=40, allow_two=options["allow_two"],
                        )
                    if outcome.result.get("best"):
                        owner.model.generate_experiment()
            except Exception as exc:
                outcome.status, outcome.error = "failed", str(exc)
        return completed(outcome)
    monkeypatch.setattr(View, "_submit_optimization_ui_job", submit)


def complete_flow(**kwargs):
    callback = kwargs.get("on_complete")
    if callback:
        return callback()
    return True, {"best": True}
