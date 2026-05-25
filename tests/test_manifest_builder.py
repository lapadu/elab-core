"""Tests for elab_server.manifest_builder.ManifestBuilder."""
import pytest

from elab_server.manifest_builder import ManifestBuilder


@pytest.fixture
def builder():
    """A minimal ManifestBuilder instance."""
    return ManifestBuilder("test-prov", "Test Provider")


class TestManifestBuilder:
    """Tests for the manifest builder."""

    def test_build_minimal_manifest(self, builder):
        """A builder with one task should produce a valid manifest."""
        builder.add_task("t1", "S", "SENSOR", "generic")
        m = builder.build()
        assert m["id"] == "test-prov"
        assert m["name"] == "Test Provider"
        assert len(m["tasks"]) == 1
        assert m["providerVersion"] == "1.0.0"
        assert m["apiVersion"] == "2.0.0"

    def test_add_sensor_task(self, builder):
        """add_task for SENSOR should produce valid task entry."""
        builder.add_task("t1", "Sensor 1", "SENSOR", "generic", group_id="scope")
        m = builder.build()
        assert len(m["tasks"]) == 1
        task = m["tasks"][0]
        assert task["id"] == "t1"
        assert task["name"] == "Sensor 1"
        assert task["type"] == "SENSOR"
        assert task["ui"]["mode"] == "generic"
        assert task["groupId"] == "scope"

    def test_add_actuator_task(self, builder):
        """add_task for ACTUATOR should work."""
        builder.add_task("a1", "LED", "ACTUATOR", "generic")
        m = builder.build()
        assert m["tasks"][0]["type"] == "ACTUATOR"

    def test_add_task_with_decoder(self, builder):
        """add_task with a valid decoder config should pass validation."""
        builder.add_task(
            "t1", "BinSensor", "SENSOR", "generic",
            decoder={"type": "generic_binary", "parameters": {"dataType": "uint16"}}
        )
        m = builder.build()
        assert m["tasks"][0]["decoder"]["type"] == "generic_binary"

    def test_add_task_with_invalid_decoder_type_raises(self, builder):
        """Unknown decoder type should raise ValueError at build time."""
        with pytest.raises(ValueError, match="Unknown decoder type"):
            builder.add_task(
                "t1", "Bad", "SENSOR", "generic",
                decoder={"type": "nonexistent_decoder", "parameters": {}}
            )

    def test_add_task_with_config(self, builder):
        """config dict should be passed through."""
        builder.add_task("t1", "S", "SENSOR", "generic", config={"unit": "V", "timeWindow": 5})
        m = builder.build()
        assert m["tasks"][0]["config"]["unit"] == "V"

    def test_add_task_with_color(self, builder):
        """color should be included in task."""
        builder.add_task("t1", "S", "SENSOR", "generic", color="#FF0000")
        m = builder.build()
        assert m["tasks"][0]["color"] == "#FF0000"

    def test_add_task_virtual(self, builder):
        """virtual flag should be set."""
        builder.add_task("t1", "Sim", "MATH", "generic", virtual=True)
        m = builder.build()
        assert m["tasks"][0]["virtual"] is True

    def test_add_task_with_actions(self, builder):
        """actions list should be passed through."""
        actions = [{"id": "START", "label": "Start"}]
        builder.add_task("t1", "S", "SENSOR", "generic", actions=actions)
        m = builder.build()
        assert m["tasks"][0]["actions"] == actions

    def test_add_task_with_group(self, builder):
        """group field should be included."""
        builder.add_task("t1", "S", "SENSOR", "generic", group="analog")
        m = builder.build()
        assert m["tasks"][0]["group"] == "analog"

    def test_fluent_chaining(self, builder):
        """add_task returns self for fluent chaining."""
        result = builder.add_task("t1", "A", "SENSOR", "generic")
        assert result is builder

    def test_multiple_tasks(self, builder):
        """Multiple tasks can be added."""
        builder.add_task("t1", "S1", "SENSOR", "generic")
        builder.add_task("t2", "S2", "SENSOR", "generic")
        builder.add_task("a1", "Act", "ACTUATOR", "generic")
        m = builder.build()
        assert len(m["tasks"]) == 3

    def test_category_defaults_to_hardware(self):
        """Default category is HARDWARE."""
        b = ManifestBuilder("p", "P")
        b.add_task("t1", "S", "SENSOR", "generic")
        m = b.build()
        assert m["category"] == "HARDWARE"

    def test_custom_category(self):
        """Category can be overridden."""
        b = ManifestBuilder("p", "P", category="VIRTUAL_SCRIPT")
        b.add_task("t1", "S", "SENSOR", "generic")
        m = b.build()
        assert m["category"] == "VIRTUAL_SCRIPT"

    def test_decoder_non_dict_raises(self, builder):
        """Non-dict decoder should raise ValueError."""
        with pytest.raises(ValueError, match="must be a dict"):
            builder.add_task("t1", "S", "SENSOR", "generic", decoder="bad")

    def test_decoder_missing_type_raises(self, builder):
        """Decoder without 'type' key should raise ValueError."""
        with pytest.raises(ValueError, match="missing 'type'"):
            builder.add_task("t1", "S", "SENSOR", "generic", decoder={"parameters": {}})
