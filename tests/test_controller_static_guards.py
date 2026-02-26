import ast
from pathlib import Path


def test_controller_has_no_duplicate_method_definitions():
    controller_path = Path(__file__).resolve().parents[1] / "FreeRTOS-interface" / "Controller.py"
    tree = ast.parse(controller_path.read_text(encoding="utf-8"))

    controller_cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Controller":
            controller_cls = node
            break

    assert controller_cls is not None, "Controller class not found"

    seen = set()
    duplicates = set()
    for node in controller_cls.body:
        if isinstance(node, ast.FunctionDef):
            if node.name in seen:
                duplicates.add(node.name)
            seen.add(node.name)

    assert duplicates == set(), f"Duplicate methods found: {sorted(duplicates)}"
