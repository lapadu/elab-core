"""FIR-Filter Node für E-Lab.

Registriert sich als MATH-Task mit dem Mean-Template. Die Eingangsquelle
wird dynamisch über die UI zugewiesen (Drag & Drop), nicht fest verdrahtet.
"""
import numpy as np
from scipy.signal import firwin, lfilter
from elab_api import LocalNode

# --- Konfiguration ---
OUTPUT_TASK = "fir_filtered_signal"
INITIAL_CUTOFF = 100       # Hz
INITIAL_ORDER = 51         # Anzahl Koeffizienten
SAMPLE_RATE = 10000        # Hz

# --- Filter-State ---
fir_coeffs = firwin(INITIAL_ORDER, INITIAL_CUTOFF, fs=SAMPLE_RATE)
filter_state = np.zeros(INITIAL_ORDER - 1)
filter_enabled = True


def rebuild_filter(order: int, cutoff: float, window: str = "hamming") -> None:
    """Berechnet die FIR-Koeffizienten neu."""
    global fir_coeffs, filter_state
    fir_coeffs = firwin(order, cutoff, fs=SAMPLE_RATE, window=window)
    filter_state = np.zeros(order - 1)


# --- Node Setup ---
node = LocalNode(name="FIR Lowpass Filter")

# MATH-Task mit generischem MATH-Template → Drop-Zone + dynamische Config in der UI
node.register_math_task(
    task_id=OUTPUT_TASK,
    template="tpl_generic_math",  # Generic Math-Template: Drop-Zone + configFields
    unit="V",
    color="#3b82f6",
    tags=["dsp", "filter", "fir"],
    config=[
        {
            "key": "cutoff_freq",
            "label": "Cutoff-Frequenz",
            "type": "slider",
            "value": INITIAL_CUTOFF,
            "min": 10,
            "max": SAMPLE_RATE // 2 - 1,
            "step": 10,
            "unit": "Hz",
        },
        {
            "key": "filter_order",
            "label": "Filter-Ordnung",
            "type": "number",
            "value": INITIAL_ORDER,
            "min": 5,
            "max": 255,
            "step": 2,
        },
        {
            "key": "filter_type",
            "label": "Fenster-Funktion",
            "type": "select",
            "value": "hamming",
            "options": [
                {"label": "Hamming", "value": "hamming"},
                {"label": "Hann", "value": "hann"},
                {"label": "Blackman", "value": "blackman"},
                {"label": "Rectangular", "value": "boxcar"},
            ],
        },
        {
            "key": "enabled",
            "label": "Filter aktiv",
            "type": "toggle",
            "value": True,
        },
    ],
)


# --- Callbacks ---

@node.on_input_update(OUTPUT_TASK)
def on_source_changed(source):
    """Wird aufgerufen wenn der Benutzer einen Sensor auf den Filter zieht."""
    global filter_state
    if source:
        print(f"✔ Eingangsquelle zugewiesen: {source.get('name', source.get('id'))}")
        # Reset filter state for clean start with new source
        filter_state = np.zeros(INITIAL_ORDER - 1)
    else:
        print("✖ Eingangsquelle entfernt")


@node.on_config_update(OUTPUT_TASK)
def on_config_changed(key: str, value):
    """Wird aufgerufen wenn der Benutzer einen Parameter in der UI ändert."""
    global fir_coeffs, filter_state, INITIAL_CUTOFF, INITIAL_ORDER, filter_enabled

    if key == "cutoff_freq":
        INITIAL_CUTOFF = int(value)
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF)
        print(f"✔ Cutoff geändert: {INITIAL_CUTOFF} Hz")

    elif key == "filter_order":
        INITIAL_ORDER = int(value)
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF)
        print(f"✔ Ordnung geändert: {INITIAL_ORDER} Taps")

    elif key == "filter_type":
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF, window=str(value))
        print(f"✔ Fensterfunktion geändert: {value}")

    elif key == "enabled":
        filter_enabled = bool(value)
        print(f"✔ Filter {'aktiviert' if filter_enabled else 'deaktiviert'}")


@node.on_dynamic_stream()
def process_data(source_id: str, values: list):
    """Verarbeitet Daten von der aktuell in der UI zugewiesenen Quelle."""
    global filter_state

    if not filter_enabled or not values:
        return

    data = np.array(values, dtype=np.float64)

    # FIR-Filter anwenden (mit State für nahtlose Chunk-Übergänge)
    filtered, filter_state = lfilter(fir_coeffs, 1.0, data, zi=filter_state)

    # Gefiltertes Signal publizieren → erscheint als neuer Sensor in der UI
    node.publish(OUTPUT_TASK, filtered.astype(np.float32))


# --- Start ---
if __name__ == "__main__":
    print("FIR-Filter Node gestartet")
    print(f"  Ausgang:  {OUTPUT_TASK}")
    print(f"  Cutoff:   {INITIAL_CUTOFF} Hz / Ordnung: {INITIAL_ORDER}")
    print(f"  Template: tpl_generic_math (Eingang per Drag & Drop in der UI)")
    print()
    print("  → Sensor oder Generator in der UI auf den Filter ziehen")
    node.run()
