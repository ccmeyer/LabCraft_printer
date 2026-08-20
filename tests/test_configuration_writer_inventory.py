import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "FreeRTOS-interface"
DIRECT_WRITER_METHODS = {
    "save_locations",
    "update_calibration_data",
    "save_calibrations_to_file",
    "store_calibrations",
}

# These calls are either the guarded legacy compatibility path or the guarded
# implementation inside the Model classes. Canonical production objects reject
# them, and every active UI path first selects the Controller transaction API.
EXPECTED_CALL_SITES = {
    ("CalibrationClasses/View.py", "RackCalibrationFixDialog.save_calibrations", "update_calibration_data"),
    ("Controller.py", "Controller.commit_named_location", "save_locations"),
    ("Controller.py", "Controller.save_locations", "save_locations"),
    ("Model.py", "Model.update_rack_calibration", "save_locations"),
    ("Model.py", "RackModel.update_calibration_data", "save_calibrations_to_file"),
    ("Model.py", "RackModel.update_calibration_data", "store_calibrations"),
    ("Model.py", "WellPlate.update_calibration_data", "save_calibrations_to_file"),
    ("Model.py", "WellPlate.update_calibration_data", "store_calibrations"),
    ("View.py", "RackBox._run_guided_rack_calibration", "update_calibration_data"),
    ("View.py", "WellPlateWidget.open_calibration_dialog", "update_calibration_data"),
}


class _WriterCallVisitor(ast.NodeVisitor):
    def __init__(self, relative_path):
        self.relative_path = relative_path
        self.scope = []
        self.calls = set()

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in DIRECT_WRITER_METHODS:
            self.calls.add(
                (self.relative_path, ".".join(self.scope), node.func.attr)
            )
        self.generic_visit(node)


def test_direct_governed_writer_call_inventory_is_explicit_and_unchanged():
    actual = set()
    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(APP_ROOT).as_posix()
        visitor = _WriterCallVisitor(relative)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig")))
        actual.update(visitor.calls)

    assert actual == EXPECTED_CALL_SITES
