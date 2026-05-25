"""Tests for elab_clients_core.python.shared.overrides."""

import json

from elab_clients_core.python.shared.overrides import (
    apply_task_meta_update,
    load_overrides,
    save_overrides,
)


def test_load_overrides_applies_color_name_and_config(tmp_path):
    """Overrides should update mutable fields on matching tasks."""
    manifest = {
        "tasks": [
            {"id": "t1", "color": "#111111", "name": "A", "config": {"gain": 1}},
            {"id": "t2", "color": "#222222", "name": "B", "config": {"gain": 2}},
        ]
    }
    overrides_file = tmp_path / "overrides.json"
    overrides_file.write_text(
        json.dumps(
            {
                "t1": {"color": "#ff0000", "name": "Renamed", "config": {"gain": 5}},
                "t2": {"config": {"gain": 7}},
            }
        ),
        encoding="utf-8",
    )

    load_overrides(manifest, str(overrides_file))

    assert manifest["tasks"][0]["color"] == "#ff0000"
    assert manifest["tasks"][0]["name"] == "Renamed"
    assert manifest["tasks"][0]["config"]["gain"] == 5
    assert manifest["tasks"][1]["config"]["gain"] == 7


def test_load_overrides_missing_or_invalid_file_is_noop(tmp_path):
    """Missing/invalid override files should not mutate manifest."""
    manifest = {"tasks": [{"id": "t1", "name": "A", "color": "#111", "config": {"x": 1}}]}

    # Missing file -> no-op
    load_overrides(manifest, str(tmp_path / "missing.json"))
    assert manifest["tasks"][0]["name"] == "A"

    # Invalid JSON -> no-op
    broken = tmp_path / "broken.json"
    broken.write_text("{ not-json", encoding="utf-8")
    load_overrides(manifest, str(broken))
    assert manifest["tasks"][0]["config"]["x"] == 1


def test_save_overrides_writes_expected_shape(tmp_path):
    """save_overrides should persist only user-editable fields."""
    manifest = {
        "tasks": [
            {"id": "t1", "color": "#abc", "name": "N1", "config": {"a": 1}, "type": "SENSOR"},
            {"id": "t2", "name": "N2"},
        ]
    }
    out = tmp_path / "saved.json"

    save_overrides(manifest, str(out))

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["t1"] == {"color": "#abc", "name": "N1", "config": {"a": 1}}
    assert payload["t2"] == {"color": None, "name": "N2", "config": {}}


def test_apply_task_meta_update_updates_matching_task_only():
    """apply_task_meta_update returns True only when a target task exists."""
    manifest = {
        "tasks": [
            {"id": "t1", "color": "#000", "name": "Old"},
            {"id": "t2", "color": "#111", "name": "Keep"},
        ]
    }

    ok = apply_task_meta_update(manifest, "t1", {"color": "#fff", "name": "New"})
    assert ok is True
    assert manifest["tasks"][0]["color"] == "#fff"
    assert manifest["tasks"][0]["name"] == "New"
    assert manifest["tasks"][1]["name"] == "Keep"

    missing = apply_task_meta_update(manifest, "nope", {"name": "X"})
    assert missing is False
