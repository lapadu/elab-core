"""Tests for the client-side device identity resolution.

Two units running identical firmware must end up with different device ids,
and an id must survive a restart so the operator only approves a device once.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import the shared client helper directly via path injection so we don't need
# the elab_clients_core package on sys.path.
_SHARED = Path(__file__).resolve().parent.parent / "elab_clients_core" / "python" / "shared"
sys.path.insert(0, str(_SHARED))

import identity as client_identity  # noqa: E402

from elab_server.auth import DEVICE_ANCHORS as SERVER_ANCHORS  # noqa: E402
from elab_server.manifest_builder import ManifestBuilder  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_identity_dir(tmp_path, monkeypatch):
    """Keep every test out of the real ~/.elab/identity directory."""
    monkeypatch.setenv("ELAB_CLIENT_IDENTITY_DIR", str(tmp_path / "identity"))


class TestAnchoredIdentity:
    """Hardware-anchored ids need no storage and never collide."""

    def test_two_boards_same_model_differ(self):
        a = client_identity.resolve_device_identity(
            "esp32_voltmeter", anchor_value="aabbccddeeff", anchor="efuse_mac"
        )
        b = client_identity.resolve_device_identity(
            "esp32_voltmeter", anchor_value="112233445566", anchor="efuse_mac"
        )
        assert a.device_id != b.device_id
        assert a.model == b.model == "esp32_voltmeter"
        assert a.anchor == "efuse_mac"

    def test_anchored_id_is_stable_without_storage(self, tmp_path, monkeypatch):
        """No file is written, so an unwritable home directory is harmless."""
        monkeypatch.setenv("ELAB_CLIENT_IDENTITY_DIR", str(tmp_path / "nope"))
        first = client_identity.resolve_device_identity(
            "owon_xdm1041", anchor_value="SN12345", anchor="serial"
        )
        second = client_identity.resolve_device_identity(
            "owon_xdm1041", anchor_value="SN12345", anchor="serial"
        )
        assert first.device_id == second.device_id
        assert not (tmp_path / "nope").exists()

    def test_anchor_value_requires_hardware_anchor(self):
        with pytest.raises(ValueError, match="not a hardware anchor"):
            client_identity.resolve_device_identity(
                "m", anchor_value="abc", anchor="assigned"
            )

    def test_unsafe_characters_are_sanitized(self):
        ident = client_identity.resolve_device_identity(
            "govee_thermo_hygro", anchor_value="A4:C1:38:11:22:33", anchor="ble_mac"
        )
        assert ":" not in ident.device_id
        assert ident.device_id.startswith("govee_thermo_hygro_A4_C1_38_11_22_33_")

    def test_sanitized_anchor_collisions_remain_distinct(self):
        first = client_identity.resolve_device_identity(
            "instrument", anchor_value="A/B", anchor="serial"
        )
        second = client_identity.resolve_device_identity(
            "instrument", anchor_value="A_B", anchor="serial"
        )
        assert first.device_id != second.device_id

    def test_anchors_match_the_server_enum(self):
        assert client_identity.DEVICE_ANCHORS == SERVER_ANCHORS


class TestAssignedIdentity:
    """Without a hardware anchor the id is generated once and persisted."""

    def test_id_survives_a_restart(self):
        first = client_identity.resolve_device_identity("smart_counter")
        second = client_identity.resolve_device_identity("smart_counter")
        assert first.device_id == second.device_id
        assert first.anchor == "assigned"

    def test_instances_get_separate_ids(self):
        a = client_identity.resolve_device_identity("hw_temp_sensor", instance="a")
        b = client_identity.resolve_device_identity("hw_temp_sensor", instance="b")
        assert a.device_id != b.device_id

    def test_unwritable_storage_falls_back_to_ephemeral(self, monkeypatch):
        def _fail(*_args, **_kwargs):
            return False

        monkeypatch.setattr(client_identity, "_save_assigned_id", _fail)
        ident = client_identity.resolve_device_identity("smart_counter")
        assert ident.anchor == "ephemeral"
        assert ident.is_stable is False


class TestIdComposition:
    """Ids derived from an identity must satisfy the manifest schema."""

    def test_scoped_ids_are_schema_valid(self):
        ident = client_identity.resolve_device_identity(
            "esp32_voltmeter", anchor_value="aabbccddeeff", anchor="efuse_mac"
        )
        builder = ManifestBuilder(
            ident.provider_id("adc"),
            "ESP32 ADC",
            device_id=ident.device_id,
            model=ident.model,
            device_anchor=ident.anchor,
        )
        builder.add_task(ident.task_id("ch1"), "CH1", "SENSOR", "generic")
        manifest = builder.build()
        assert manifest["device"]["id"] == ident.device_id
        assert manifest["tasks"][0]["id"].startswith(ident.device_id)

    def test_provider_id_without_suffix_is_the_device_id(self):
        ident = client_identity.resolve_device_identity(
            "m", anchor_value="x1", anchor="serial"
        )
        assert ident.provider_id() == ident.device_id
