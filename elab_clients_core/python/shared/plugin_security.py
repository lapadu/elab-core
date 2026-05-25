"""Helpers to lock down remote plugin loading via Subresource Integrity (SRI).

Plugins are usually a single JS file served by the Python client over its own
HTTP server. The dispatcher forwards the URL via the manifest's ``ui.url``
field. To prevent a malicious or hijacked client from tricking a workbench
into loading an arbitrary script, the client publishes a SHA-256 SRI hash
alongside the URL (``ui.integrity``). The browser refuses to execute the
script if the hash does not match.

This protects against:
  * MITM injection on the LAN.
  * A compromised plugin file silently swapped on the client host.

It does NOT protect against a fully malicious provider that controls both the
script and the manifest. For that, an additional dispatcher-side allow-list
of accepted plugin origins is required (see ``ELAB_PLUGIN_ORIGINS`` in the
server config).
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Literal

Algo = Literal["sha256", "sha384", "sha512"]


def compute_plugin_sri(file_path: str, algorithm: Algo = "sha256") -> str:
    """Return the SRI integrity string for *file_path*.

    Example return value::

        "sha256-abc123==..."

    Raises:
        FileNotFoundError: when the plugin file does not exist.
        ValueError: when *algorithm* is not supported by SRI.
    """
    if algorithm not in ("sha256", "sha384", "sha512"):
        raise ValueError(f"Unsupported SRI algorithm: {algorithm}")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)

    hasher = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        # Stream in 64 KiB chunks so even huge bundles never load fully into RAM.
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    digest_b64 = base64.b64encode(hasher.digest()).decode("ascii")
    return f"{algorithm}-{digest_b64}"
