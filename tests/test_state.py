"""Tests for elab_server.state.SystemState."""
import threading
import pytest
from unittest.mock import MagicMock, patch

from elab_server.state import SystemState
from elab_server.config_store import ConfigStore


@pytest.fixture
def mock_socketio():
    """Mock socketio object."""
    sio = MagicMock()
    sio.emit = MagicMock()
    return sio


@pytest.fixture
def state(mock_socketio):
    """Fresh SystemState for each test."""
    return SystemState(mock_socketio)


VALID_MANIFEST = {
    "id": "prov-1",
    "name": "TestProvider",
    "category": "HARDWARE",
    "version": "1.0.0",
    "capabilities": ["stream"],
    "tasks": [
        {
            "id": "task-1",
            "name": "Sensor A",
            "type": "SENSOR",
            "ui": {"mode": "generic"},
        }
    ],
}


class TestSystemState:
    """Tests for SystemState provider management."""

    def test_add_provider(self, state):
        """add_provider should register a provider and index it."""
        ok = state.add_provider("sid-1", VALID_MANIFEST.copy())
        assert ok
        providers = state.get_providers_list()
        assert len(providers) == 1
        assert providers[0]["id"] == "prov-1"

    def test_add_provider_indexes_task_id(self, state):
        """Provider tasks should be indexed for O(1) lookup."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        sid = state.find_provider_sid("task-1")
        assert sid == "sid-1"

    def test_add_provider_indexes_provider_id(self, state):
        """Provider id itself should be indexed."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        sid = state.find_provider_sid("prov-1")
        assert sid == "sid-1"

    def test_remove_provider(self, state, mock_socketio):
        """remove_provider should clean up all state and emit disconnect."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        state.remove_provider("sid-1")
        assert state.get_providers_list() == []
        assert state.find_provider_sid("prov-1") is None
        assert state.find_provider_sid("task-1") is None
        mock_socketio.emit.assert_called()

    def test_add_provider_replaces_existing_same_id(self, state):
        """Re-registering same provider id replaces the old one cleanly."""
        m1 = VALID_MANIFEST.copy()
        m1["name"] = "V1"
        state.add_provider("sid-1", m1)

        m2 = VALID_MANIFEST.copy()
        m2["name"] = "V2"
        state.add_provider("sid-1", m2)

        providers = state.get_providers_list()
        assert len(providers) == 1
        assert providers[0]["name"] == "V2"

    def test_add_provider_invalid_manifest_rejected(self, state):
        """Non-dict manifests should be rejected."""
        ok = state.add_provider("sid-1", "not a dict")
        assert not ok
        assert state.get_providers_list() == []

    def test_find_provider_sid_returns_none_for_unknown(self, state):
        """Unknown IDs return None."""
        assert state.find_provider_sid("nonexistent") is None
        assert state.find_provider_sid("") is None
        assert state.find_provider_sid(None) is None

    def test_get_provider_manifest(self, state):
        """get_provider_manifest should find manifest by provider or task id."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        # By provider id
        m = state.get_provider_manifest("prov-1")
        assert m is not None
        assert m["id"] == "prov-1"
        # By task id
        m2 = state.get_provider_manifest("task-1")
        assert m2 is not None
        assert m2["id"] == "prov-1"
        # Unknown
        assert state.get_provider_manifest("unknown") is None

    def test_update_task_meta(self, state):
        """update_task_meta should update color, name, config in place."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        result = state.update_task_meta("task-1", {
            "color": "#FF0000",
            "name": "Renamed",
            "config": {"unit": "V"},
        })
        assert result is True
        m = state.get_provider_manifest("prov-1")
        task = m["tasks"][0]
        assert task["color"] == "#FF0000"
        assert task["name"] == "Renamed"
        assert task["config"]["unit"] == "V"

    def test_update_task_meta_unknown_task(self, state):
        """update_task_meta with unknown task returns False."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        result = state.update_task_meta("nonexistent", {"color": "#000"})
        assert result is False

    def test_atomic_update_context_manager(self, state):
        """atomic_update context manager provides thread-safe access."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        with state.atomic_update() as s:
            assert len(s.providers) == 1

    def test_active_tasks_by_slot(self, state):
        """active_tasks_by_slot can be set and read."""
        state.active_tasks_by_slot[0] = "task-1"
        state.active_tasks_by_slot[1] = "task-2"
        assert state.active_tasks_by_slot[0] == "task-1"
        assert state.active_tasks_by_slot[1] == "task-2"

    def test_multiple_providers_different_sids(self, state):
        """Multiple providers from different sessions coexist."""
        m1 = VALID_MANIFEST.copy()
        m1["id"] = "prov-A"
        m1["tasks"] = [{"id": "t-A", "name": "A", "type": "SENSOR", "ui": {"mode": "generic"}}]

        m2 = VALID_MANIFEST.copy()
        m2["id"] = "prov-B"
        m2["tasks"] = [{"id": "t-B", "name": "B", "type": "SENSOR", "ui": {"mode": "generic"}}]

        state.add_provider("sid-1", m1)
        state.add_provider("sid-2", m2)

        assert len(state.get_providers_list()) == 2
        assert state.find_provider_sid("t-A") == "sid-1"
        assert state.find_provider_sid("t-B") == "sid-2"

    def test_thread_safety(self, state):
        """Concurrent add/remove operations should not corrupt state."""
        import random

        errors = []

        def worker(i):
            try:
                m = VALID_MANIFEST.copy()
                m["id"] = f"prov-{i}"
                m["tasks"] = [{"id": f"task-{i}", "name": f"T{i}", "type": "SENSOR", "ui": {"mode": "generic"}}]
                state.add_provider(f"sid-{i}", m)
                # small delay
                state.find_provider_sid(f"prov-{i}")
                state.get_providers_list()
                state.remove_provider(f"sid-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert state.get_providers_list() == []


class TestTaskConfigPersistence:
    """Tests for alias, color persistence and persistConfig behavior."""

    @pytest.fixture
    def config_store(self, tmp_path):
        """Create a ConfigStore backed by a temp directory."""
        import os
        db_path = os.path.join(str(tmp_path), "test_config.sqlite")
        s = ConfigStore(db_path=db_path)
        yield s
        s.close()

    @pytest.fixture
    def state_with_store(self, mock_socketio, config_store):
        """SystemState with a real config store."""
        return SystemState(mock_socketio, config_store=config_store)

    def test_set_task_alias_stored_in_db(self, state_with_store, config_store):
        """Alias is stored in ConfigStore when provider does not self-persist."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": False,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        result = state_with_store.set_task_alias("task-1", "Temp Fenster")
        assert result is True
        # Verify stored in DB
        assert config_store.get_task_config("task-1")["alias"] == "Temp Fenster"

    def test_set_task_alias_forwarded_to_provider(self, state_with_store, mock_socketio):
        """Alias is forwarded to provider when persistConfig is True."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": True,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.set_task_alias("task-1", "My Alias")
        # Should have emitted persist_config to the provider
        mock_socketio.emit.assert_any_call('persist_config', {
            'task_id': 'task-1',
            'alias': 'My Alias'
        }, room='sid-1')

    def test_set_task_color_stored_in_db(self, state_with_store, config_store):
        """Color is stored in ConfigStore when provider does not self-persist."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": False,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        result = state_with_store.set_task_color("task-1", "#22c55e")
        assert result is True
        assert config_store.get_task_config("task-1")["color"] == "#22c55e"

    def test_set_task_color_forwarded_to_provider(self, state_with_store, mock_socketio):
        """Color is forwarded to provider when persistConfig is True."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": True,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.set_task_color("task-1", "#ef4444")
        mock_socketio.emit.assert_any_call('persist_config', {
            'task_id': 'task-1',
            'color': '#ef4444'
        }, room='sid-1')

    def test_set_task_decimals_stored_in_db(self, state_with_store, config_store):
        """Decimals is stored in ConfigStore when provider does not self-persist."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": False,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        result = state_with_store.set_task_decimals("task-1", 4)
        assert result is True
        assert config_store.get_task_config("task-1")["decimals"] == 4

    def test_apply_stored_config_on_registration(self, state_with_store, config_store):
        """Stored alias/color/decimals is applied to manifest on registration."""
        config_store.set_task_alias("task-1", "Stored Alias")
        config_store.set_task_color("task-1", "#abcdef")
        config_store.set_task_decimals("task-1", 3)

        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": False,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.apply_stored_config(manifest)

        task = manifest["tasks"][0]
        assert task["alias"] == "Stored Alias"
        assert task["color"] == "#abcdef"
        assert task["decimals"] == 3

    def test_apply_stored_config_skipped_for_self_persist(self, state_with_store, config_store):
        """Stored config is NOT applied when provider self-persists."""
        config_store.set_task_alias("task-1", "Should Not Apply")
        config_store.set_task_color("task-1", "#000000")

        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "persistConfig": True,
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "color": "#ffffff", "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.apply_stored_config(manifest)

        task = manifest["tasks"][0]
        assert "alias" not in task
        assert task["color"] == "#ffffff"

    def test_set_alias_unknown_task(self, state_with_store):
        """Setting alias for unknown task returns False."""
        assert state_with_store.set_task_alias("nonexistent", "X") is False

    def test_set_color_unknown_task(self, state_with_store):
        """Setting color for unknown task returns False."""
        assert state_with_store.set_task_color("nonexistent", "#000") is False

    def test_provider_persists_check(self, state_with_store):
        """_provider_persists returns correct value based on manifest."""
        m1 = {
            "id": "prov-1", "name": "A", "category": "HARDWARE",
            "persistConfig": True,
            "tasks": [{"id": "t1", "name": "T", "type": "SENSOR", "ui": {"mode": "generic"}}]
        }
        m2 = {
            "id": "prov-2", "name": "B", "category": "HARDWARE",
            "persistConfig": False,
            "tasks": [{"id": "t2", "name": "T", "type": "SENSOR", "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", m1)
        state_with_store.add_provider("sid-2", m2)
        assert state_with_store._provider_persists("t1") is True
        assert state_with_store._provider_persists("t2") is False
        assert state_with_store._provider_persists("unknown") is False
