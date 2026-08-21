"""Provider pairing / authentication state: pending devices, approved secrets,
UI-internal sources and one-shot auto-approval tokens."""
import time
from typing import Any, Dict, List, Optional

from .context import StateContext
from .provider_registry import ProviderRegistry


class PairingStore:
    """Owns the TOFU/HMAC pairing state kept apart from the provider registry.

    Unapproved devices live here (never in ``providers``) so they never appear
    to the UI as active data sources while remaining visible in the
    registration view.
    """

    def __init__(self, ctx: StateContext, providers: ProviderRegistry):
        self._ctx = ctx
        self._providers = providers
        # Providers awaiting operator approval. sid -> {device_id, manifest,
        # manifest_hash, client_ip, first_seen_at}.
        self.pending_providers: Dict[str, Dict[str, Any]] = {}
        # Active approved providers: device_id -> secret_hex (in-memory cache
        # for fast HMAC verification on the data_stream hot path).
        self.approved_secrets: Dict[str, str] = {}
        # sid -> device_id mapping for approved sessions.
        self.sid_to_device: Dict[str, str] = {}
        # One-shot auto-approval tokens issued to locally-spawned scripts via
        # ProcessManager. Consumed on first register_provider use.
        self.auto_approve_tokens: Dict[str, Dict[str, Any]] = {}  # token -> {issued_at, script}
        # Source IDs (provider + task ids) belonging to UI-internal virtual
        # providers (e.g. in-browser simulators). These bypass TOFU/HMAC because
        # the originating socket is already a trusted UI client.
        self.ui_internal_sources: set[str] = set()

    # ------------------------------------------------------------------
    # Pending providers
    # ------------------------------------------------------------------
    def add_pending_provider(
        self,
        sid: str,
        device_id: str,
        manifest: Dict[str, Any],
        manifest_hash: str,
        client_ip: Optional[str] = None,
    ) -> None:
        """Register a provider as awaiting approval (does NOT enter ``providers``)."""
        with self._ctx.lock:
            self.pending_providers[sid] = {
                "device_id": device_id,
                "manifest": manifest,
                "manifest_hash": manifest_hash,
                "client_ip": client_ip,
                "first_seen_at": time.time(),
            }

    def remove_pending_provider(self, sid: str) -> Optional[Dict[str, Any]]:
        """Pop a pending entry by sid."""
        with self._ctx.lock:
            return self.pending_providers.pop(sid, None)

    def get_pending_list(self) -> List[Dict[str, Any]]:
        """Return a serializable snapshot of all pending providers."""
        with self._ctx.lock:
            return [
                {
                    "device_id": entry["device_id"],
                    "manifest": entry["manifest"],
                    "manifest_hash": entry["manifest_hash"],
                    "client_ip": entry.get("client_ip"),
                    "first_seen_at": entry.get("first_seen_at"),
                    "sid": sid,
                }
                for sid, entry in self.pending_providers.items()
            ]

    def find_pending_sid_by_device(self, device_id: str) -> Optional[str]:
        """Return the sid of the pending provider with given device_id, if any."""
        with self._ctx.lock:
            for sid, entry in self.pending_providers.items():
                if entry.get("device_id") == device_id:
                    return sid
        return None

    # ------------------------------------------------------------------
    # Approved secrets
    # ------------------------------------------------------------------
    def register_approved_secret(self, sid: str, device_id: str, secret_hex: str) -> None:
        """Cache an approved provider's secret in memory for fast HMAC verify."""
        with self._ctx.lock:
            self.approved_secrets[device_id] = secret_hex
            self.sid_to_device[sid] = device_id

    def get_secret_for_sid(self, sid: str) -> Optional[str]:
        """Return the cached secret for a session, or ``None`` if not approved."""
        with self._ctx.lock:
            device_id = self.sid_to_device.get(sid)
            if device_id is None:
                return None
            return self.approved_secrets.get(device_id)

    def get_secret_for_source(self, source_id: str) -> Optional[str]:
        """Return the cached secret responsible for a given source / task id.

        Looks up the owning provider's manifest by ``source_id`` (which may be
        the provider id itself or any of its task ids) and returns the secret
        keyed by ``device_id`` (= manifest['id']). This works correctly even
        when several providers are multiplexed through one Socket.IO session
        (e.g. via the bridge daemon).
        """
        with self._ctx.lock:
            for p_list in self._providers.providers.values():
                for provider in p_list:
                    if provider.get('id') == source_id:
                        return self.approved_secrets.get(provider['id'])
                    for task in provider.get('tasks', []) or []:
                        if task.get('id') == source_id:
                            pid = provider.get('id')
                            if pid:
                                return self.approved_secrets.get(pid)
                            return None
        return None

    def drop_session_auth(self, sid: str) -> Optional[str]:
        """Remove session-level auth state on disconnect. Returns device_id if any."""
        with self._ctx.lock:
            device_id = self.sid_to_device.pop(sid, None)
            # Keep ``approved_secrets`` intact across reconnects (TOFU persists).
            return device_id

    # ------------------------------------------------------------------
    # Auto-approval tokens
    # ------------------------------------------------------------------
    def issue_auto_approve_token(self, token: str, script: Optional[str] = None) -> None:
        """Register a one-shot auto-approval token (used by ProcessManager)."""
        with self._ctx.lock:
            self.auto_approve_tokens[token] = {
                "issued_at": time.time(),
                "script": script,
            }

    def consume_auto_approve_token(self, token: Optional[str]) -> bool:
        """Atomically consume an auto-approval token. Returns True if valid."""
        if not isinstance(token, str) or not token:
            return False
        with self._ctx.lock:
            return self.auto_approve_tokens.pop(token, None) is not None

    # ------------------------------------------------------------------
    # UI-internal sources
    # ------------------------------------------------------------------
    def mark_ui_internal(self, source_id: str) -> None:
        """Tag a source id as belonging to a trusted UI-internal provider."""
        if not source_id:
            return
        with self._ctx.lock:
            self.ui_internal_sources.add(source_id)

    def is_ui_internal(self, source_id: str) -> bool:
        """Whether *source_id* bypasses TOFU/HMAC as a UI-internal source."""
        with self._ctx.lock:
            return source_id in self.ui_internal_sources

    def forget_sources(self, providers: List[Dict[str, Any]]) -> None:
        """Drop UI-internal source-id registrations for removed providers."""
        with self._ctx.lock:
            for manifest in providers:
                pid = manifest.get('id')
                if pid:
                    self.ui_internal_sources.discard(pid)
                for task in manifest.get('tasks', []) or []:
                    if not isinstance(task, dict):
                        continue
                    tid = task.get('id')
                    if tid:
                        self.ui_internal_sources.discard(tid)
