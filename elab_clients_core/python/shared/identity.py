"""Device identity resolution for E-Lab Python clients.

Every provider belongs to a *device*: the physical or logical unit that carries
the pairing credential. Two boards running identical firmware must still end up
with different device ids, otherwise the dispatcher cannot tell their streams
apart and refuses the second registration.

Anchor ladder
-------------
The id is derived from the strongest available anchor:

``efuse_mac``  chip-unique MAC / efuse value (ESP32 and friends)
``serial``     USB / VISA / instrument serial number
``ble_mac``    MAC of the Bluetooth peripheral a wrapper client is bound to
``assigned``   locally generated UUID, persisted under ``~/.elab/identity``
``ephemeral``  nothing survived a restart - pairing has to be repeated

Wrapper clients (BLE, USB) usually start out ``assigned`` and upgrade to a
hardware anchor once they are bound to a concrete instrument. Call
:func:`resolve_device_identity` again after binding and re-register.

Usage sketch
------------
::

    identity = resolve_device_identity("govee_thermo_hygro", anchor_value=mac)
    manifest = ManifestBuilder(
        identity.provider_id("sensor"),
        "Govee Thermo & Hygro",
        device_id=identity.device_id,
        model=identity.model,
        device_anchor=identity.anchor,
    )
    builder.add_task(identity.task_id("temp"), ...)
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Anchors ordered from strongest to weakest. Mirrors
#: ``elab_server.auth.DEVICE_ANCHORS``.
DEVICE_ANCHORS = ("efuse_mac", "serial", "ble_mac", "assigned", "ephemeral")

#: The manifest schema restricts ids to this alphabet.
_ID_SAFE_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def _identity_dir() -> Path:
    base = os.environ.get("ELAB_CLIENT_IDENTITY_DIR")
    if base:
        return Path(base)
    return Path.home() / ".elab" / "identity"


def sanitize_id(value: str) -> str:
    """Reduce *value* to a schema-safe id without losing uniqueness."""
    safe = _ID_SAFE_RE.sub("_", value)
    if safe == value:
        return safe
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{safe}_{digest}"


@dataclass(frozen=True)
class DeviceIdentity:
    """Resolved identity of one physical or logical device."""

    device_id: str
    model: str
    anchor: str
    name: Optional[str] = None

    @property
    def is_stable(self) -> bool:
        """Whether this id survives a restart and can hold a lasting pairing."""
        return self.anchor != "ephemeral"

    def provider_id(self, suffix: Optional[str] = None) -> str:
        """Return a provider id scoped to this device."""
        return f"{self.device_id}_{sanitize_id(suffix)}" if suffix else self.device_id

    def task_id(self, suffix: str) -> str:
        """Return a globally unique task id scoped to this device."""
        return f"{self.device_id}_{sanitize_id(suffix)}"


def _load_assigned_id(model: str) -> Optional[str]:
    path = _identity_dir() / f"{sanitize_id(model)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read identity file %s: %s", path, exc)
        return None
    device_id = data.get("device_id")
    return device_id if isinstance(device_id, str) and device_id else None


def _save_assigned_id(model: str, device_id: str) -> bool:
    path = _identity_dir() / f"{sanitize_id(model)}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"device_id": device_id, "model": model, "saved_at": time.time()}),
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.warning("Could not persist identity file %s: %s", path, exc)
        return False


def resolve_device_identity(
    model: str,
    *,
    anchor_value: Optional[str] = None,
    anchor: str = "assigned",
    instance: Optional[str] = None,
    name: Optional[str] = None,
) -> DeviceIdentity:
    """Resolve the identity of a device running *model*.

    ``anchor_value`` is a hardware-unique string (MAC, serial number). When it
    is present the id is derived from it and nothing is written to disk - the
    hardware itself is the anchor. Otherwise a UUID is generated once and
    persisted under ``~/.elab/identity/<model>.json``.

    ``instance`` distinguishes several logical devices served by one process
    (e.g. two simulated sensors); it participates in the persisted id so each
    instance keeps its own pairing.
    """
    safe_model = sanitize_id(model)
    key = f"{safe_model}_{sanitize_id(instance)}" if instance else safe_model

    if anchor_value:
        if anchor not in DEVICE_ANCHORS or anchor in ("assigned", "ephemeral"):
            raise ValueError(
                f"anchor_value given but anchor={anchor!r} is not a hardware anchor"
            )
        return DeviceIdentity(f"{key}_{sanitize_id(anchor_value)}", safe_model, anchor, name)

    stored = _load_assigned_id(key)
    if stored:
        return DeviceIdentity(stored, safe_model, "assigned", name)

    device_id = f"{key}_{uuid.uuid4().hex[:12]}"
    if _save_assigned_id(key, device_id):
        logger.info("Assigned new persistent device id %s for model %s", device_id, safe_model)
        return DeviceIdentity(device_id, safe_model, "assigned", name)

    # Storage unavailable: the id is valid for this session only, so the
    # operator will have to approve the device again after a restart.
    logger.warning(
        "Could not persist a device id for %s - running with an ephemeral identity. "
        "Pairing will not survive a restart.",
        safe_model,
    )
    return DeviceIdentity(device_id, safe_model, "ephemeral", name)


__all__ = [
    "DEVICE_ANCHORS",
    "DeviceIdentity",
    "resolve_device_identity",
    "sanitize_id",
]
