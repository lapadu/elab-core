"""Tests for the TOFU pairing + HMAC signing implementation.

Covers:
* manifest canonicalization (volatile-field stripping, deterministic bytes)
* HMAC sign/verify round-trip, replay-window enforcement, tampering detection
* auto-approve token lifecycle (issued once, consumed atomically, single-use)
* :class:`SystemState` pending/approved book-keeping incl. bridge multiplexing
* :class:`ConfigStore` credential CRUD + manifest_hash binding
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from elab_server.auth import (
    MAX_TIMESTAMP_SKEW_SEC,
    canonicalize_manifest,
    compute_manifest_hash,
    generate_secret,
    is_auth_required,
    make_auto_approve_token,
    sign_payload,
    verify_payload,
)
from elab_server.config_store import ConfigStore
from elab_server.state import SystemState


MANIFEST = {
    "id": "dev-1",
    "name": "Test Sensor",
    "category": "HARDWARE",
    "version": "1.0",
    "capabilities": ["measure"],
    "tasks": [
        {
            "id": "dev-1-ch1",
            "name": "CH1",
            "type": "SENSOR",
            "ui": {"mode": "generic"},
        }
    ],
}


# --- Canonicalization & hashing --------------------------------------------

class TestCanonicalization:
    def test_strips_volatile_fields(self):
        with_volatile = dict(MANIFEST)
        with_volatile["sid"] = "abc"
        with_volatile["client_ip"] = "10.0.0.1"
        with_volatile["isUiInstance"] = False
        with_volatile["connected_at"] = 123.456
        assert canonicalize_manifest(with_volatile) == canonicalize_manifest(MANIFEST)

    def test_deterministic_across_key_order(self):
        a = {"id": "x", "name": "A", "tasks": []}
        b = {"tasks": [], "name": "A", "id": "x"}
        assert canonicalize_manifest(a) == canonicalize_manifest(b)
        assert compute_manifest_hash(a) == compute_manifest_hash(b)

    def test_change_in_task_changes_hash(self):
        h1 = compute_manifest_hash(MANIFEST)
        modified = {**MANIFEST, "tasks": [{**MANIFEST["tasks"][0], "id": "dev-1-ch2"}]}
        assert compute_manifest_hash(modified) != h1


# --- HMAC sign/verify -------------------------------------------------------

class TestHmacSignVerify:
    def test_round_trip_succeeds(self):
        secret = generate_secret()
        ts = time.time()
        payload = {"sourceId": "dev-1-ch1", "values": [1, 2, 3], "startTime": ts}
        sig = sign_payload(payload, secret, ts)
        payload["auth"] = {"sig": sig, "ts": ts}
        ok, reason = verify_payload(payload, secret, server_time=ts)
        assert ok, reason

    def test_signature_mismatch_detected(self):
        secret = generate_secret()
        ts = time.time()
        payload = {"sourceId": "x", "values": [1], "auth": {"sig": "00" * 32, "ts": ts}}
        ok, reason = verify_payload(payload, secret, server_time=ts)
        assert not ok
        assert "signature" in reason

    def test_skew_beyond_window_rejected(self):
        secret = generate_secret()
        ts = time.time()
        payload = {"sourceId": "x", "values": [1]}
        sig = sign_payload(payload, secret, ts)
        payload["auth"] = {"sig": sig, "ts": ts}
        future = ts + MAX_TIMESTAMP_SKEW_SEC + 60
        ok, reason = verify_payload(payload, secret, server_time=future)
        assert not ok
        assert "skew" in reason

    def test_tampered_payload_detected(self):
        secret = generate_secret()
        ts = time.time()
        payload = {"sourceId": "x", "values": [1, 2, 3]}
        sig = sign_payload(payload, secret, ts)
        payload["auth"] = {"sig": sig, "ts": ts}
        # Tamper after signing.
        payload["values"] = [9, 9, 9]
        ok, _ = verify_payload(payload, secret, server_time=ts)
        assert not ok

    def test_missing_auth_block_rejected(self):
        secret = generate_secret()
        ok, reason = verify_payload({"sourceId": "x"}, secret, server_time=time.time())
        assert not ok
        assert "missing" in reason

    def test_wrong_secret_rejected(self):
        s1, s2 = generate_secret(), generate_secret()
        ts = time.time()
        payload = {"sourceId": "x", "values": [1]}
        payload["auth"] = {"sig": sign_payload(payload, s1, ts), "ts": ts}
        ok, _ = verify_payload(payload, s2, server_time=ts)
        assert not ok


# --- Environment toggle -----------------------------------------------------

class TestAuthRequired:
    def test_default_is_true(self, monkeypatch):
        monkeypatch.delenv("ELAB_REQUIRE_AUTH", raising=False)
        assert is_auth_required()

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "FALSE", "Off"])
    def test_disable_keywords(self, monkeypatch, val):
        monkeypatch.setenv("ELAB_REQUIRE_AUTH", val)
        assert not is_auth_required()

    def test_unrecognised_value_keeps_enabled(self, monkeypatch):
        monkeypatch.setenv("ELAB_REQUIRE_AUTH", "yes")
        assert is_auth_required()


# --- ConfigStore credential CRUD --------------------------------------------

@pytest.fixture
def config_store(tmp_path):
    store = ConfigStore(str(tmp_path / "elab.sqlite"))
    yield store
    store.close()


class TestConfigStoreCredentials:
    def test_upsert_pending_creates_row(self, config_store):
        config_store.upsert_pending_credential("dev-1", "secret_hex", "hash1", "10.0.0.1")
        row = config_store.get_credential("dev-1")
        assert row is not None
        assert row["status"] == "pending"
        assert row["secret_hex"] == "secret_hex"
        assert row["manifest_hash"] == "hash1"

    def test_approve_then_get(self, config_store):
        config_store.upsert_pending_credential("dev-1", "s", "h1", None)
        ok = config_store.approve_credential("dev-1", "h1")
        assert ok
        row = config_store.get_credential("dev-1")
        assert row["status"] == "approved"
        assert row["approved_at"] is not None

    def test_approve_fails_on_hash_mismatch(self, config_store):
        config_store.upsert_pending_credential("dev-1", "s", "h1", None)
        assert not config_store.approve_credential("dev-1", "h_wrong")
        row = config_store.get_credential("dev-1")
        assert row["status"] == "pending"

    def test_upsert_preserves_approved_when_hash_unchanged(self, config_store):
        config_store.upsert_pending_credential("dev-1", "s1", "h1", None)
        config_store.approve_credential("dev-1", "h1")
        # Reconnect with the same hash should not demote.
        config_store.upsert_pending_credential("dev-1", "s2", "h1", "1.2.3.4")
        row = config_store.get_credential("dev-1")
        assert row["status"] == "approved"
        # Secret must remain the originally-approved one.
        assert row["secret_hex"] == "s1"

    def test_upsert_repends_on_hash_change(self, config_store):
        config_store.upsert_pending_credential("dev-1", "s1", "h1", None)
        config_store.approve_credential("dev-1", "h1")
        config_store.upsert_pending_credential("dev-1", "s2", "h2_changed", None)
        row = config_store.get_credential("dev-1")
        assert row["status"] == "pending"
        assert row["manifest_hash"] == "h2_changed"

    def test_revoke_then_delete(self, config_store):
        config_store.upsert_pending_credential("dev-1", "s", "h", None)
        config_store.approve_credential("dev-1", "h")
        config_store.revoke_credential("dev-1")
        assert config_store.get_credential("dev-1")["status"] == "revoked"
        config_store.delete_credential("dev-1")
        assert config_store.get_credential("dev-1") is None

    def test_list_filter_by_status(self, config_store):
        config_store.upsert_pending_credential("a", "s", "h", None)
        config_store.upsert_pending_credential("b", "s", "h", None)
        config_store.approve_credential("b", "h")
        pending = config_store.list_credentials(status="pending")
        approved = config_store.list_credentials(status="approved")
        assert {r["device_id"] for r in pending} == {"a"}
        assert {r["device_id"] for r in approved} == {"b"}


# --- SystemState pending / approved helpers ---------------------------------

@pytest.fixture
def state():
    sio = MagicMock()
    return SystemState(sio)


class TestSystemStateAuth:
    def test_pending_then_remove(self, state):
        state.add_pending_provider("sid-1", "dev-1", MANIFEST, "hash", "10.0.0.1")
        snapshot = state.get_pending_list()
        assert len(snapshot) == 1
        assert snapshot[0]["device_id"] == "dev-1"
        assert state.find_pending_sid_by_device("dev-1") == "sid-1"
        assert state.remove_pending_provider("sid-1") is not None
        assert state.get_pending_list() == []

    def test_register_secret_and_lookup(self, state):
        state.register_approved_secret("sid-1", "dev-1", "deadbeef")
        assert state.get_secret_for_sid("sid-1") == "deadbeef"

    def test_get_secret_for_source_via_provider_id(self, state):
        state.providers["sid-1"] = [{"id": "dev-1", "tasks": [{"id": "t1"}]}]
        state.register_approved_secret("sid-1", "dev-1", "k")
        assert state.get_secret_for_source("dev-1") == "k"
        assert state.get_secret_for_source("t1") == "k"
        assert state.get_secret_for_source("unknown") is None

    def test_get_secret_handles_bridge_multiplex(self, state):
        # One sid hosts multiple proxied providers, each with own secret.
        state.providers["bridge-sid"] = [
            {"id": "node-A", "tasks": [{"id": "a-ch"}]},
            {"id": "node-B", "tasks": [{"id": "b-ch"}]},
        ]
        state.register_approved_secret("bridge-sid", "node-A", "k-A")
        # second provider keyed by its own device_id (sid mapping overwritten,
        # but secret cache is per-device).
        state.approved_secrets["node-B"] = "k-B"
        assert state.get_secret_for_source("a-ch") == "k-A"
        assert state.get_secret_for_source("b-ch") == "k-B"

    def test_drop_session_auth_keeps_secret_cache(self, state):
        state.register_approved_secret("sid-1", "dev-1", "k")
        dev = state.drop_session_auth("sid-1")
        assert dev == "dev-1"
        # The cached secret survives so a reconnect with the same device_id
        # can be silently re-approved.
        assert state.approved_secrets["dev-1"] == "k"


# --- Auto-approve token lifecycle ------------------------------------------

class TestAutoApproveTokens:
    def test_issue_and_consume_once(self, state):
        tok = make_auto_approve_token()
        state.issue_auto_approve_token(tok, script="mything.py")
        assert state.consume_auto_approve_token(tok)
        assert not state.consume_auto_approve_token(tok)

    def test_consume_unknown_token_fails(self, state):
        assert not state.consume_auto_approve_token("not-a-real-token")

    def test_consume_none_fails(self, state):
        assert not state.consume_auto_approve_token(None)
        assert not state.consume_auto_approve_token("")
