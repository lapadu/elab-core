"""Stateless helpers and module-level caches shared by socket handlers.

This module exists so the handler groups (auth / provider / session /
plugin) can stay focused on routing instead of repeating uncertainty math,
binary payload limits or the plugin URL allow-list.

Nothing in here registers Socket.IO handlers; the constants and caches
are deliberately module-level so the dispatcher process keeps a single
shared view (the per-source clock offsets, for example).
"""
from __future__ import annotations

import logging
import math
import os
import threading
from typing import Any
from urllib.parse import urlparse


logger = logging.getLogger(__name__)


# --- Module-level state -----------------------------------------------------

# Per-source clock offset (server_ms - client_ms). Protected by
# ``_time_offsets_lock`` because Socket.IO handlers may run in parallel
# under gevent/threading.
_time_offsets: dict = {}
_time_offsets_lock = threading.Lock()

# Soft cap so a misbehaving client (or one cycling fake source_ids) cannot
# leak unbounded memory. Configurable via env var for very large labs.
_MAX_TIME_OFFSETS = max(
    256,
    int(os.environ.get('ELAB_MAX_TIME_OFFSETS', '4096')),
)

# Hard cap on a single inbound binary payload (per data_stream frame).
# Protects the dispatcher from a misbehaving ESP32 sending oversized buffers.
# Override via the ELAB_MAX_BINARY_PAYLOAD env var (bytes).
_MAX_BINARY_PAYLOAD = int(os.environ.get('ELAB_MAX_BINARY_PAYLOAD', 64 * 1024))

# Optional comma-separated allow-list of additional plugin origins
# (e.g. "http://internal-cdn.lab:8080"). Provider-supplied URLs that don't
# resolve to either the registering provider's own client IP or one of these
# origins are stripped from the manifest before it reaches the workbench.
_PLUGIN_ORIGIN_ALLOWLIST = {
    o.strip().rstrip('/').lower()
    for o in os.environ.get('ELAB_PLUGIN_ORIGINS', '').split(',')
    if o.strip()
}


# --- Numeric helpers --------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Return finite float(value) or *default* for invalid input."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


def _pick_observed_value(payload: dict) -> float:
    """Pick a representative value from a data_stream payload."""
    val = payload.get('value')
    if isinstance(val, (int, float)) and math.isfinite(float(val)):
        return float(val)
    vals = payload.get('values')
    if isinstance(vals, list):
        for raw in reversed(vals):
            if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
                return float(raw)
    return 0.0


def _get_task_for_source(state: Any, source_id: str) -> dict | None:
    """Return task manifest dict for a source id, if currently registered."""
    return state.get_task(source_id)


def _resolve_digit_step(accuracy: dict, decoder: Any) -> float:
    """Resolve one-digit step in decoded units for the configured reference."""
    ref = accuracy.get('digitReference', 'ui_lsd')
    if ref == 'ui_lsd':
        return abs(_safe_float(accuracy.get('displayStep'), 0.0))
    if ref == 'explicit_step':
        return abs(_safe_float(accuracy.get('digitStep'), 0.0))
    if ref == 'adc_lsb':
        if decoder and hasattr(decoder, 'adc_lsb_decoded'):
            try:
                return abs(float(decoder.adc_lsb_decoded()))
            except (TypeError, ValueError):
                return 0.0
        return 0.0
    return 0.0


def _uncertainty_from_accuracy(accuracy: dict | None, value: float, decoder: Any) -> dict | None:
    """Build decoded-domain uncertainty from the accuracy object."""
    if not isinstance(accuracy, dict):
        return None

    model = accuracy.get('model')
    if not isinstance(model, str):
        return None

    abs_v = abs(_safe_float(value, 0.0))
    systematic_abs = 0.0
    random_sigma = 0.0

    if model == 'percent_reading':
        systematic_abs = abs_v * _safe_float(accuracy.get('relativePctReading'), 0.0) / 100.0
    elif model == 'absolute':
        systematic_abs = abs(_safe_float(accuracy.get('absoluteOffset'), 0.0))
    elif model == 'percent_reading_plus_absolute':
        systematic_abs = (
            abs_v * _safe_float(accuracy.get('relativePctReading'), 0.0) / 100.0
            + abs(_safe_float(accuracy.get('absoluteOffset'), 0.0))
        )
    elif model == 'percent_reading_plus_digits':
        digit_step = _resolve_digit_step(accuracy, decoder)
        systematic_abs = (
            abs_v * _safe_float(accuracy.get('relativePctReading'), 0.0) / 100.0
            + abs(_safe_float(accuracy.get('digits'), 0.0)) * digit_step
            + abs(_safe_float(accuracy.get('absoluteOffset'), 0.0))
        )
    elif model == 'adc_quantization_only':
        adc_step = _resolve_digit_step({'digitReference': 'adc_lsb'}, decoder)
        random_sigma = adc_step / math.sqrt(12.0) if adc_step > 0.0 else 0.0
    elif model == 'combined':
        sys_part = _uncertainty_from_accuracy(accuracy.get('systematic'), value, decoder) or {}
        rnd_part = _uncertainty_from_accuracy(accuracy.get('random'), value, decoder) or {}
        systematic_abs = abs(_safe_float(sys_part.get('systematicAbs'), 0.0))
        random_sigma = abs(_safe_float(rnd_part.get('randomSigma'), 0.0))
    elif model == 'random_sigma':
        random_sigma = abs(_safe_float(accuracy.get('randomSigma'), 0.0))
    else:
        return None

    return {
        'domain': 'decoded',
        'model': 'combined',
        'systematicAbs': systematic_abs,
        'randomSigma': random_sigma,
        'confidenceK': _safe_float(accuracy.get('confidenceK'), 2.0),
        'source': 'manifest_accuracy',
    }


def _merge_uncertainty(base: dict | None, extra: dict | None) -> dict | None:
    """Merge two uncertainty objects in decoded domain."""
    if not isinstance(base, dict) and not isinstance(extra, dict):
        return None
    if not isinstance(base, dict):
        out = dict(extra)
        out['domain'] = 'decoded'
        return out
    if not isinstance(extra, dict):
        out = dict(base)
        out['domain'] = 'decoded'
        return out

    out = dict(base)
    out['domain'] = 'decoded'
    out['model'] = 'combined'
    out['systematicAbs'] = (
        abs(_safe_float(base.get('systematicAbs'), 0.0))
        + abs(_safe_float(extra.get('systematicAbs'), 0.0))
    )
    out['randomSigma'] = math.sqrt(
        _safe_float(base.get('randomSigma'), 0.0) ** 2
        + _safe_float(extra.get('randomSigma'), 0.0) ** 2
    )
    out['confidenceK'] = _safe_float(base.get('confidenceK'), _safe_float(extra.get('confidenceK'), 2.0))
    return out


# --- Plugin URL allow-list --------------------------------------------------

def _is_plugin_url_allowed(url: str, client_ip: str) -> bool:
    """Return True if *url* may be loaded into the workbench.

    The plugin script must come from either the provider's own client IP or
    from an explicitly whitelisted origin. This stops a hijacked manifest
    from pointing the browser at an arbitrary attacker host.
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    if not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if client_ip and isinstance(client_ip, str) and host == client_ip.lower():
        return True
    origin = f"{parsed.scheme}://{host}"
    
    # Erlaube Platzhalter für Ports, z.B. http://127.0.0.1:*
    wildcard_origin = f"{origin}:*"
    
    if parsed.port:
        origin = f"{origin}:{parsed.port}"
        
    return (origin.lower() in _PLUGIN_ORIGIN_ALLOWLIST or
            wildcard_origin.lower() in _PLUGIN_ORIGIN_ALLOWLIST)


def _sanitize_plugin_urls(manifest: dict, client_ip: str) -> None:
    """Strip ui.url/ui.integrity from any task whose URL is not allow-listed.

    Mutates *manifest* in place.
    """
    for task in manifest.get('tasks', []) or []:
        ui = task.get('ui') if isinstance(task, dict) else None
        if not isinstance(ui, dict):
            continue
        url = ui.get('url')
        if not url:
            continue
        if not _is_plugin_url_allowed(url, client_ip):
            logger.warning(
                "Stripped untrusted plugin URL %s from task %s (client_ip=%s)",
                url, task.get('id'), client_ip,
            )
            ui.pop('url', None)
            ui.pop('integrity', None)
            # Fall back to generic UI so the workbench still renders something.
            ui['mode'] = 'generic'


# --- Time-offset cache helpers ---------------------------------------------

def _drop_time_offsets_for(source_ids) -> None:
    """Remove cached offsets for a set of source ids (called on disconnect)."""
    if not source_ids:
        return
    with _time_offsets_lock:
        for sid in source_ids:
            _time_offsets.pop(sid, None)


def _get_offset(source_id: str, client_ts_ms: float, now_ms: float) -> float:
    """Return a stable client->server clock offset; recompute if it drifts."""
    with _time_offsets_lock:
        offset = _time_offsets.get(source_id)
        if offset is None or abs((client_ts_ms + offset) - now_ms) > 2000:
            offset = now_ms - client_ts_ms
            # Enforce the soft cap with FIFO eviction. ``dict`` keeps insertion
            # order since Python 3.7, so popping the first item is the oldest
            # entry. Cheap O(1) operations under the lock.
            if source_id not in _time_offsets and len(_time_offsets) >= _MAX_TIME_OFFSETS:
                try:
                    oldest_key = next(iter(_time_offsets))
                    _time_offsets.pop(oldest_key, None)
                except StopIteration:
                    pass
            _time_offsets[source_id] = offset
        else:
            # Refresh insertion order so active sources are not evicted as
            # 'oldest' by the cap above.
            _time_offsets.pop(source_id, None)
            _time_offsets[source_id] = offset
        return offset
