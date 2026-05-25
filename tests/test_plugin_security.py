"""Tests for elab_clients_core.python.shared.plugin_security."""
import os
import hashlib
import base64

from elab_clients_core.python.shared.plugin_security import compute_plugin_sri


def test_sri_matches_manual_sha256(tmp_path):
    """SRI output must match a manually computed SHA-256 hash."""
    f = tmp_path / "plugin.js"
    payload = b"console.log('hi');\n" * 100
    f.write_bytes(payload)

    expected = "sha256-" + base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
    assert compute_plugin_sri(str(f)) == expected


def test_sri_supports_sha384(tmp_path):
    """SRI hash for sha384 algorithm must start with the correct prefix."""
    f = tmp_path / "plugin.js"
    f.write_bytes(b"x")
    sri = compute_plugin_sri(str(f), algorithm="sha384")
    assert sri.startswith("sha384-")


def test_sri_streams_large_file(tmp_path):
    """Multi-chunk streaming must produce the same hash as a single-pass hashlib run."""
    # 1 MiB so we cross multiple 64 KiB chunks.
    f = tmp_path / "big.js"
    payload = os.urandom(1024 * 1024)
    f.write_bytes(payload)

    sri = compute_plugin_sri(str(f))
    expected = "sha256-" + base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
    assert sri == expected


def test_sri_missing_file_returns_none_or_raises(tmp_path):
    """A missing file must either raise FileNotFoundError/OSError or return None."""
    # Either behavior is acceptable; the helper must not crash silently with
    # an empty hash that would create a forged-but-empty SRI.
    missing = tmp_path / "nope.js"
    try:
        result = compute_plugin_sri(str(missing))
    except (FileNotFoundError, OSError):
        return
    assert result is None
