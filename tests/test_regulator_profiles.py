import copy
import json
from pathlib import Path

import pytest

import LocalConfig
import RegulatorProfiles as rp
from Model import Model


def _configure_paths(monkeypatch, tmp_path):
    presets_dir = tmp_path / "FreeRTOS-interface" / "Presets"
    local_dir = tmp_path / "local"
    presets_dir.mkdir(parents=True)
    local_dir.mkdir()
    monkeypatch.setattr(LocalConfig, "PRESETS_DIR", presets_dir)
    monkeypatch.setattr(LocalConfig, "LOCAL_DIR", local_dir)
    return presets_dir, local_dir


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _factory_doc():
    return rp.factory_default_document()


def test_factory_default_document_validates():
    document = _factory_doc()

    validated = rp.validate_document(document)

    assert validated == document
    assert validated is not document


def test_tracked_preset_validates():
    path = Path("FreeRTOS-interface/Presets/RegulatorProfiles.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert rp.validate_document(payload) == payload


def test_explicit_missing_store_path_loads_factory_defaults(tmp_path):
    path = tmp_path / "missing" / "RegulatorProfiles.json"
    store = rp.RegulatorProfileStore(path=path)

    document = store.load()

    assert document == _factory_doc()
    assert not path.exists()


def test_local_config_seeds_local_regulator_profiles(monkeypatch, tmp_path):
    presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    preset = _factory_doc()
    _write_json(presets_dir / "RegulatorProfiles.json", preset)

    store = rp.RegulatorProfileStore()
    document = store.load()

    local_path = local_dir / "RegulatorProfiles.json"
    assert store.path == local_path
    assert local_path.exists()
    assert document == preset
    assert json.loads(local_path.read_text(encoding="utf-8")) == preset


def test_unknown_metadata_fields_are_preserved_after_load_and_save(tmp_path):
    document = _factory_doc()
    document["unknown_top"] = {"kept": True}
    document["profiles"]["stream_default"]["unknown_profile"] = "keep me"
    document["profiles"]["stream_default"]["source"]["unknown_source"] = 123
    document["profiles"]["stream_default"]["print"]["unknown_channel"] = {"x": 1}
    path = tmp_path / "RegulatorProfiles.json"
    _write_json(path, document)

    store = rp.RegulatorProfileStore(path=path)
    loaded = store.load()
    saved = store.save(loaded)

    assert saved["unknown_top"] == {"kept": True}
    assert saved["profiles"]["stream_default"]["unknown_profile"] == "keep me"
    assert saved["profiles"]["stream_default"]["source"]["unknown_source"] == 123
    assert saved["profiles"]["stream_default"]["print"]["unknown_channel"] == {"x": 1}
    assert json.loads(path.read_text(encoding="utf-8")) == saved


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda doc: doc.update(schema_version=2), "schema_version"),
        (lambda doc: doc.pop("active_profiles"), "active_profiles"),
        (lambda doc: doc["active_profiles"].pop("droplet"), "droplet"),
        (lambda doc: doc["active_profiles"].update(droplet="missing"), "does not exist"),
        (lambda doc: doc["active_profiles"].update(droplet="stream_default"), "does not match"),
        (lambda doc: doc["profiles"]["stream_default"].update(mode="other"), "mode"),
        (lambda doc: doc["profiles"]["stream_default"].pop("source"), "source"),
        (lambda doc: doc["profiles"]["stream_default"]["print"].pop("ready"), "ready"),
        (
            lambda doc: doc["profiles"]["stream_default"]["print"]["recovery"].update(active_ticks=21),
            "active_ticks out of range",
        ),
        (
            lambda doc: doc["profiles"]["stream_default"]["print"]["recovery"].update(active_ticks=True),
            "active_ticks must be an integer",
        ),
        (
            lambda doc: doc["profiles"]["stream_default"]["print"]["recovery"].update(active_ticks="2"),
            "active_ticks must be an integer",
        ),
        (
            lambda doc: doc["profiles"]["stream_default"]["print"]["recovery"].update(linear_decay=1),
            "linear_decay must be a boolean",
        ),
        (
            lambda doc: doc["profiles"]["stream_default"]["conditions"].update(frequency_hz=True),
            "frequency_hz must be numeric",
        ),
    ],
)
def test_invalid_profile_documents_fail_closed(mutate, match):
    document = _factory_doc()
    mutate(document)

    with pytest.raises(rp.RegulatorProfileError, match=match):
        rp.validate_document(document)


def test_atomic_save_preserves_previous_file_on_replace_failure(tmp_path, monkeypatch):
    target = tmp_path / "RegulatorProfiles.json"
    baseline = _factory_doc()
    _write_json(target, baseline)
    store = rp.RegulatorProfileStore(path=target)
    store.load()

    updated = _factory_doc()
    updated["profiles"]["stream_default"]["description"] = "Changed"

    def _boom(*_args, **_kwargs):
        raise RuntimeError("replace failed")

    monkeypatch.setattr(rp.os, "replace", _boom)

    with pytest.raises(RuntimeError, match="replace failed"):
        store.save(updated)

    assert json.loads(target.read_text(encoding="utf-8")) == baseline


def test_upsert_set_active_and_get_active_profile_are_deterministic(tmp_path):
    store = rp.RegulatorProfileStore(path=tmp_path / "RegulatorProfiles.json")
    document = store.load()
    candidate = copy.deepcopy(document["profiles"]["stream_default"])
    candidate["profile_id"] = "stream_candidate_001"
    candidate["description"] = "Candidate"

    saved_profile = store.upsert_profile(candidate, make_active=True)
    active = store.get_active_profile("stream")

    assert saved_profile["profile_id"] == "stream_candidate_001"
    assert active["profile_id"] == "stream_candidate_001"

    store.set_active_profile("stream", None)
    assert store.get_active_profile("stream") is None

    with pytest.raises(rp.RegulatorProfileError, match="mode does not match"):
        store.set_active_profile("droplet", "stream_candidate_001")


def test_model_initializes_regulator_profile_store(monkeypatch, tmp_path):
    presets_dir, _local_dir = _configure_paths(monkeypatch, tmp_path)
    _write_json(presets_dir / "RegulatorProfiles.json", _factory_doc())
    model = Model.__new__(Model)

    Model._initialize_regulator_profile_store(model)

    assert model.regulator_profiles_error is None
    assert model.regulator_profiles["schema_version"] == 1
    assert model.regulator_profiles_path.endswith("RegulatorProfiles.json")
    assert model.regulator_profile_store.document == model.regulator_profiles


def test_model_falls_back_to_defaults_without_overwriting_invalid_local(monkeypatch, tmp_path):
    presets_dir, local_dir = _configure_paths(monkeypatch, tmp_path)
    _write_json(presets_dir / "RegulatorProfiles.json", _factory_doc())
    local_path = local_dir / "RegulatorProfiles.json"
    local_path.write_text("{ not json", encoding="utf-8")
    model = Model.__new__(Model)

    Model._initialize_regulator_profile_store(model)

    assert model.regulator_profiles == _factory_doc()
    assert model.regulator_profiles_error
    assert local_path.read_text(encoding="utf-8") == "{ not json"
