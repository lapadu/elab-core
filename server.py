"""Main entry point for the E-Lab server."""

import gevent.monkey  # pylint: disable=unused-import

gevent.monkey.patch_all()

import io   # noqa: E402
import sys  # noqa: E402

# Force UTF-8 on stdout/stderr so emoji log lines don't crash under
# PyInstaller or when spawned from Electron on Windows (cp1252 default).
STDOUT_ENCODING = str(getattr(sys.stdout, 'encoding', None) or 'utf-8')
if STDOUT_ENCODING.lower().replace('-', '') != 'utf8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
STDERR_ENCODING = str(getattr(sys.stderr, 'encoding', None) or 'utf-8')
if STDERR_ENCODING.lower().replace('-', '') != 'utf8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import json  # noqa: E402
import logging  # noqa: E402
import gevent  # noqa: E402
import time  # noqa: E402

# Suppress noisy ConnectionResetError tracebacks from engineio writer
# greenlets when a client process is killed (socket already gone).
hub = gevent.get_hub()
hub.NOT_ERROR += (ConnectionResetError,)


class _JsonErrorFilter(logging.Filter):
    """Downgrade repeated JSONDecodeError tracebacks from misbehaving
    clients to a single-line warning to avoid log spam.

    Historically the ESP32 voltmeter emitted oversized Socket.IO frames
    that engineio truncated, producing a flood of identical decode errors.
    The firmware now chunks frames at <= 1024 samples (see
    elab_clients_core/esp32/arduino/voltmeter.ino, MAX_VALUES_PER_FRAME), so this
    filter is mostly a safety net for third-party clients that violate
    the WebSocket buffer limit.

    Rate-limit is per (error message, position) pair so that distinct
    errors are still surfaced quickly, while a flood of the same
    truncated-payload error is throttled.
    """

    _WINDOW_S: float = 10.0
    _last_warn: dict = {}

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc = record.exc_info[1]
            if isinstance(exc, json.JSONDecodeError):
                key = (exc.msg, exc.pos)
                now = time.time()
                last = self._last_warn.get(key, 0.0)
                # Periodic cheap cleanup: cap the dict to avoid memory leak
                # if many distinct errors stream in over a long uptime.
                if len(self._last_warn) > 1024:
                    self._last_warn.clear()
                if now - last > self._WINDOW_S:
                    self._last_warn[key] = now
                    record.msg = (
                        "Malformed JSON from client (pos %d: %s). "
                        "Likely truncated payload from ESP32."
                    )
                    record.args = (exc.pos, exc.msg)
                    record.exc_info = None
                    record.exc_text = None
                    record.levelno = logging.WARNING
                    record.levelname = "WARNING"
                    return True
                return False
        return True


logging.getLogger("engineio.server").addFilter(_JsonErrorFilter())
logging.getLogger("engineio").addFilter(_JsonErrorFilter())

if __name__ == "__main__":
    from elab_server.main import main

    main()
