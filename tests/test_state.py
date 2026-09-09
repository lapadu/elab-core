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

    def test_set_task_decimals_forwarded_to_persist_capable_device(
        self, state_with_store, mock_socketio, config_store
    ):
        """Decimals follows the same device-authority rule as alias and color."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "device": {"id": "dev-1", "model": "m", "anchor": "efuse_mac",
                       "persistCapable": True},
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.set_task_decimals("task-1", 4)
        mock_socketio.emit.assert_any_call(
            'persist_config', {'task_id': 'task-1', 'decimals': 4}, room='sid-1'
        )
        assert config_store.get_task_config("task-1") == {}

    def test_stored_config_records_owning_device(self, state_with_store, config_store):
        """Dispatcher-held overrides remember which device they belong to."""
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "device": {"id": "dev-1", "model": "m", "anchor": "assigned",
                       "persistCapable": False},
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.set_task_alias("task-1", "Eingang Vorstufe")
        assert config_store.delete_device_config("dev-1") == 1
        assert config_store.get_task_config("task-1") == {}

    def test_apply_stored_config_skipped_for_persist_capable_device(
        self, state_with_store, config_store
    ):
        """A self-persisting device keeps the values it shipped in its manifest."""
        config_store.set_task_alias("task-1", "Stale Alias")
        manifest = {
            "id": "prov-1", "name": "Test", "category": "HARDWARE",
            "device": {"id": "dev-1", "model": "m", "anchor": "efuse_mac",
                       "persistCapable": True},
            "tasks": [{"id": "task-1", "name": "Sensor", "type": "SENSOR",
                       "alias": "Eingang Endstufe", "ui": {"mode": "generic"}}]
        }
        state_with_store.add_provider("sid-1", manifest)
        state_with_store.apply_stored_config(manifest)
        assert manifest["tasks"][0]["alias"] == "Eingang Endstufe"

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


class TestDeviceIdentity:
    """Two devices running identical firmware must stay distinguishable."""

    @pytest.fixture
    def config_store(self, tmp_path):
        """Create an isolated ConfigStore for device configuration tests."""
        store = ConfigStore(db_path=str(tmp_path / "device_config.sqlite"))
        yield store
        store.close()

    @pytest.fixture
    def state_with_store(self, mock_socketio, config_store):
        """Create state backed by the isolated ConfigStore."""
        return SystemState(mock_socketio, config_store=config_store)

    @staticmethod
    def _manifest(device_id, provider_suffix="adc", task_suffix="ch1"):
        return {
            "id": f"{device_id}_{provider_suffix}",
            "name": "ESP32 Voltmeter",
            "category": "HARDWARE",
            "device": {
                "id": device_id,
                "model": "esp32_voltmeter",
                "anchor": "efuse_mac",
                "persistCapable": True,
            },
            "tasks": [{
                "id": f"{device_id}_{task_suffix}",
                "name": "CH1",
                "type": "SENSOR",
                "ui": {"mode": "generic"},
            }],
        }

    def test_two_devices_same_firmware_coexist(self, state):
        """Distinct hardware anchors yield distinct, independently routable ids."""
        a = self._manifest("esp32_voltmeter_aabbccddeeff")
        b = self._manifest("esp32_voltmeter_112233445566")
        assert state.add_provider("sid-a", a)
        assert state.add_provider("sid-b", b)
        assert state.find_provider_sid("esp32_voltmeter_aabbccddeeff_ch1") == "sid-a"
        assert state.find_provider_sid("esp32_voltmeter_112233445566_ch1") == "sid-b"
        assert len(state.get_providers_list()) == 2

    def test_duplicate_ids_are_reported_not_renamed(self, state):
        """A colliding id must surface as a conflict instead of being suffixed."""
        state.add_provider("sid-a", self._manifest("esp32_voltmeter_01"))
        clash = self._manifest("esp32_voltmeter_01")
        conflicts = state.find_id_conflicts("sid-b", clash)
        assert conflicts == ["esp32_voltmeter_01_adc", "esp32_voltmeter_01_ch1"]
        assert state.add_provider("sid-b", clash) is False
        assert clash["id"] == "esp32_voltmeter_01_adc"
        assert clash["tasks"][0]["id"] == "esp32_voltmeter_01_ch1"

    def test_reregistration_is_not_a_conflict(self, state):
        """The same session refreshing its own manifest is not a duplicate."""
        manifest = self._manifest("esp32_voltmeter_01")
        state.add_provider("sid-a", manifest)
        assert state.find_id_conflicts("sid-a", manifest) == []

    def test_task_id_may_not_shadow_a_foreign_provider_id(self, state):
        """Ids are globally unique across both namespaces, not just within one."""
        state.add_provider("sid-a", self._manifest("dev-a"))
        other = self._manifest("dev-b")
        other["tasks"][0]["id"] = "dev-a_adc"
        assert state.add_provider("sid-b", other) is False
        assert state.find_provider_sid("dev-a_adc") == "sid-a"

    def test_duplicate_task_ids_within_one_manifest_refused(self, state):
        """A provider cannot declare the same task twice."""
        manifest = self._manifest("dev-a")
        manifest["tasks"].append(dict(manifest["tasks"][0]))
        assert state.add_provider("sid-a", manifest) is False

    def test_secret_resolves_via_device_for_every_task(self, state):
        """All providers of one device share a single pairing credential."""
        state.add_provider("sid-a", self._manifest("dev-a"))
        state.register_approved_secret("sid-a", "dev-a", "s3cr3t")
        assert state.get_secret_for_source("dev-a_ch1") == "s3cr3t"
        assert state.get_secret_for_source("dev-a_adc") == "s3cr3t"

    def test_legacy_manifest_without_device_block_still_pairs(self, state):
        """Manifests predating the device block fall back to the provider id."""
        state.add_provider("sid-1", VALID_MANIFEST.copy())
        state.register_approved_secret("sid-1", "prov-1", "legacy")
        assert state.get_secret_for_source("task-1") == "legacy"

    def test_forget_secret_stops_verification(self, state):
        """Revoking a device drops its cached secret immediately."""
        state.add_provider("sid-a", self._manifest("dev-a"))
        state.register_approved_secret("sid-a", "dev-a", "s3cr3t")
        state.forget_secret("dev-a")
        assert state.get_secret_for_source("dev-a_ch1") is None

    def test_find_sid_for_source_binds_stream_to_session(self, state):
        """data_stream can be checked against the session that registered it."""
        state.add_provider("sid-a", self._manifest("dev-a"))
        assert state.find_sid_for_source("dev-a_ch1") == "sid-a"
        assert state.find_sid_for_source("unknown") is None

    def test_device_name_is_cached_for_non_persistent_device(self, state_with_store, config_store):
        """The dispatcher stores names for devices without local persistence."""
        manifest = self._manifest("dev-a")
        manifest["device"]["persistCapable"] = False
        state_with_store.add_provider("sid-a", manifest)
        assert state_with_store.set_device_name("dev-a", "Eingang Vorstufe")
        assert config_store.get_device_config("dev-a")["name"] == "Eingang Vorstufe"

    def test_device_name_is_forwarded_for_persistent_device(self, state_with_store, mock_socketio):
        """Persistent devices receive the operator name instead of a DB copy."""
        state_with_store.add_provider("sid-a", self._manifest("dev-a"))
        assert state_with_store.set_device_name("dev-a", "Eingang Endstufe")
        mock_socketio.emit.assert_any_call(
            "persist_config", {"device_name": "Eingang Endstufe"}, room="sid-a"
        )

    def test_ephemeral_credential_is_not_written_to_database(self, state_with_store, config_store):
        """Ephemeral pairing stays in memory and disappears with its session."""
        state_with_store.set_ephemeral_credential("dev-e", "secret", "hash")
        assert state_with_store.get_ephemeral_credential("dev-e")["status"] == "pending"
        assert config_store.get_credential("dev-e") is None
        state_with_store.approve_ephemeral_credential("dev-e", "hash")
        state_with_store.register_approved_secret("sid-e", "dev-e", "secret")
        state_with_store.drop_session_auth("sid-e")
        assert state_with_store.get_ephemeral_credential("dev-e") is None
        assert state_with_store.get_secret_for_source("dev-e_ch1") is None
