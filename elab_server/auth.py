"""HMAC-based authentication for E-Lab providers.

Trust on First Use (TOFU) device pairing + HMAC-SHA256 signed data_stream packets.

Identity model
--------------
* ``device_id``     -> ``manifest["id"]`` (permanent, client-chosen, stable across reboots)
* ``manifest_hash`` -> SHA-256 hex of a canonicalized projection of the manifest
* ``secret``        -> 32-byte server-generated value, sent once to the client at approval

Lifecycle
---------
1. Client connects and sends ``register_provider`` with its manifest.
2. Server computes ``manifest_hash`` from the canonical projection and looks up the
   credential by ``device_id`` in :class:`ConfigStore`.
3. Unknown ``device_id`` or unknown ``manifest_hash``:
   * Server generates a fresh secret, stores a row in state ``'pending'``,
     and emits ``registration_pending`` to the client.
   * ``data_stream`` packets from this provider are rejected until approval.
4. Operator approves the device in the UI: status flips to ``'approved'`` and the
   server emits ``registration_approved`` with the secret (one-shot delivery).
5. Approved provider signs every ``data_stream`` packet with HMAC-SHA256.
   The server verifies the signature; mismatches are dropped silently.

The secret is *never* transmitted again after the initial pairing handshake.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# --- Configuration ----------------------------------------------------------

#: Maximum tolerated skew (seconds) between client timestamp in the auth block
#: and the server clock. Mitigates replay across long windows.
MAX_TIMESTAMP_SKEW_SEC = 300.0

#: Fields that vary per-connection and must be stripped before hashing the manifest.
_VOLATILE_MANIFEST_FIELDS = frozenset({
    "sid",
    "connected_at",
    "client_ip",
    "isUiInstance",
})


def _strip_volatile(obj: Any) -> Any:
    """Return a deep copy of ``obj`` with volatile bookkeeping fields removed."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v)
            for k, v in obj.items()
            if k not in _VOLATILE_MANIFEST_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def canonicalize_manifest(manifest: Dict[str, Any]) -> bytes:
    """Return the canonical byte representation used for hashing.

    Uses ``json.dumps`` with ``sort_keys=True`` and tight separators so any
    platform (CPython, ESP32 ArduinoJson + helper) can reproduce the exact bytes.
    """
    cleaned = _strip_volatile(manifest)
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_manifest_hash(manifest: Dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of the canonical manifest projection."""
    return hashlib.sha256(canonicalize_manifest(manifest)).hexdigest()


def generate_secret() -> str:
    """Return a fresh 32-byte (64 hex char) shared secret."""
    return secrets.token_hex(32)


# --- HMAC signing -----------------------------------------------------------

def _canonical_payload(payload: Dict[str, Any]) -> bytes:
    """Canonical byte representation of a data_stream payload for HMAC input.

    The ``auth`` block itself is excluded so the signature can be embedded.
    Binary fields (``raw_bytes``, ``binary_payload``) are handled by their JSON
    representation; for raw bytes the client must include them already-decoded
    in the payload before signing, identically to what the server sees.
    """
    cleaned = {k: v for k, v in payload.items() if k != "auth"}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_payload(payload: Dict[str, Any], secret_hex: str, timestamp: float) -> str:
    """Compute the HMAC-SHA256 signature for a data_stream payload.

    The signature covers ``timestamp || '\\n' || canonical_payload``. Including
    the timestamp inside the MAC input prevents an attacker from rebinding a
    captured signature to a different ``ts`` field.
    """
    secret = bytes.fromhex(secret_hex)
    ts_bytes = f"{timestamp:.6f}".encode("ascii")
    mac_input = ts_bytes + b"\n" + _canonical_payload(payload)
    return hmac.new(secret, mac_input, hashlib.sha256).hexdigest()


def verify_payload(
    payload: Dict[str, Any],
    secret_hex: str,
    *,
    server_time: float,
    max_skew_sec: float = MAX_TIMESTAMP_SKEW_SEC,
) -> Tuple[bool, str]:
    """Verify the HMAC signature on a data_stream payload.

    Returns ``(ok, reason)``. ``reason`` is empty on success.
    """
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return False, "missing auth block"
    sig = auth.get("sig")
    ts = auth.get("ts")
    if not isinstance(sig, str) or not isinstance(ts, (int, float)):
        return False, "malformed auth block"
    if abs(server_time - float(ts)) > max_skew_sec:
        return False, "timestamp skew exceeds limit"
    expected = sign_payload(payload, secret_hex, float(ts))
    if not hmac.compare_digest(expected, sig):
        logger.warning("HMAC MISMATCH DEBUG: canonical=%r, ts=%s", _canonical_payload(payload), ts)
        return False, "signature mismatch"
    return True, ""


# --- Auto-approval token (for locally-spawned scripts) ----------------------

#: Environment variable carrying a one-shot pairing token from process_manager.
AUTO_APPROVE_ENV = "ELAB_AUTO_APPROVE_TOKEN"


def is_auth_required() -> bool:
    """Whether HMAC authentication is enforced.

    Defaults to ``True``. Set ``ELAB_REQUIRE_AUTH=0`` (or ``false``/``no``) to disable
    for tests or legacy deployments.
    """
    raw = os.environ.get("ELAB_REQUIRE_AUTH")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def make_auto_approve_token() -> str:
    """Return a fresh single-use auto-approval token."""
    return secrets.token_urlsafe(24)


# Re-export for convenience
__all__ = [
    "MAX_TIMESTAMP_SKEW_SEC",
    "AUTO_APPROVE_ENV",
    "canonicalize_manifest",
    "compute_manifest_hash",
    "generate_secret",
    "sign_payload",
    "verify_payload",
    "is_auth_required",
    "make_auto_approve_token",
]
