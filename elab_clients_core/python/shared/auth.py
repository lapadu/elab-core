"""Client-side helper for the E-Lab device pairing + HMAC protocol.

Usage sketch
------------
::

    from shared.auth import ProviderAuth

    auth = ProviderAuth(device_id=DEVICE_ID)
    sio = socketio.Client()

    # Bind handlers BEFORE connecting so pairing responses are not missed.
    auth.bind(sio)

    sio.connect(dispatcher_url)
    auth.send_register(sio, manifest)  # adds optional auto_approve_token

    # Block until the dispatcher either approved us or told us we are pending.
    if not auth.wait_until_ready(timeout=30):
        log.warning("Provider awaiting operator approval...")
        auth.wait_until_ready(timeout=None)  # block forever

    # Hot path: sign every data_stream packet
    sio.emit("data_stream", auth.sign(payload))

The shared secret is persisted under ``~/.elab/credentials/<device_id>.json``
(chmod 600 on POSIX). After the first successful pairing the device reconnects
silently without operator intervention.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Volatile manifest fields stripped before hashing. MUST stay in sync with
# elab_server/auth.py:_VOLATILE_MANIFEST_FIELDS.
_VOLATILE_MANIFEST_FIELDS = frozenset({"sid", "connected_at", "client_ip", "isUiInstance"})

#: Environment variable that ProcessManager sets for locally-spawned scripts.
AUTO_APPROVE_ENV = "ELAB_AUTO_APPROVE_TOKEN"


def _credentials_dir() -> Path:
    base = os.environ.get("ELAB_CLIENT_CREDENTIALS_DIR")
    if base:
        return Path(base)
    return Path.home() / ".elab" / "credentials"


def _credential_path(device_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "_-." else "_" for c in device_id)
    return _credentials_dir() / f"{safe}.json"


def _strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items()
                if k not in _VOLATILE_MANIFEST_FIELDS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def canonicalize_manifest(manifest: Dict[str, Any]) -> bytes:
    return json.dumps(_strip_volatile(manifest), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_manifest_hash(manifest: Dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_manifest(manifest)).hexdigest()


def _canonical_payload(payload: Dict[str, Any]) -> bytes:
    cleaned = {k: v for k, v in payload.items() if k != "auth"}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sign(secret_hex: str, payload: Dict[str, Any], timestamp: float) -> str:
    secret = bytes.fromhex(secret_hex)
    ts_bytes = f"{timestamp:.6f}".encode("ascii")
    return hmac.new(secret, ts_bytes + b"\n" + _canonical_payload(payload),
                    hashlib.sha256).hexdigest()


class ProviderAuth:
    """Holds the per-device pairing state and signs outgoing data_stream packets.

    Thread-safe for the typical pattern (one connection per instance).
    """

    def __init__(self, device_id: str, persist: bool = True):
        self.device_id = device_id
        self._persist = persist
        self._lock = threading.Lock()
        self._secret_hex: Optional[str] = None
        self._approved = threading.Event()
        self._on_pending: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_revoked: Optional[Callable[[Dict[str, Any]], None]] = None
        if persist:
            self._load_secret()

    # --- persistence ---------------------------------------------------

    def _load_secret(self) -> None:
        path = _credential_path(self.device_id)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            secret = data.get("secret_hex")
            if isinstance(secret, str) and len(secret) >= 32:
                self._secret_hex = secret
                self._approved.set()
                logger.info("Loaded persisted credential for %s", self.device_id)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load credential for %s: %s", self.device_id, exc)

    def _save_secret(self, secret_hex: str) -> None:
        if not self._persist:
            return
        path = _credential_path(self.device_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "device_id": self.device_id,
                "secret_hex": secret_hex,
                "saved_at": time.time(),
            }), encoding="utf-8")
            if os.name == "posix":
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            logger.warning("Failed to persist credential for %s: %s", self.device_id, exc)

    def forget(self) -> None:
        """Wipe the cached secret (e.g. after a server-side revoke)."""
        with self._lock:
            self._secret_hex = None
            self._approved.clear()
        path = _credential_path(self.device_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    # --- protocol ------------------------------------------------------

    def has_secret(self) -> bool:
        with self._lock:
            return self._secret_hex is not None

    def bind(self, sio, on_pending: Optional[Callable[[Dict[str, Any]], None]] = None,
             on_revoked: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        """Register the pairing event handlers on a socketio.Client instance."""
        self._on_pending = on_pending
        self._on_revoked = on_revoked

        @sio.on("registration_approved")
        def _approved(data):
            secret = data.get("secret") if isinstance(data, dict) else None
            if not isinstance(secret, str):
                return
            with self._lock:
                self._secret_hex = secret
            self._save_secret(secret)
            self._approved.set()
            logger.info("✅ Provider %s approved by dispatcher", self.device_id)

        @sio.on("registration_pending")
        def _pending(data):
            logger.info("⏳ Provider %s pending operator approval: %r",
                        self.device_id, data)
            if self._on_pending:
                try:
                    self._on_pending(data or {})
                except Exception:  # pragma: no cover  pylint: disable=broad-except
                    logger.exception("on_pending callback failed")

        @sio.on("registration_revoked")
        def _revoked(data):
            logger.warning("⛔ Provider %s credential revoked: %r", self.device_id, data)
            self.forget()
            sio.disconnect()
            if self._on_revoked:
                try:
                    self._on_revoked(data or {})
                except Exception:  # pragma: no cover  pylint: disable=broad-except
                    logger.exception("on_revoked callback failed")

    def send_register(self, sio, manifest: Dict[str, Any]) -> str:
        """Send register_provider and return the computed manifest hash.

        Adds the one-shot ``auto_approve_token`` from ELAB_AUTO_APPROVE_TOKEN
        env var if present (used by ProcessManager for trusted local scripts).
        """
        token = os.environ.pop(AUTO_APPROVE_ENV, None)
        # Always work on a copy so the original manifest isn't mutated with the
        # ephemeral pairing token.
        payload = dict(manifest)
        if token:
            payload["auto_approve_token"] = token
        sio.emit("register_provider", payload)
        return compute_manifest_hash(manifest)

    def wait_until_ready(self, timeout: Optional[float] = 30.0) -> bool:
        """Block until the dispatcher has issued (or restored) a secret.

        Returns True if a secret is available, False on timeout.
        """
        return self._approved.wait(timeout=timeout)

    def sign(self, payload: Dict[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
        """Return ``payload`` augmented with an ``auth`` block.

        Caller may pass the dict-to-emit directly; the original is mutated
        for efficiency (single-allocation hot path).
        """
        secret = self._secret_hex
        if secret is None:
            raise RuntimeError(f"ProviderAuth({self.device_id}): no secret yet")
        ts = time.time() if now is None else now
        sig = _sign(secret, payload, ts)
        payload["auth"] = {"ts": ts, "sig": sig}
        return payload


__all__ = [
    "AUTO_APPROVE_ENV",
    "ProviderAuth",
    "canonicalize_manifest",
    "compute_manifest_hash",
]
