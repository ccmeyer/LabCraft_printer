import hashlib
import json
from pathlib import Path

import pytest

from tools import historical_fixtures as fixtures


def test_manifest_is_bounded_and_has_all_replay_groups():
    groups = fixtures.load_manifest()
    assert set(groups) == {"dense_stream", "htps_tail", "focus"}
    assert sum(map(len, groups.values())) == 175


@pytest.mark.parametrize("relative", ["../escape", "/absolute", "C:/private", "a\\b", "a/../b"])
def test_manifest_rejects_escaping_entries(tmp_path, relative):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "groups": {"test": {relative: "a" * 64}}}))
    with pytest.raises(ValueError, match="Invalid historical fixture entry"):
        fixtures.load_manifest(path)


def test_verified_files_preserve_input_and_reject_missing_or_changed_bytes(tmp_path):
    path = tmp_path / "input.csv"
    path.write_bytes(b"original")
    entries = {"input.csv": hashlib.sha256(b"original").hexdigest()}
    assert fixtures.verified_files(tmp_path, entries) == [path]
    assert path.read_bytes() == b"original"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        fixtures.verified_files(tmp_path, entries)
    path.unlink()
    with pytest.raises(ValueError, match="Missing historical fixture"):
        fixtures.verified_files(tmp_path, entries)


def test_external_root_rejects_every_worktree_including_spaces(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second tree"
    monkeypatch.setattr(fixtures.subprocess, "check_output", lambda *a, **k:
                        f"worktree {first}\0HEAD a\0\0worktree {second}\0HEAD b\0\0".encode())
    for root in (first, second / "ignored/data"):
        with pytest.raises(ValueError, match="outside every"):
            fixtures.external_root(root)
    assert fixtures.external_root(tmp_path / "external") == tmp_path / "external"


def test_stage_copies_only_manifest_inputs_and_refuses_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "input").write_bytes(b"data")
    (source / "private").write_bytes(b"do not copy")
    entries = {"input": hashlib.sha256(b"data").hexdigest()}
    monkeypatch.setattr(fixtures, "load_manifest", lambda: {"group": entries})
    monkeypatch.setattr(fixtures, "external_root", lambda p: p)
    destination = tmp_path / "external"
    assert fixtures.stage(source, destination) == 1
    assert list(destination.iterdir()) == [destination / "input"]
    with pytest.raises(FileExistsError):
        fixtures.stage(source, destination)
    assert (source / "private").read_bytes() == b"do not copy"


def test_stage_validates_before_creating_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(fixtures, "load_manifest", lambda: {"group": {"missing": "a" * 64}})
    monkeypatch.setattr(fixtures, "external_root", lambda p: p)
    with pytest.raises(ValueError, match="Missing"):
        fixtures.stage(source, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()
