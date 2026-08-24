from __future__ import annotations

from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "run_machine_data_bootstrap_only.py"
SPEC = importlib.util.spec_from_file_location("run_machine_data_bootstrap_only", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class _Field:
    def __init__(self):
        self.text = ""
        self.enabled = True
        self.read_only = False

    def setText(self, value):
        self.text = str(value)

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setReadOnly(self, value):
        self.read_only = bool(value)


def _install_fake_modules(monkeypatch, tmp_path, *, accepted=False):
    source = tmp_path / "source"
    (source / "local").mkdir(parents=True)
    (source / "VERSION").write_text("v1.3.0-rc.7\n", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "FreeRTOS-interface").mkdir()
    machine_data = tmp_path / "machine-data"

    app_version = ModuleType("AppVersion")
    app_version.get_app_version = lambda _repo: "v1.3.0-rc.7"
    app_version.get_app_commit = lambda _repo: "a" * 40

    machine_data_module = ModuleType("MachineData")
    machine_data_module.resolve_machine_data_base = lambda **_kwargs: SimpleNamespace(
        root=machine_data,
        active_machine_path=machine_data / "active_machine.json",
        machines_root=machine_data / "machines",
    )

    class BootstrapState(Enum):
        CANDIDATE_SELECTION_REQUIRED = "candidate_selection_required"
        READY = "ready"

    class FakeBootstrap:
        def __init__(self, base, **_kwargs):
            self.base = base

        def inspect(self):
            return SimpleNamespace(state=BootstrapState.CANDIDATE_SELECTION_REQUIRED)

        def inspect_candidate(self, _selection):
            return SimpleNamespace(
                normalized_source=source.resolve(),
                is_importable=True,
                legacy_identity=None,
                identity_status="unassigned",
            )

    bootstrap_module = ModuleType("MachineDataBootstrap")
    bootstrap_module.BootstrapState = BootstrapState
    bootstrap_module.MachineDataBootstrap = FakeBootstrap

    migration_module = ModuleType("MachineDataMigration")
    migration_module.CandidateSourceKind = SimpleNamespace(
        OPERATOR_SELECTED_WRAPPER="operator_selected_wrapper"
    )
    migration_module.CandidateSelection = lambda *args: args

    class FakeDialog:
        instance = None

        def __init__(self, bootstrap, current_checkout_local=None):
            FakeDialog.instance = self
            self.bootstrap = bootstrap
            self.current_checkout_local = current_checkout_local
            self.source_path = _Field()
            self.browse_folder_button = _Field()
            self.browse_zip_button = _Field()
            self.machine_id = _Field()
            self.operator = _Field()
            self.source_reason = _Field()
            self.failure_code = None
            self.failure_message = None
            self.context = None

        def setWindowTitle(self, _title):
            pass

        def exec(self):
            from PySide6 import QtWidgets

            if accepted:
                machine_uuid = "00000000-0000-0000-0000-000000000001"
                machine_root = machine_data / "machines" / machine_uuid
                metadata = machine_root / "metadata"
                update_history = machine_root / "update_history"
                metadata.mkdir(parents=True)
                update_history.mkdir()
                (machine_data / "active_machine.json").write_text("{}\n", encoding="utf-8")
                evidence = {
                    "identity_path": metadata / "machine_identity.json",
                    "candidate_evidence_path": metadata / "candidate_evidence.json",
                    "migration_receipt_path": metadata / "migration_receipt.json",
                    "migration_tree_manifest_path": metadata / "migration_tree_manifest.json",
                    "verification_path": metadata / "verification.json",
                    "activation_receipt_path": metadata / "activation_receipt.json",
                    "deployment_anchor_path": update_history / "deployment_anchor.json",
                }
                for path in evidence.values():
                    path.write_text("{}\n", encoding="utf-8")
                closed = {"value": False}
                context = SimpleNamespace(
                    active_machine=SimpleNamespace(
                        machine_id="LC-TEST",
                        machine_uuid=machine_uuid,
                        activation_id="00000000-0000-0000-0000-000000000002",
                        migration_id="00000000-0000-0000-0000-000000000003",
                    ),
                    paths=SimpleNamespace(
                        base=SimpleNamespace(active_machine_path=machine_data / "active_machine.json"),
                        machine_root=machine_root,
                        **evidence,
                    ),
                    close=lambda: closed.__setitem__("value", True),
                    closed=closed,
                )
                self.context = context
            return (
                QtWidgets.QDialog.DialogCode.Accepted
                if accepted
                else QtWidgets.QDialog.DialogCode.Rejected
            )

    dialog_module = ModuleType("MachineDataBootstrapDialog")
    dialog_module.MachineDataBootstrapDialog = FakeDialog
    for name, module in (
        ("AppVersion", app_version),
        ("MachineData", machine_data_module),
        ("MachineDataBootstrap", bootstrap_module),
        ("MachineDataMigration", migration_module),
        ("MachineDataBootstrapDialog", dialog_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    for name in list(sys.modules):
        if name in runner.FORBIDDEN_MODULES or any(
            name.startswith(prefix) for prefix in runner.FORBIDDEN_PREFIXES
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
    return source, repo, machine_data, FakeDialog


def _args(source, repo, machine_data, result_path, outcome):
    return runner.build_parser().parse_args(
        [
            "--repo-root", str(repo),
            "--source-wrapper", str(source),
            "--machine-data-root", str(machine_data),
            "--expected-version", "v1.3.0-rc.7",
            "--expected-commit", "a" * 40,
            "--expected-machine-id", "LC-TEST",
            "--operator", "Operator",
            "--source-reason", "Preserved backup",
            "--expected-outcome", outcome,
            "--result-path", str(result_path),
        ]
    )


def test_regular_tree_evidence_is_content_bound(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.json").write_text("{}\n", encoding="utf-8")
    first = runner.regular_tree_evidence(root)
    (root / "a.json").write_text('{"changed": true}\n', encoding="utf-8")
    second = runner.regular_tree_evidence(root)
    assert first["tree_sha256"] != second["tree_sha256"]


def test_cancelled_bootstrap_locks_source_and_writes_no_machine_data(qapp, monkeypatch, tmp_path):
    source, repo, machine_data, dialog_type = _install_fake_modules(
        monkeypatch, tmp_path, accepted=False
    )
    result = runner.run_bootstrap_only(
        _args(source, repo, machine_data, tmp_path / "evidence" / "result.json", "cancelled")
    )
    assert result["status"] == "passed"
    assert result["outcome"] == "cancelled"
    assert not machine_data.exists()
    dialog = dialog_type.instance
    assert dialog.source_path.text == str(source.resolve())
    assert dialog.source_path.read_only is True
    assert dialog.browse_folder_button.enabled is False
    assert dialog.browse_zip_button.enabled is False
    assert dialog.machine_id.text == "LC-TEST"
    assert dialog.machine_id.read_only is True
    assert dialog.operator.read_only is True
    assert dialog.source_reason.read_only is True
    assert result["forbidden_imports"] == []


def test_destination_and_source_must_be_disjoint(monkeypatch, tmp_path):
    source, repo, _machine_data, _dialog = _install_fake_modules(
        monkeypatch, tmp_path, accepted=False
    )
    args = _args(
        source,
        repo,
        source / "machine-data",
        tmp_path / "evidence" / "result.json",
        "cancelled",
    )
    try:
        runner.run_bootstrap_only(args)
    except runner.BootstrapOnlyError as exc:
        assert "disjoint" in str(exc)
    else:
        raise AssertionError("Nested destination was accepted")


def test_successful_activation_closes_context_and_reports_evidence(qapp, monkeypatch, tmp_path):
    source, repo, machine_data, dialog_type = _install_fake_modules(
        monkeypatch, tmp_path, accepted=True
    )
    result = runner.run_bootstrap_only(
        _args(source, repo, machine_data, tmp_path / "evidence" / "result.json", "activated")
    )
    assert result["outcome"] == "activated"
    assert result["active_machine"]["machine_id"] == "LC-TEST"
    assert set(result["active_machine"]["evidence_sha256"]) == {
        "active_machine",
        "machine_identity",
        "candidate_evidence",
        "migration_receipt",
        "migration_tree_manifest",
        "verification",
        "activation_receipt",
        "deployment_anchor",
    }
    assert dialog_type.instance.context.closed["value"] is True
    assert result["forbidden_imports"] == []


def test_expected_commit_mismatch_fails_before_dialog(qapp, monkeypatch, tmp_path):
    source, repo, machine_data, dialog_type = _install_fake_modules(
        monkeypatch, tmp_path, accepted=False
    )
    args = _args(source, repo, machine_data, tmp_path / "result.json", "cancelled")
    args.expected_commit = "b" * 40
    try:
        runner.run_bootstrap_only(args)
    except runner.BootstrapOnlyError as exc:
        assert "commit differs" in str(exc)
    else:
        raise AssertionError("Commit mismatch was accepted")
    assert dialog_type.instance is None


def test_result_path_cannot_be_inside_machine_data(monkeypatch, tmp_path):
    source, repo, machine_data, _dialog = _install_fake_modules(
        monkeypatch, tmp_path, accepted=False
    )
    args = _args(source, repo, machine_data, machine_data / "result.json", "cancelled")
    try:
        runner.run_bootstrap_only(args)
    except runner.BootstrapOnlyError as exc:
        assert "inside the machine data" in str(exc)
    else:
        raise AssertionError("Machine-data-contained result path was accepted")


def test_main_does_not_write_a_failure_result_into_machine_data(
    monkeypatch, tmp_path
):
    source, repo, machine_data, _dialog = _install_fake_modules(
        monkeypatch, tmp_path, accepted=False
    )
    result = machine_data / "unsafe-result.json"
    code = runner.main(
        [
            "--repo-root", str(repo),
            "--source-wrapper", str(source),
            "--machine-data-root", str(machine_data),
            "--expected-version", "v1.3.0-rc.7",
            "--expected-commit", "a" * 40,
            "--expected-machine-id", "LC-TEST",
            "--operator", "Operator",
            "--source-reason", "Preserved backup",
            "--expected-outcome", "cancelled",
            "--result-path", str(result),
        ]
    )
    assert code == 1
    assert not result.exists()


def test_forbidden_import_fails_before_dialog(qapp, monkeypatch, tmp_path):
    source, repo, machine_data, dialog_type = _install_fake_modules(
        monkeypatch, tmp_path, accepted=False
    )
    monkeypatch.setitem(sys.modules, "hardware.unexpected", ModuleType("hardware.unexpected"))
    try:
        runner.run_bootstrap_only(
            _args(source, repo, machine_data, tmp_path / "result.json", "cancelled")
        )
    except runner.BootstrapOnlyError as exc:
        assert "forbidden modules" in str(exc)
    else:
        raise AssertionError("Forbidden bootstrap import was accepted")
    assert dialog_type.instance is None


def test_forbidden_import_inventory_is_explicit(monkeypatch):
    module = ModuleType("hardware.fake")
    monkeypatch.setitem(sys.modules, "hardware.fake", module)
    assert "hardware.fake" in runner.forbidden_imports()
