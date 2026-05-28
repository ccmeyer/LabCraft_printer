import json

import pytest

import LocalConfig


def _configure_paths(monkeypatch, tmp_path):
    presets_dir = tmp_path / "FreeRTOS-interface" / "Presets"
    calibration_memory_dir = tmp_path / "FreeRTOS-interface" / "CalibrationMemory"
    local_dir = tmp_path / "local"
    presets_dir.mkdir(parents=True)
    calibration_memory_dir.mkdir(parents=True)
    local_dir.mkdir()
    monkeypatch.setattr(LocalConfig, "PRESETS_DIR", presets_dir)
    monkeypatch.setattr(LocalConfig, "CALIBRATION_MEMORY_TEMPLATE_DIR", calibration_memory_dir)
    monkeypatch.setattr(LocalConfig, "LOCAL_DIR", local_dir)
    return presets_dir, local_dir


def _write_calibration_memory_seed(root, *, marker="template"):
    (root / "entities").mkdir(parents=True, exist_ok=True)
    seed_text = {
        "schema.json": json.dumps({"schema_family": "labcraft.calibration_memory", "marker": marker}, indent=2),
        "config.json": json.dumps(
            {"schema_name": "labcraft.calibration_memory.runtime_config", "memory_enabled": True, "marker": marker},
            indent=2,
        ),
        "entities/reagents.json": json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.reagents_registry",
                "items": [{"reagent_id": marker, "display_name": marker}],
            },
            indent=2,
        ),
        "entities/printer_head_types.json": json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.printer_head_types_registry",
                "items": [{"head_type_id": marker, "display_name": marker}],
            },
            indent=2,
        ),
        "entities/printer_heads.json": json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.printer_heads_registry",
                "items": [{"printer_head_id": marker, "display_name": marker}],
            },
            indent=2,
        ),
    }
    for relative_path, text in seed_text.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


def test_get_machine_config_path_seeds_missing_local_from_current_preset(monkeypatch, tmp_path):
    presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    preset_text = '{\n  "HARDWARE_PROFILE": "legacy",\n  "machine": "bench-a"\n}\n'
    (presets_dir / "Settings.json").write_text(preset_text, encoding="utf-8")

    resolved = LocalConfig.get_machine_config_path("Settings.json")

    assert resolved == local_dir / "Settings.json"
    assert resolved.read_text(encoding="utf-8") == preset_text


def test_get_machine_config_path_prefers_existing_valid_local(monkeypatch, tmp_path):
    presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    (presets_dir / "Locations.json").write_text(
        json.dumps({"preset": {"X": 1, "Y": 2, "Z": 3}}),
        encoding="utf-8",
    )
    local_payload = {"local": {"X": 10, "Y": 20, "Z": 30}}
    local_path = local_dir / "Locations.json"
    local_path.write_text(json.dumps(local_payload, indent=2), encoding="utf-8")

    resolved = LocalConfig.get_machine_config_path("Locations.json")

    assert resolved == local_path
    assert json.loads(local_path.read_text(encoding="utf-8")) == local_payload


def test_get_machine_config_path_fails_fast_for_invalid_existing_local(monkeypatch, tmp_path):
    presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    (presets_dir / "Plates.json").write_text(
        json.dumps([{"name": "template"}]),
        encoding="utf-8",
    )
    local_path = local_dir / "Plates.json"
    local_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid machine config"):
        LocalConfig.get_machine_config_path("Plates.json")

    assert local_path.read_text(encoding="utf-8") == "{ not json"


def test_get_machine_config_path_rejects_wrong_top_level_type(monkeypatch, tmp_path):
    presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    (presets_dir / "Obstacles.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="expected top-level dict"):
        LocalConfig.get_machine_config_path("Obstacles.json")

    assert not (local_dir / "Obstacles.json").exists()


def test_get_calibration_memory_root_seeds_missing_local_files_from_templates(monkeypatch, tmp_path):
    _presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    template_dir = LocalConfig.CALIBRATION_MEMORY_TEMPLATE_DIR
    _write_calibration_memory_seed(template_dir, marker="template_marker")

    resolved = LocalConfig.get_calibration_memory_root()

    assert resolved == local_dir / "CalibrationMemory"
    for relative_path in LocalConfig._CALIBRATION_MEMORY_SEED_TYPES:
        assert (resolved / relative_path).read_text(encoding="utf-8") == (
            template_dir / relative_path
        ).read_text(encoding="utf-8")
    assert not (resolved / "indices").exists()
    assert not (resolved / "runs").exists()


def test_get_calibration_memory_root_preserves_existing_valid_local_seed(monkeypatch, tmp_path):
    _presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    template_dir = LocalConfig.CALIBRATION_MEMORY_TEMPLATE_DIR
    _write_calibration_memory_seed(template_dir, marker="template_marker")
    local_root = local_dir / "CalibrationMemory"
    _write_calibration_memory_seed(local_root, marker="local_marker")
    local_reagents_path = local_root / "entities" / "reagents.json"
    original_local_text = local_reagents_path.read_text(encoding="utf-8")

    resolved = LocalConfig.get_calibration_memory_root()

    assert resolved == local_root
    assert local_reagents_path.read_text(encoding="utf-8") == original_local_text


def test_get_calibration_memory_root_fails_fast_for_invalid_existing_local_seed(monkeypatch, tmp_path):
    _presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    _write_calibration_memory_seed(LocalConfig.CALIBRATION_MEMORY_TEMPLATE_DIR)
    local_root = local_dir / "CalibrationMemory"
    _write_calibration_memory_seed(local_root, marker="local_marker")
    local_config_path = local_root / "config.json"
    local_config_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid machine config"):
        LocalConfig.get_calibration_memory_root()

    assert local_config_path.read_text(encoding="utf-8") == "{ not json"


def test_get_calibration_memory_root_seeds_missing_files_in_partial_local_root(monkeypatch, tmp_path):
    _presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    template_dir = LocalConfig.CALIBRATION_MEMORY_TEMPLATE_DIR
    _write_calibration_memory_seed(template_dir, marker="template_marker")
    local_root = local_dir / "CalibrationMemory"
    local_root.mkdir()
    local_config_path = local_root / "config.json"
    local_config_path.write_text(
        json.dumps({"schema_name": "labcraft.calibration_memory.runtime_config", "marker": "local"}, indent=2),
        encoding="utf-8",
    )

    resolved = LocalConfig.get_calibration_memory_root()

    assert resolved == local_root
    assert json.loads(local_config_path.read_text(encoding="utf-8"))["marker"] == "local"
    assert (local_root / "schema.json").exists()
    assert (local_root / "entities" / "reagents.json").exists()
