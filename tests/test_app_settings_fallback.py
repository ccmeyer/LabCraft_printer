import json

from App import load_settings


def test_load_settings_returns_defaults_when_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.json"

    settings = load_settings(str(missing))

    assert settings == {"HARDWARE_PROFILE": "current"}


def test_load_settings_returns_defaults_when_json_invalid(tmp_path):
    bad = tmp_path / "Settings.json"
    bad.write_text("{ not valid json", encoding="utf-8")

    settings = load_settings(str(bad))

    assert settings == {"HARDWARE_PROFILE": "current"}


def test_load_settings_reads_valid_json(tmp_path):
    path = tmp_path / "Settings.json"
    path.write_text(json.dumps({"HARDWARE_PROFILE": "legacy", "foo": 1}), encoding="utf-8")

    settings = load_settings(str(path))

    assert settings["HARDWARE_PROFILE"] == "legacy"
    assert settings["foo"] == 1
