# pylint: disable=invalid-name
"""
E-Lab Python port of the ESP32 ``VoltageActuatorClient`` (nanoFramework).

This client registers a generic voltage actuator with the dispatcher and
receives ``execute_command`` messages. It mirrors the C# reference
implementation feature-for-feature:

* **Buffering / cache handling:** incoming samples are pushed into a thread-safe
  playback queue instead of being applied immediately.
* **Timed playback thread:** a dedicated consumer thread dequeues samples at a
  configurable interval (default 50 Hz / 20 ms), so bursts of values are played
  back with the correct timing.
* **Array & scalar commands:** both ``values`` arrays (with optional
  ``startTime`` / ``endTime`` for automatic timing) and single ``value`` scalars
  are supported.
* **Auto-timing:** when start/end timestamps accompany an array, the per-sample
  interval is derived automatically; timestamp units are detected by magnitude,
  so high-rate (kHz) streams are handled correctly.

Instead of driving a PWM/LED output, the received signal is plotted live in a
matplotlib chart for debugging on a laptop. The client is signal-agnostic: it
auto-scales to any amplitude and handles high-rate (kHz) streams, and the chart
provides a Reset button to clear the view.
"""

import os
import sys
import time
import signal
import logging
import threading
import argparse
from collections import deque
from typing import Any, Deque, Optional

project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(project_root)
# Add the client directory as an import root for the shared-module fallback.
_clients_dir = os.path.dirname(os.path.abspath(__file__))
if _clients_dir not in sys.path:
    sys.path.insert(0, _clients_dir)
# Add the python/ parent directory so ``from shared.X import …`` works when the
# client is launched directly from elab_clients_core/python/clients/.
_python_dir = os.path.dirname(_clients_dir)
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)

import socketio


def discover_dispatcher(*_args: Any, **_kwargs: Any) -> Optional[str]:
    """Fallback discovery function replaced by shared import when available."""
    return None


try:
    # Preferred: absolute import that always resolves when the project root is
    # on sys.path (server-spawned and dev workflows).
    from elab_clients_core.python.shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from elab_clients_core.python.shared.auth import ProviderAuth  # type: ignore[import-not-found]
except ImportError:
    # Fallback: launched from the clients dir. ``_python_dir`` is on sys.path
    # above so ``from shared.X import …`` resolves cleanly.
    from shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from shared.auth import ProviderAuth  # type: ignore[import-not-found]

from elab_server.manifest_builder import ManifestBuilder

# ==========================================
# CONFIGURATION
# ==========================================
UDP_PORT = 5005
DEFAULT_PLAYBACK_INTERVAL_MS = 20  # 50 Hz (matches the C# default)
QUEUE_OVERFLOW_LIMIT = 2000  # Drop the buffer if it grows beyond this (C# parity)
CHART_WINDOW = 4000  # Number of received samples kept in the live chart window

INSTANCE_ID = int(time.time() * 1000) % 100000
PROVIDER_ID = f"py_voltage_actuator_{INSTANCE_ID}"
PROVIDER_NAME = "Python Voltage Actuator"
TASK_ID = f"{PROVIDER_ID}_v_out"

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(PROVIDER_NAME)

# pylint: disable=C0301


# ==========================================
# DEVICE MANIFEST (generic actuator)
# ==========================================
def build_manifest() -> dict[str, Any]:
    """Builds the actuator manifest with a generic actuator UI template."""
    builder = ManifestBuilder(PROVIDER_ID, PROVIDER_NAME)
    builder.add_task(
        task_id=TASK_ID,
        name="Voltage Output",
        task_type="ACTUATOR",
        color="#22c55e",
        tags=["Voltage", "Actuator", "Debug"],
        config={
            "unit": "V",
            "range": [-10, 10],
            "min": -10,
            "max": 10,
            "step": 0.1,
            "value": 0.0,
        },
        ui_mode="generic",
        ui_default_template="tpl_generic_actuator",
    )
    return builder.build()


# ==========================================
# CHART SINK (replaces the PWM/LED output)
# ==========================================
class ChartSink:
    """Thread-safe rolling buffer that feeds the live debug chart.

    Received samples are stored against their *source* timestamps, so the chart
    shows the transmitted signal faithfully (true frequency/shape) regardless of
    the playback thread's timing. The matplotlib animation (main thread) reads a
    snapshot on every frame.
    """

    def __init__(self, window: int = CHART_WINDOW) -> None:
        self._lock = threading.Lock()
        self._times: Deque[float] = deque(maxlen=window)
        self._values: Deque[float] = deque(maxlen=window)
        self._chunk_starts: Deque[float] = deque(maxlen=200)  # boundary markers
        self._base_ms: Optional[float] = None

    def push_samples(self, times_ms: list[float], values: list[float]) -> None:
        """Records received samples using their source timestamps (in ms)."""
        with self._lock:
            for i, (t_ms, value) in enumerate(zip(times_ms, values)):
                if self._base_ms is None:
                    self._base_ms = t_ms
                t_s = (t_ms - self._base_ms) / 1000.0
                if i == 0:
                    # Record the start of each incoming chunk as a boundary.
                    self._chunk_starts.append(t_s)
                self._times.append(t_s)
                self._values.append(value)

    def snapshot(self) -> tuple[list[float], list[float]]:
        """Returns a copy of the current (times, values) window for plotting."""
        with self._lock:
            return list(self._times), list(self._values)

    def chunk_boundaries(self) -> list[float]:
        """Returns the chart-relative start times (s) of each received chunk."""
        with self._lock:
            return list(self._chunk_starts)

    def reset(self) -> None:
        """Clears the chart window and restarts the time axis at zero."""
        with self._lock:
            self._times.clear()
            self._values.clear()
            self._chunk_starts.clear()
            self._base_ms = None


# ==========================================
# ACTUATOR CORE (buffer + playback logic)
# ==========================================
class VoltageActuator:
    """Buffers incoming samples and plays them back on a timed thread.

    Direct port of the C# ``VoltageActuatorClient`` playback/cache handling.
    """

    def __init__(self, sink: ChartSink) -> None:
        self._sink = sink
        self._queue: Deque[float] = deque()
        self._queue_lock = threading.Lock()
        self._playback_interval_ms = DEFAULT_PLAYBACK_INTERVAL_MS
        self._current_voltage = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._playback_loop, name="PlaybackLoop", daemon=True
        )

    def start(self) -> None:
        """Starts the playback consumer thread."""
        self._thread.start()

    def stop(self) -> None:
        """Signals the playback thread to stop."""
        self._stop.set()

    # --- playback (consumer) -------------------------------------------
    def _playback_loop(self) -> None:
        """Dequeues buffered samples and applies them at the current interval."""
        logger.info("🎬 Playback thread started.")
        while not self._stop.is_set():
            has_data = False
            next_value = 0.0

            # Hold the lock only briefly so the network thread is never blocked.
            with self._queue_lock:
                if self._queue:
                    next_value = self._queue.popleft()
                    has_data = True

            if has_data:
                self._set_voltage(next_value)
                # Timed wait between samples.
                time.sleep(self._playback_interval_ms / 1000.0)
            else:
                # Buffer empty: hold the current voltage and poll again shortly.
                time.sleep(0.01)

    def _set_voltage(self, value: float) -> None:
        """Records the latest applied sample (monitor mode: no range clamping).

        The client is a general signal sink, so values pass through unclamped;
        the chart auto-scales to whatever amplitude arrives.
        """
        # Skip redundant updates (saves work), matching the C# behaviour.
        if abs(self._current_voltage - value) < 1e-9:
            return
        self._current_voltage = value
        logger.debug("Applied value: %.4g", value)

    # --- command parsing (producer) ------------------------------------
    def handle_command(self, command: dict[str, Any]) -> None:
        """Parses an ``execute_command`` payload and buffers its samples.

        Accepts the same shapes as the C# actuator:
        * ``{"values": [...], "startTime": t0, "endTime": t1}`` – array + timing
        * ``{"value": x}`` – single scalar sample
        * an optional ``interval_ms`` overrides the playback interval directly
        """
        payload = command.get("payload", command) or {}

        # 1. Explicit interval override (fallback timing source).
        interval = _to_float(payload.get("interval_ms"))
        if interval is not None and interval >= 1:
            self._playback_interval_ms = int(interval)

        # 2. Optional timestamps for automatic timing (normalized to ms).
        start_ms = _to_ms(_to_float(payload.get("startTime")))
        end_ms = _to_ms(_to_float(payload.get("endTime")))

        # 3. Array of samples?
        values = payload.get("values")
        if isinstance(values, (list, tuple)) and values:
            samples: list[float] = []
            with self._queue_lock:
                if len(self._queue) > QUEUE_OVERFLOW_LIMIT:
                    self._queue.clear()
                for raw in values:
                    val = _to_float(raw)
                    if val is not None:
                        self._queue.append(val)
                        samples.append(val)

            count = len(samples)
            # 4. Derive the send interval from the timestamps when possible.
            #    Units are already normalized to ms, so this holds for any
            #    sample density (including kHz streams).
            if start_ms is not None and end_ms is not None and count > 0:
                diff = end_ms - start_ms
                if diff > 0:
                    self._playback_interval_ms = max(1, int(diff / count))
                    logger.debug(
                        "Auto-timing: %d samples in %dms -> interval %dms",
                        count,
                        int(diff),
                        self._playback_interval_ms,
                    )

            # Feed the debug chart with the received samples at their source
            # timestamps, so the true waveform is visible.
            self._chart_samples(samples, start_ms, end_ms)
            return

        # 5. Fallback: a single scalar value.
        scalar = _to_float(payload.get("value"))
        if scalar is not None:
            with self._queue_lock:
                self._queue.append(scalar)
            self._sink.push_samples([time.time() * 1000.0], [scalar])

    def _chart_samples(
        self,
        samples: list[float],
        start_ms: Optional[float],
        end_ms: Optional[float],
    ) -> None:
        """Reconstructs per-sample source timestamps (ms) and feeds the chart."""
        count = len(samples)
        if count == 0:
            return
        if start_ms is not None and end_ms is not None and end_ms > start_ms:
            span = end_ms - start_ms
            step = span / (count - 1) if count > 1 else 0.0
            times_ms = [start_ms + i * step for i in range(count)]
        else:
            base = time.time() * 1000.0
            times_ms = [base + i for i in range(count)]
        self._sink.push_samples(times_ms, samples)


def _to_float(raw: Any) -> Optional[float]:
    """Best-effort numeric coercion; returns None when the value is not numeric."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None


def _to_ms(value: Optional[float]) -> Optional[float]:
    """Normalizes a timestamp to milliseconds via magnitude detection.

    Epoch milliseconds are ~1e12 while epoch seconds are ~1e9; values below the
    threshold are treated as seconds and scaled up. Magnitude-based detection is
    independent of sample density, so high-rate (kHz) streams are not
    misinterpreted the way a span/count heuristic would.
    """
    if value is None:
        return None
    return value * 1000.0 if abs(value) < 1e11 else value


# ==========================================
# DISCOVERY
# ==========================================
def discover_server(max_attempts: int = 5) -> Optional[str]:
    """Finds the dispatcher with short timeouts and retry logic."""
    return discover_dispatcher(
        UDP_PORT, logger, max_attempts=max_attempts, timeout_sec=2.0
    )


# ==========================================
# MAIN
# ==========================================
def main() -> None:
    """Entry point: connects, registers, and runs the live debug chart."""
    parser = argparse.ArgumentParser(description="E-Lab Python voltage actuator client")
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="Disable the matplotlib debug chart (headless logging only).",
    )
    args = parser.parse_args()

    server_url = discover_server()
    if not server_url:
        logger.error("❌ No dispatcher found via UDP discovery.")
        sys.exit(1)

    manifest = build_manifest()
    sink = ChartSink()
    actuator = VoltageActuator(sink)
    actuator.start()

    sio: Any = socketio.Client()
    auth = ProviderAuth(device_id=PROVIDER_ID)
    auth.bind(sio)

    @sio.event
    def connect():  # pylint: disable=unused-variable
        logger.info("✅ Connected to dispatcher!")
        auth.send_register(sio, manifest)

    @sio.event
    def disconnect():  # pylint: disable=unused-variable
        logger.warning("⚠️ Connection interrupted.")

    @sio.event
    def execute_command(data):  # pylint: disable=unused-variable
        target_id = data.get("provider_id", "").replace("prov_", "")
        if target_id and target_id not in (PROVIDER_ID, TASK_ID):
            return
        command = data.get("command", {})
        actuator.handle_command(command)

    def shutdown_handler(_signum, _frame):
        """Stops the actuator and disconnects cleanly."""
        logger.info("🛑 Client shutting down...")
        actuator.stop()
        if sio.connected:
            sio.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        sio.connect(server_url)
    except socketio.exceptions.ConnectionError as exc:  # type: ignore[attr-defined] # pylint: disable=no-member
        logger.error("❌ Could not connect: %s", exc)
        sys.exit(1)

    if args.no_chart:
        logger.info("Running headless (no chart). Press Ctrl+C to stop.")
        while True:
            time.sleep(1)

    run_chart(sink)


def _add_buttons(fig, sink, pause_state: list, button_cls) -> tuple:
    """Creates Pause and Reset buttons; returns references to keep them alive."""
    pause_ax = fig.add_axes((0.63, 0.03, 0.15, 0.07))
    pause_btn = button_cls(pause_ax, "Pause")

    def on_pause(_evt):
        pause_state[0] = not pause_state[0]
        pause_btn.label.set_text("Resume" if pause_state[0] else "Pause")
        fig.canvas.draw_idle()

    pause_btn.on_clicked(on_pause)

    reset_ax = fig.add_axes((0.81, 0.03, 0.15, 0.07))
    reset_btn = button_cls(reset_ax, "Reset")
    reset_btn.on_clicked(lambda _evt: sink.reset())
    return pause_btn, reset_btn


def run_chart(sink: ChartSink) -> None:
    """Runs the live matplotlib debug chart on the main thread."""
    try:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
        from matplotlib.widgets import Button as MplButton
    except ImportError:
        logger.warning(
            "matplotlib not installed – falling back to headless mode. "
            "Install it with 'pip install matplotlib' to see the debug chart."
        )
        while True:
            time.sleep(1)

    fig, ax = plt.subplots()
    fig.subplots_adjust(bottom=0.18)
    (line,) = ax.plot([], [], color="#22c55e", lw=1.5)
    ax.set_title("Signal Monitor – received samples (debug)")
    ax.set_xlabel("Source time [s]")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)

    paused: list = [False]  # mutable container so the closure can mutate it
    _vline_artists: list = []

    def update(_frame):
        nonlocal _vline_artists
        if paused[0]:
            return (line, *_vline_artists)

        times, values = sink.snapshot()
        boundaries = sink.chunk_boundaries()

        line.set_data(times, values)
        if times:
            lo, hi = times[0], times[-1]
            ax.set_xlim(lo, hi if hi > lo else lo + 1)
        if values:
            # Auto-scale the Y-axis so any amplitude (mV, V, kHz counts, …) fits.
            vmin, vmax = min(values), max(values)
            if vmax - vmin < 1e-9:
                pad = abs(vmax) * 0.1 or 1.0
            else:
                pad = (vmax - vmin) * 0.1
            ax.set_ylim(vmin - pad, vmax + pad)

        # Redraw chunk-boundary markers (dashed vertical lines).
        for vl in _vline_artists:
            vl.remove()
        _vline_artists = []
        if times:
            lo, hi = times[0], times[-1]
            for bx in boundaries:
                if lo <= bx <= hi:
                    vl = ax.axvline(
                        x=bx, color="#475569", lw=0.7, linestyle="--", alpha=0.7
                    )
                    _vline_artists.append(vl)

        return (line, *_vline_artists)

    # Pause / Resume and Reset buttons.
    pause_btn, reset_btn = _add_buttons(fig, sink, paused, MplButton)

    # Keep references so the animation and buttons are not garbage-collected.
    _anim = FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    _keep_alive = (_anim, pause_btn, reset_btn)
    logger.info("📈 Live debug chart opened. Close the window to exit.")
    plt.show()


if __name__ == "__main__":
    main()
