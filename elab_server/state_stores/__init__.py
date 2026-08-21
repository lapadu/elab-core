"""Focused state stores composed by :class:`elab_server.state.SystemState`.

The stores share a single re-entrant lock via :class:`StateContext` so that
operations spanning several stores (e.g. removing a provider also purges its
actuator links and pending-auth state) stay atomic, exactly like the previous
monolithic ``SystemState.atomic_update`` block.
"""
from .context import StateContext
from .provider_registry import ProviderRegistry
from .actuator_links import ActuatorLinkRegistry
from .pairing_store import PairingStore
from .task_meta import TaskMetaStore

__all__ = [
    "StateContext",
    "ProviderRegistry",
    "ActuatorLinkRegistry",
    "PairingStore",
    "TaskMetaStore",
]
