"""Tests for the client-side ``ProviderAuth`` helper.

Verifies that:
* persistence round-trip works (secret loaded from disk on next instance)
* ``send_register`` consumes ``ELAB_AUTO_APPROVE_TOKEN`` exactly once
* the registration_approved handler stores + persists the secret
* the registration_revoked handler wipes both in-memory and on-disk state
* ``sign`` produces a signature accepted by the server-side ``verify_payload``
* canonicalization on both sides is byte-identical
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

# Import the shared client helper directly via path injection so we don't need
# the elab_clients_core package on sys.path.
_SHARED = Path(__file__).resolve().parent.parent / "elab_clients_core" / "python" / "shared"
sys.path.insert(0, str(_SHARED))

import auth as client_auth  # noqa: E402

from elab_server.auth import (  # noqa: E402
    canonicalize_manifest as server_canonicalize,
    compute_manifest_hash as server_hash,
    generate_secret,
    verify_payload,
)


MANIFEST = {
    "id": "client-dev-1",
    "name": "Client Test",
    "category": "HARDWARE",
    "version": "1.0",
    "capabilities": ["measure"],
    "tasks": [{"id": "client-dev-1-ch1", "name": "ch", "type": "SENSOR",
               "ui": {"mode": "generic"}}],
}


@pytest.fixture
def isolated_creds_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ELAB_CLIENT_CREDENTIALS_DIR", str(tmp_path))
    yield tmp_path


class FakeSio:
    """Minimal stand-in for socketio.Client capturing handlers + emits."""

    def __init__(self):
        self._handlers = {}
        self.emits = []

    def on(self, event):
        def decorator(fn):
            self._handlers[event] = fn
            return fn
        return decorator

    def emit(self, event, data=None):
        self.emits.append((event, data))

    def trigger(self, event, data):
        self._handlers[event](data)


# --- Canonicalization parity -----------------------------------------------

def test_client_and_server_canonicalize_identically():
    assert client_auth.canonicalize_manifest(MANIFEST) == server_canonicalize(MANIFEST)
    assert client_auth.compute_manifest_hash(MANIFEST) == server_hash(MANIFEST)


# --- Persistence round-trip -------------------------------------------------

class TestPersistence:
    def test_secret_persists_across_instances(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-x")
        assert not a.has_secret()
        sio = FakeSio()
        a.bind(sio)
        sio.trigger("registration_approved",
                    {"deviceId": "dev-x", "secret": generate_secret()})
        assert a.has_secret()
        # Fresh instance: must load from disk.
        b = client_auth.ProviderAuth(device_id="dev-x")
        assert b.has_secret()

    def test_forget_wipes_disk(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-y")
        sio = FakeSio()
        a.bind(sio)
        sio.trigger("registration_approved",
                    {"deviceId": "dev-y", "secret": generate_secret()})
        a.forget()
        assert not a.has_secret()
        b = client_auth.ProviderAuth(device_id="dev-y")
        assert not b.has_secret()

    def test_persist_false_does_not_write(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-mem", persist=False)
        sio = FakeSio()
        a.bind(sio)
        sio.trigger("registration_approved",
                    {"deviceId": "dev-mem", "secret": generate_secret()})
        # In-memory only.
        assert a.has_secret()
        files = list(isolated_creds_dir.glob("*.json"))
        assert files == []


# --- send_register / auto-approve token -------------------------------------

class TestSendRegister:
    def test_includes_token_from_env_and_consumes_it(self, isolated_creds_dir, monkeypatch):
        monkeypatch.setenv(client_auth.AUTO_APPROVE_ENV, "tok-123")
        a = client_auth.ProviderAuth(device_id="dev-tok")
        sio = FakeSio()
        a.send_register(sio, MANIFEST)
        ev, data = sio.emits[-1]
        assert ev == "register_provider"
        assert data["auto_approve_token"] == "tok-123"
        # Env var must be consumed atomically so a retry never replays it.
        assert client_auth.AUTO_APPROVE_ENV not in os.environ

    def test_no_token_means_no_field(self, isolated_creds_dir, monkeypatch):
        monkeypatch.delenv(client_auth.AUTO_APPROVE_ENV, raising=False)
        a = client_auth.ProviderAuth(device_id="dev-notok")
        sio = FakeSio()
        a.send_register(sio, MANIFEST)
        _, data = sio.emits[-1]
        assert "auto_approve_token" not in data

    def test_does_not_mutate_input_manifest(self, isolated_creds_dir, monkeypatch):
        monkeypatch.setenv(client_auth.AUTO_APPROVE_ENV, "tk")
        a = client_auth.ProviderAuth(device_id="dev-noclobber")
        sio = FakeSio()
        original = dict(MANIFEST)
        a.send_register(sio, MANIFEST)
        assert "auto_approve_token" not in MANIFEST
        assert MANIFEST == original


# --- Revoke handler ---------------------------------------------------------

class TestRevoke:
    def test_revoke_clears_in_memory_and_on_disk(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-rev")
        sio = FakeSio()
        a.bind(sio)
        sio.trigger("registration_approved",
                    {"deviceId": "dev-rev", "secret": generate_secret()})
        assert a.has_secret()
        sio.trigger("registration_revoked", {"deviceId": "dev-rev"})
        assert not a.has_secret()
        assert not list(isolated_creds_dir.glob("*.json"))


# --- Sign / verify interop --------------------------------------------------

class TestSignVerifyInterop:
    def test_round_trip_with_server_verify(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-sign")
        sio = FakeSio()
        a.bind(sio)
        secret = generate_secret()
        sio.trigger("registration_approved", {"deviceId": "dev-sign", "secret": secret})

        payload = {"sourceId": "dev-sign-ch1", "values": [1, 2, 3], "startTime": 0.5}
        signed = a.sign(payload)
        assert "auth" in signed
        ok, reason = verify_payload(signed, secret, server_time=signed["auth"]["ts"])
        assert ok, reason

    def test_sign_without_secret_raises_or_skips(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-nosecret")
        # The helper should refuse to sign without an approved secret; doc'd
        # contract is to gate calls with has_secret(), but we still want a
        # clear error rather than silent corruption.
        if a.has_secret():  # safety net
            pytest.skip("unexpected leftover secret")
        with pytest.raises((RuntimeError, ValueError, AssertionError, TypeError)):
            a.sign({"sourceId": "x", "values": [1]})


# --- wait_until_ready -------------------------------------------------------

class TestWaitUntilReady:
    def test_returns_true_immediately_when_already_approved(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-ready")
        sio = FakeSio()
        a.bind(sio)
        sio.trigger("registration_approved",
                    {"deviceId": "dev-ready", "secret": generate_secret()})
        t0 = time.time()
        assert a.wait_until_ready(timeout=0.1)
        assert time.time() - t0 < 0.05

    def test_timeout_returns_false_when_pending(self, isolated_creds_dir):
        a = client_auth.ProviderAuth(device_id="dev-wait")
        assert not a.wait_until_ready(timeout=0.05)
