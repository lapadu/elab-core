"""Interactive JSON log viewer with matplotlib plotting and optional file picker."""

import json
import argparse
import sys

try:
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Cursor
    _HAS_MPL = True
except ImportError:
    plt = None  # type: ignore[assignment]
    Cursor = None  # type: ignore[assignment]
    _HAS_MPL = False

try:
    import tkinter as tk
    from tkinter import filedialog as _filedialog
    _HAS_TK = True
except ImportError:
    tk = None  # type: ignore[assignment]
    _filedialog = None  # type: ignore[assignment]
    _HAS_TK = False


def plot_logs_from_obj(obj, absolute_time=False):
    """Render time-series data from a parsed log object."""
    sources = obj.get("sources", {})
    series_data = []
    for key, src in sources.items():
        name = src.get("name", key)
        pts = src.get("data", [])
        t = [p.get("t") for p in pts if p is not None and "t" in p and "v" in p]
        v = [p.get("v") for p in pts if p is not None and "t" in p and "v" in p]
        if not t:
            continue
        ts = t if absolute_time else [tt - t[0] for tt in t]
        series_data.append((name, ts, v))

    if not series_data or not _HAS_MPL:
        print("No data available or matplotlib is unavailable.")
        return

    # Both names are bound because _HAS_MPL is True at this point.
    assert plt is not None
    assert Cursor is not None

    fig, ax = plt.subplots(figsize=(10, 6))
    lines = []
    for name, ts, vs in series_data:
        x = [x/1000.0 for x in ts]
        # Use small markers to keep dense series readable.
        ln, = ax.plot(x, vs, ls='-', marker='o', markersize=3, label=name, picker=5)
        lines.append(ln)

    ax.set_xlabel('Time (s)' if not absolute_time else 'Time (s) since epoch')
    ax.set_ylabel('Value')
    ax.set_title('Log Viewer (Zoom: Lupe-Icon; Pan: Hand-Icon; Reset: Home)')
    ax.grid(True, alpha=0.3)
    ax.legend()

    # Crosshair improves point inspection while zooming and panning.
    Cursor(ax, useblit=True, color='gray', linewidth=1)

    # Clicking a point shows its nearest sampled value.
    annot = ax.annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points",
                        bbox=dict(boxstyle="round", fc="w"), arrowprops=dict(arrowstyle="->"))
    annot.set_visible(False)

    def update_annot(line):
        x, y = line.get_xdata(), line.get_ydata()
        annot.xy = (x, y)  # type: ignore[assignment]
        text = f"{line.get_label()}\n t={x:.6f}s\n v={y:.6f}"
        annot.set_text(text)
        bbox_patch = annot.get_bbox_patch()
        if bbox_patch is not None:
            bbox_patch.set_alpha(0.8)

    def on_pick(event):
        line = event.artist
        update_annot(line)
        annot.set_visible(True)
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect('pick_event', on_pick)

    # Mouse-wheel zoom anchored at the cursor position.
    base_scale = 1.2
    def zoom_fun(event):
        if event.inaxes != ax:
            return
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        xdata = event.xdata
        ydata = event.ydata
        if event.button == 'up':
            scale_factor = 1/base_scale
        elif event.button == 'down':
            scale_factor = base_scale
        else:
            return
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        relx = (cur_xlim[1] - xdata)/(cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata)/(cur_ylim[1] - cur_ylim[0])
        ax.set_xlim(xdata - new_width*(1-relx), xdata + new_width*relx)
        ax.set_ylim(ydata - new_height*(1-rely), ydata + new_height*rely)
        ax.figure.canvas.draw_idle()

    fig.canvas.mpl_connect('scroll_event', zoom_fun)

    plt.tight_layout()
    plt.show()


def open_file_dialog():
    """Open a native file picker and return `(path, error_message)` tuple."""
    if not _HAS_TK:
        return None, "tkinter unavailable"

    assert tk is not None
    assert _filedialog is not None
    try:
        root = tk.Tk()
        root.withdraw()
        root.update()
        path = _filedialog.askopenfilename(
            title="Select log file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        root.destroy()
        if not path:
            return None, "No file selected."
        return path, None
    except (OSError, RuntimeError) as e:
        return None, f"File dialog failed: {e}"


def load_json_file(path):
    """Load and parse a JSON document from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    """Parse CLI args, load selected log file, and launch the plot window."""
    parser = argparse.ArgumentParser(description="Log viewer with zoom and point inspection")
    parser.add_argument("--file", "-f", help="Path to the JSON log file")
    parser.add_argument("--absolute-time", action="store_true",
                        help="Show the time axis as seconds since epoch")
    args = parser.parse_args()

    path = args.file
    error_hint = None
    if not path:
        path, error_hint = open_file_dialog()
        if error_hint:
            print(f"Note: {error_hint}")
    if not path:
        print("Aborting: no file selected. Alternatively use --file <path>.")
        sys.exit(1)

    try:
        obj = load_json_file(path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error loading file '{path}': {e}")
        sys.exit(1)

    plot_logs_from_obj(obj, absolute_time=args.absolute_time)

if __name__ == "__main__":
    main()
