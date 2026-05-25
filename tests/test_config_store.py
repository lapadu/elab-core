"""Tests for elab_server.config_store.ConfigStore."""
import os
import tempfile
import pytest

from elab_server.config_store import ConfigStore


@pytest.fixture
def store(tmp_path):
    """Create a ConfigStore backed by a temp directory."""
    db_path = os.path.join(str(tmp_path), "test_config.sqlite")
    s = ConfigStore(db_path=db_path)
    yield s
    s.close()


class TestConfigStore:
    """Tests for the persistent configuration store."""

    def test_get_empty(self, store):
        """Getting config for unknown task returns empty dict."""
        assert store.get_task_config("nonexistent") == {}

    def test_set_and_get_alias(self, store):
        """Setting an alias persists and can be retrieved."""
        store.set_task_alias("task-1", "Temp Fenster")
        config = store.get_task_config("task-1")
        assert config["alias"] == "Temp Fenster"

    def test_set_and_get_color(self, store):
        """Setting a color persists and can be retrieved."""
        store.set_task_color("task-1", "#ef4444")
        config = store.get_task_config("task-1")
        assert config["color"] == "#ef4444"

    def test_set_alias_and_color(self, store):
        """Both alias and color can be stored for the same task."""
        store.set_task_alias("task-1", "My Sensor")
        store.set_task_color("task-1", "#22c55e")
        config = store.get_task_config("task-1")
        assert config["alias"] == "My Sensor"
        assert config["color"] == "#22c55e"

    def test_clear_alias(self, store):
        """Setting alias to None clears it."""
        store.set_task_alias("task-1", "Test")
        store.set_task_alias("task-1", None)
        config = store.get_task_config("task-1")
        assert "alias" not in config

    def test_clear_color(self, store):
        """Setting color to None clears it."""
        store.set_task_color("task-1", "#ff0000")
        store.set_task_color("task-1", None)
        config = store.get_task_config("task-1")
        assert "color" not in config

    def test_get_all_configs(self, store):
        """get_all_configs returns all stored entries."""
        store.set_task_alias("task-1", "Alias A")
        store.set_task_color("task-2", "#abcdef")
        all_configs = store.get_all_configs()
        assert "task-1" in all_configs
        assert all_configs["task-1"]["alias"] == "Alias A"
        assert "task-2" in all_configs
        assert all_configs["task-2"]["color"] == "#abcdef"

    def test_overwrite_alias(self, store):
        """Overwriting an alias replaces the old value."""
        store.set_task_alias("task-1", "Old")
        store.set_task_alias("task-1", "New")
        config = store.get_task_config("task-1")
        assert config["alias"] == "New"

    def test_overwrite_color(self, store):
        """Overwriting a color replaces the old value."""
        store.set_task_color("task-1", "#111111")
        store.set_task_color("task-1", "#222222")
        config = store.get_task_config("task-1")
        assert config["color"] == "#222222"

    def test_persistence_across_reopen(self, tmp_path):
        """Data survives closing and reopening the store."""
        db_path = os.path.join(str(tmp_path), "persist_test.sqlite")
        s1 = ConfigStore(db_path=db_path)
        s1.set_task_alias("task-1", "Persistent")
        s1.set_task_color("task-1", "#aabbcc")
        s1.close()

        s2 = ConfigStore(db_path=db_path)
        config = s2.get_task_config("task-1")
        assert config["alias"] == "Persistent"
        assert config["color"] == "#aabbcc"
        s2.close()
