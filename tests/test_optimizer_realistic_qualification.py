import copy
import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QThread

from Model import ExperimentModel
from OptimizationJobs import optimization_job_manager
from tests.optimizer_qualification_cases import (
    CASE_IDS, SYNTHETIC_IDS, MANUAL_IDS, MANIFEST, REFINEMENT,
    allocation_evidence, assert_physical_allocation, load_case, populate_model,
)
from tests.test_optimization_jobs import manager, request_for, wait_for, real_editor
from tools.optimizer_realistic_qualification import (
    assert_outputs_equal, import_payload, measure, new_editor, close_owner, save_evidence,
)


@pytest.mark.parametrize("name", SYNTHETIC_IDS)
def test_dense_explicit_inputs_have_realistic_cooccurrence_and_levels(name):
    case = load_case(name)
    info = case.describe()
    count = int(name.split("_")[-1])
    assert info == load_case(name).describe()
    assert info["authored_rows"] == int(name.split("_")[1])
    assert info["unique_compositions"] >= info["authored_rows"] * .9
    assert info["nonzero_reagents_per_row"] == {"min": count, "max": count}
    assert list(info["distinct_targets"].values()) == [3 + j % 6 for j in range(count)]
    assert len(set(case.design.Well)) == len(case.design)


@pytest.mark.parametrize("name,rows,n,active", [
    ("manual_5", 243, 5, 5), ("manual_8", 256, 8, 8),
    ("manual_groups", 144, 10, 8), ("three_pairs", 64, 5, 5),
])
def test_manual_dimensions_and_independent_choice_compositions(name, rows, n, active):
    case = load_case(name)
    info = case.describe()
    assert info["authored_rows"] == rows
    assert info["reagent_count"] == n
    assert info["nonzero_reagents_per_row"] == {"min": active, "max": active}
    if name == "manual_groups":
        for row in case.compositions():
            for group in ("Group1", "Group2"):
                assert sum(k.startswith(group) for k in row) == 1


def test_explicit_group_export_preserves_selections_and_duplicates():
    manual = load_case("manual_groups")
    imported = load_case("groups_import")
    assert [{k:v for k,v in r.items() if v} for r in imported.compositions()] == manual.compositions()
    manual.replicates = 2
    assert len(manual.compositions()) == 288


@pytest.mark.parametrize("name", ["dense_96_5", "manual_groups", "three_pairs"])
def test_worker_matches_full_sync_allocation_and_independent_arithmetic(qapp, manager, name):
    case = load_case(name)
    ranks = []
    for allow_two in (False, True):
        model = populate_model(case, allow_two)
        results = []
        manager.submit(model, request_for(model, allow_two=allow_two), results.append)
        wait_for(qapp, lambda: results, timeout=900)
        assert results[0].status == "succeeded", results[0].error
        sync = model.optimize_stock_solutions(**REFINEMENT, allow_two=allow_two)
        if not sync.get("best"):
            assert not results[0].result.get("best")
            ranks.append(None)
            continue
        model.generate_experiment()
        assert_outputs_equal(results[0].computed, model.capture_optimization_outputs())
        assert_physical_allocation(case, model)
        ev = allocation_evidence(model, sync)
        ranks.append(ev["rank"])
        if name == "three_pairs" and allow_two:
            assert len(ev["two_stock_keys"]) == 3
            assert ev["rank"][0] == 0
    if ranks[0] is not None:
        assert ranks[1] is not None and tuple(ranks[1]) <= tuple(ranks[0])


def test_zero_absent_options_replicates_and_additional_control():
    case = load_case("manual_groups")
    case.replicates = 2
    case.reagents[1].targets = (0., 1., 5.)
    model = populate_model(case, True)
    # Separate control does not select either choice group.
    model.set_additional_conditions([{"label":"control", "targets":{("Signal1", None):.5}}])
    case.additional = [{"Signal1":.5}]
    result = model.optimize_stock_solutions(**REFINEMENT, allow_two=True)
    assert result["best"]
    model.generate_experiment()
    assert_physical_allocation(case, model)


def test_manual_editor_route_uses_actual_controls(qapp, real_editor):
    result = measure(qapp, load_case("manual_groups"), True, "editor")
    assert not result.get("validation_error"), result.get("validation_error")
    assert result["allocation"]["stock_ids"]
    assert result["input_fingerprint"]


def test_real_import_and_apply_route_preserve_explicit_rows(qapp, real_editor):
    case = load_case("dense_96_5")
    payload = import_payload(qapp, case, True)
    result = measure(qapp, case, True, "editor", payload=payload)
    assert not result.get("validation_error"), result.get("validation_error")
    assert result["allocation"]["stock_ids"]


@pytest.mark.parametrize("failure", ["cancel", "stale", "interlock", "compute", "publish"])
def test_realistic_rejection_retains_committed_outputs_and_pending_actions(qapp, real_editor, monkeypatch, tmp_path, failure):
    case = load_case("manual_groups")
    editor = new_editor(case, True)
    done = []
    editor.optimization_finished.connect(lambda *args: done.append(args))
    try:
        editor._run_design_optimization_flow()
        wait_for(qapp, lambda: done, timeout=900)
        assert done.pop()[0]
        before = editor.model.capture_optimization_outputs()
        history = copy.deepcopy(editor.model.applied_imaging_calibrations)
        path = tmp_path / "design.json"
        path.write_bytes(b"previous committed file")
        continuations = []
        def pending():
            continuations.append(True)
            path.write_bytes(b"unexpected continuation")
        if failure == "compute":
            def fail(*args, **kwargs):
                raise ValueError("injected computation error")
            monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", fail)
        if failure == "publish":
            def fail(*args, **kwargs):
                raise ValueError("injected publication error")
            monkeypatch.setattr(editor.model, "install_optimization_outputs", fail)
        editor._mark_design_optimization_dirty()
        editor._run_design_optimization_flow(on_complete=pending)
        if failure == "cancel":
            editor._optimization_ui.cancel()
        elif failure == "stale":
            editor.model.metadata["replicates"] = 2
        elif failure == "interlock":
            monkeypatch.setattr(editor, "_gripper_edit_lock_is_active", lambda: True)
        wait_for(qapp, lambda: done, timeout=900)
        assert len(done) == 1 and not done[0][0]
        assert_outputs_equal(before, editor.model.capture_optimization_outputs())
        assert editor.model.applied_imaging_calibrations == history
        assert not continuations and path.read_bytes() == b"previous committed file"
        assert editor._design_optimization_dirty
    finally:
        close_owner(qapp, editor)


def test_external_data_is_required_and_hash_mismatch_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="fixture-root"):
        load_case("real_25")
    with pytest.raises(FileNotFoundError):
        load_case("real_25", tmp_path)
    spec = MANIFEST["cases"]["real_25"]
    target = tmp_path / spec["directory"] / spec["design"]
    target.parent.mkdir()
    target.write_text("not the qualified recipe")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_case("real_25", tmp_path)


@pytest.mark.skipif(not os.environ.get("LABCRAFT_OPTIMIZER_FIXTURE_ROOT"), reason="Explicit external-data qualification lane")
@pytest.mark.parametrize("name", list(MANIFEST["cases"]))
def test_external_real_design_dimensions_and_stock_bytes(name):
    case = load_case(name, os.environ["LABCRAFT_OPTIMIZER_FIXTURE_ROOT"])
    assert case.describe()["reagent_count"] == 9
    assert case.describe()["nonzero_reagents_per_row"] == {"min":7,"max":9}
    assert len(case.hashes) == 2


def test_incremental_evidence_replaces_atomically_without_losing_completed_cases(tmp_path):
    path = tmp_path / "evidence.json"
    evidence = {"cases":{"first":{"status":"passed"}}, "complete":False}
    save_evidence(path, evidence)
    evidence["cases"]["second"] = {"status":"blocked"}
    save_evidence(path, evidence)
    assert json.loads(path.read_text()) == evidence
    assert not path.with_suffix(".json.tmp").exists()


def test_watchdog_cancels_owned_child_and_records_failed_qualification(tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace
    import tools.optimizer_realistic_qualification as harness
    output = tmp_path / "result.json"
    class Child:
        pid = 987654
        returncode = None
        def __init__(self, *args, **kwargs):
            save_evidence(output.with_suffix(".watchdog.json"), {"started_monotonic":time.monotonic()-901,"interaction":"injected stalled case"})
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            assert output.with_suffix(".cancel").exists()
            self.returncode = 0
            return 0
    monkeypatch.setattr(harness.subprocess, "Popen", Child)
    monkeypatch.setattr(harness, "require_external", lambda path: Path(path).resolve())
    assert harness.supervise(SimpleNamespace(output=str(output))) == 1
    record = json.loads(output.with_suffix(".process.json").read_text())
    assert record["pid"] == Child.pid and record["owned_process_exited"]
    assert record["cleanup"] == ["cooperative cancellation requested"]
    assert json.loads(output.read_text())["blockers"][0]["error"] == "Interaction timeout"


def test_evidence_retries_windows_reader_lock_without_losing_previous_bytes(tmp_path, monkeypatch):
    import tools.optimizer_realistic_qualification as harness
    path = tmp_path / "evidence.json"
    save_evidence(path, {"previous": True})
    replace = harness.os.replace
    attempts = []
    def temporarily_locked(source, destination):
        attempts.append(True)
        if len(attempts) == 1:
            assert json.loads(path.read_text()) == {"previous": True}
            raise PermissionError("reader temporarily denies delete sharing")
        replace(source, destination)
    monkeypatch.setattr(harness.os, "replace", temporarily_locked)
    monkeypatch.setattr(harness.time, "sleep", lambda _: None)
    save_evidence(path, {"completed": True})
    assert len(attempts) == 2 and json.loads(path.read_text()) == {"completed": True}


def test_supervisor_refuses_to_overwrite_existing_evidence(tmp_path):
    from types import SimpleNamespace
    from tools.optimizer_realistic_qualification import supervise
    output = tmp_path / "result.json"
    output.write_text("prior evidence")
    with pytest.raises(ValueError, match="unique evidence"):
        supervise(SimpleNamespace(output=str(output)))
    assert output.read_text() == "prior evidence"


def test_interrupted_supervisor_only_cleans_up_its_owned_process(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import tools.optimizer_realistic_qualification as harness
    output = tmp_path / "result.json"
    actions, children = [], []
    class Child:
        pid = 987654
        returncode = None
        checks = 0
        def __init__(self, *args, **kwargs):
            children.append(self)
        def poll(self):
            self.checks += 1
            if self.checks == 1:
                raise KeyboardInterrupt()
            return self.returncode
        def wait(self, timeout):
            if self.returncode is None:
                raise harness.subprocess.TimeoutExpired("owned-child", timeout)
            return self.returncode
        def terminate(self):
            actions.append(self.pid)
            self.returncode = -15
    def killpg(pid, sig):
        actions.append(pid)
        children[0].returncode = -15
    monkeypatch.setattr(harness.subprocess, "Popen", Child)
    monkeypatch.setattr(harness, "require_external", lambda path: Path(path).resolve())
    monkeypatch.setattr(harness.os, "killpg", killpg, raising=False)
    with pytest.raises(KeyboardInterrupt):
        harness.supervise(SimpleNamespace(output=str(output)))
    assert actions == [Child.pid]
    record = json.loads(output.with_suffix(".process.json").read_text())
    assert record["owned_process_exited"] and record["cleanup"]


def test_external_guard_covers_other_registered_worktrees(tmp_path, monkeypatch):
    import tests.optimizer_qualification_cases as catalog
    other = tmp_path / "other-checkout"
    monkeypatch.setattr(catalog.subprocess, "check_output", lambda *args, **kwargs: f"worktree {other}\nHEAD deadbeef\n")
    with pytest.raises(ValueError, match="every Git worktree"):
        catalog.require_external(other / "fixtures")


def test_unknown_case_produces_explicit_selection_blocker(qapp, tmp_path):
    from types import SimpleNamespace
    from tools.optimizer_realistic_qualification import run_suite
    output = tmp_path / "result.json"
    assert run_suite(qapp, SimpleNamespace(case=["missing"], runs=1, fixture_root=None, output=str(output))) == 1
    assert json.loads(output.read_text())["blockers"][0]["stage"] == "case selection"
