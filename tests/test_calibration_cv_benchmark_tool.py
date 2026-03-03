import importlib.util
import json
from pathlib import Path

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "calibration_cv_benchmark.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_cv_benchmark_tool_output_contract(tmp_path):
    mod = _load_module(TOOL_PATH, "calibration_cv_benchmark_tool_mod")
    payload = mod.run_benchmark(iterations=5, width=220, height=220, seed=11)

    assert payload["schema_version"] == 1
    assert payload["iterations"] == 5
    assert "generated_at" in payload
    assert payload["image_size"] == {"width": 220, "height": 220}

    timings = payload["timings_ms"]
    for key in ("identify_nozzle", "identify_droplet_contour", "characterize_droplet"):
        assert key in timings
        block = timings[key]
        assert block["count"] == 5
        assert block["mean"] is not None and block["mean"] >= 0.0
        assert block["p50"] is not None and block["p50"] >= 0.0
        assert block["p95"] is not None and block["p95"] >= 0.0

    out_path = tmp_path / "cv_benchmark.json"
    written = mod.write_json(out_path, payload)
    assert Path(written).exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1
    assert loaded["iterations"] == 5
