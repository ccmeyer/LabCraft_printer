import json

import pytest

import LocalConfig


def _configure_paths(monkeypatch, tmp_path):
    presets_dir = tmp_path / "FreeRTOS-interface" / "Presets"
    local_dir = tmp_path / "local"
    presets_dir.mkdir(parents=True)
    local_dir.mkdir()
    monkeypatch.setattr(LocalConfig, "PRESETS_DIR", presets_dir)
    monkeypatch.setattr(LocalConfig, "LOCAL_DIR", local_dir)
    return presets_dir, local_dir


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
