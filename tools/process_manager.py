#!/usr/bin/env python3
"""
Process Manager: A system to manage, schedule, and monitor Python scripts
via a web interface.
"""

import http.server
import socketserver
import os
import sys
import subprocess
import time
import shutil
import shlex
import json
import html
import threading
import email
import zipfile
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

# --- KONFIGURATION ---
PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "scripts")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archives")
SHARED_DIR = os.path.join(
    UPLOAD_DIR, "shared"
)  # <--- Shared ist nun IM scripts-Ordner!
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATE_FILE = os.path.join(BASE_DIR, "process_state.json")
SERVER_LOG_FILE = os.path.join(LOG_DIR, "server.log")

# --- GLOBALE DATENSTRUKTUREN ---
SCRIPT_STATE = {}
ACTIVE_PROCESSES = {}

# Verzeichnisse erstellen
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "archives"), exist_ok=True)
os.makedirs(SHARED_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# --- CORE FUNCTIONS ---


def save_state():
    """Save the current script state to a JSON file."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(SCRIPT_STATE, f, indent=4)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"[ERROR] Konnte Status nicht speichern: {e}")


def load_state():
    """Load the script state from the JSON file and perform migrations if needed."""
    global SCRIPT_STATE  # pylint: disable=global-statement
    if not os.path.exists(STATE_FILE):
        SCRIPT_STATE = {}
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        migrated = False
        for conf in data.values():
            if "scheduler" not in conf:
                was_running = conf.get("running", False)
                conf["scheduler"] = {
                    "active": was_running,
                    "type": "startup",
                    "time": "00:00",
                    "day": 1,
                }
                conf.pop("running", None)
                migrated = True
            if "last_run" not in conf:
                conf["last_run"] = 0

        SCRIPT_STATE = data
        if migrated:
            print("[INIT] Konfiguration migriert.")
            save_state()
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"[ERROR] Konnte Status nicht laden: {e}")
        SCRIPT_STATE = {}


def sync_files_with_state():
    """Synchronize the internal state with the actual folders in the scripts directory."""
    if not os.path.exists(UPLOAD_DIR):
        return

    # Suche nach Ordnern im UPLOAD_DIR (ignoriere den "shared"-Ordner)
    physical_folders = set()
    for entry in os.listdir(UPLOAD_DIR):
        full_path = os.path.join(UPLOAD_DIR, entry)
        if os.path.isdir(full_path) and entry.lower() != "shared":
            physical_folders.add(entry)

    known_folders = set(SCRIPT_STATE.keys())

    # Neue Projekte hinzufügen
    for f in physical_folders:
        if f not in known_folders:
            SCRIPT_STATE[f] = {
                "args": [],
                "scheduler": {
                    "active": True,
                    "type": "startup",
                    "time": "00:00",
                    "day": 1,
                },
                "last_run": 0,
                "added_at": time.time(),
            }
            save_state()

    # Gelöschte Projekte entfernen
    for f in known_folders:
        if f not in physical_folders:
            del SCRIPT_STATE[f]
            if f in ACTIVE_PROCESSES:
                _kill_process(f)
            save_state()


def get_entry_point(folder_name):
    """Sucht die auszuführende .py Datei im Projektordner."""
    folder_path = os.path.join(UPLOAD_DIR, folder_name)
    if not os.path.isdir(folder_path):
        return None

    # Intelligente Suche: Priorisierte Dateinamen
    candidates = [
        f"{folder_name}.py",
        f"{folder_name.lower()}.py",
        f"{folder_name.replace(' ', '_')}.py",
        f"{folder_name.replace(' ', '').lower()}.py",
        "main.py",
        "app.py",
        "server.py",
        "run.py",
    ]

    for c in candidates:
        p = os.path.join(folder_path, c)
        if os.path.isfile(p):
            return p

    # Fallback: Einfach die erste .py Datei im Ordner nehmen
    for f in os.listdir(folder_path):
        if f.endswith(".py"):
            return os.path.join(folder_path, f)

    return None


def _param_to_text(value):
    """Normalize email parameter values to plain text."""
    if isinstance(value, tuple):
        return str(value[-1]) if value else ""
    if value is None:
        return ""
    return str(value)


def _payload_to_bytes(value):
    """Normalize email payload values to bytes for file operations."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if value is None:
        return b""
    return str(value).encode("utf-8")


def _kill_process(folder_name):
    """Terminate a running process for the given project folder."""
    if folder_name in ACTIVE_PROCESSES:
        proc = ACTIVE_PROCESSES[folder_name]
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:  # pylint: disable=broad-exception-caught
            proc.kill()
        del ACTIVE_PROCESSES[folder_name]


def start_process(folder_name, manual=False):
    """Start a Python script from a project folder."""
    if folder_name not in SCRIPT_STATE:
        return False
    if folder_name in ACTIVE_PROCESSES:
        if ACTIVE_PROCESSES[folder_name].poll() is None:
            return True

    args = SCRIPT_STATE[folder_name].get("args", [])
    folder_path = os.path.join(UPLOAD_DIR, folder_name)

    entry_file = get_entry_point(folder_name)

    if not entry_file:
        print(
            f"[ERROR] Keine ausfuehrbare Python-Datei im Projekt '{folder_name}' gefunden."
        )
        return False

    try:
        logfile_path = os.path.join(LOG_DIR, f"{folder_name}.log")
        logfile = open(logfile_path, "a", buffering=1, encoding="utf-8")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trigger_type = "MANUELL" if manual else "SCHEDULER"
        logfile.write(f"\n[{timestamp}] --- START ({trigger_type}) ---\n")
        logfile.flush()
        os.fsync(logfile.fileno())

        cmd = [sys.executable, "-u", entry_file] + args

        # cwd=folder_path ist extrem wichtig, damit das Skript seine lokalen Ressourcen findet!
        proc = subprocess.Popen(
            cmd,
            stdout=logfile,
            stderr=logfile,
            cwd=folder_path,
            close_fds=(os.name != "nt"),
        )
        ACTIVE_PROCESSES[folder_name] = proc
        SCRIPT_STATE[folder_name]["last_run"] = time.time()
        save_state()
        print(
            f"[INFO] Projekt gestartet: {folder_name} (PID: {proc.pid}, File: {os.path.basename(entry_file)})"
        )
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"[ERROR] Startfehler bei {folder_name}: {e}")
        return False


def stop_process_instance(folder_name):
    """Stop a running process instance and log the event."""
    if folder_name in ACTIVE_PROCESSES:
        _kill_process(folder_name)
        try:
            log_path = os.path.join(LOG_DIR, f"{folder_name}.log")
            if os.path.exists(log_path):
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- GESTOPPT ---\n"
                    )
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    return True


def scheduler_loop():
    """Main loop for the process scheduler, checking and starting scripts based on their configuration."""
    while True:
        try:
            now = datetime.now()
            current_ts = time.time()
            for folder_name, conf in list(SCRIPT_STATE.items()):
                sched = conf.get("scheduler", {})
                if not sched.get("active", False):
                    continue
                if (
                    folder_name in ACTIVE_PROCESSES
                    and ACTIVE_PROCESSES[folder_name].poll() is None
                ):
                    continue

                sched_type = sched.get("type", "startup")
                last_run = conf.get("last_run", 0)
                last_run_dt = datetime.fromtimestamp(last_run)
                should_run = False

                if sched_type == "hourly" and current_ts - last_run >= 3600:
                    should_run = True
                elif sched_type == "daily" and last_run_dt.date() < now.date():
                    t_h, t_m = map(int, sched.get("time", "00:00").split(":"))
                    if now.hour > t_h or (now.hour == t_h and now.minute >= t_m):
                        should_run = True
                elif (
                    sched_type == "weekly"
                    and now.weekday() == int(sched.get("day", 0))
                    and last_run_dt.date() < now.date()
                ):
                    t_h, t_m = map(int, sched.get("time", "00:00").split(":"))
                    if now.hour > t_h or (now.hour == t_h and now.minute >= t_m):
                        should_run = True
                elif (
                    sched_type == "monthly"
                    and now.day == int(sched.get("day", 1))
                    and last_run_dt.date() < now.date()
                ):
                    t_h, t_m = map(int, sched.get("time", "00:00").split(":"))
                    if now.hour > t_h or (now.hour == t_h and now.minute >= t_m):
                        should_run = True

                if should_run:
                    print(f"[SCHEDULER] Trigger: {folder_name}")
                    start_process(folder_name, manual=False)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"[SCHEDULER ERROR] {e}")
        time.sleep(30)


def check_zombies():
    """Clean up processes that have terminated."""
    dead = []
    for fname, proc in ACTIVE_PROCESSES.items():
        if proc.poll() is not None:
            dead.append(fname)
    for fname in dead:
        del ACTIVE_PROCESSES[fname]


def read_log_tail(folder_name, lines=200):
    """Read the last N lines of a log file."""
    log_path = (
        SERVER_LOG_FILE
        if folder_name == "__server_log__"
        else os.path.join(LOG_DIR, f"{folder_name}.log")
    )
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-lines:])
        except Exception as e:  # pylint: disable=broad-exception-caught
            return f"Fehler: {e}"
    return "Logdatei noch nicht erstellt."


def read_script_content(folder_name):
    """Read the content of the entry point script for a given project."""
    entry_file = get_entry_point(folder_name)
    if entry_file and os.path.exists(entry_file):
        try:
            with open(entry_file, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:  # pylint: disable=broad-exception-caught
            return "# Fehler beim Lesen"
    return "# Keine bearbeitbare .py Datei im Projekt gefunden"


def write_script_content(folder_name, content):
    """Write new content to the entry point script of a project."""
    entry_file = get_entry_point(folder_name)
    if entry_file:
        try:
            with open(entry_file, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False
    return False


def safe_extract_zip(zip_path, target_dir):
    """Extract a ZIP file safely, handling both forward and backward slashes,
    and preventing path traversal attacks.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            # Replace backslashes with forward slashes in path
            member_path = member.filename.replace('\\', '/')
            
            # Guard against path traversal
            if member_path.startswith('/') or '..' in member_path.split('/'):
                continue
            
            target_path = os.path.abspath(os.path.join(target_dir, member_path))
            if not target_path.startswith(os.path.abspath(target_dir) + os.path.sep):
                continue
            
            if member.is_dir() or member_path.endswith('/'):
                os.makedirs(target_path, exist_ok=True)
            else:
                # Ensure parent directory exists
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with zf.open(member) as source, open(target_path, "wb") as target:
                    shutil.copyfileobj(source, target)


# --- HTML TEMPLATES ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .sched-active { background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }
        .sched-inactive { background-color: #f3f4f6; color: #6b7280; border: 1px solid #e5e7eb; }
        .proc-running { color: #16a34a; font-weight: bold; animation: pulse 2s infinite; }
        .proc-stopped { color: #9ca3af; }
        @keyframes pulse { 0%% { opacity: 1; } 50%% { opacity: 0.6; } 100%% { opacity: 1; } }
    </style>
    <script>
        function sendAction(action, folder_name, confirmMsg) {
            if (confirmMsg && !confirm(confirmMsg)) return;
            
            const formData = new FormData();
            formData.append('filename', folder_name); // Parametername aus Kompatibilität beibehalten
            
            fetch(action, { method: 'POST', body: new URLSearchParams(formData) })
            .then(() => {
                updateAll();
            });
        }

        function updateAll() {
            const activeEl = document.activeElement;
            const isInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'SELECT');
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('active-count').innerText = data.count;
                    if (!isInput) {
                        document.getElementById('script-table-body').innerHTML = data.table;
                        document.getElementById('shared-list').innerHTML = data.shared;
                    }
                });
        }
        setInterval(updateAll, 3000);

        function saveConfig(event, folder_name) {
            event.preventDefault();
            const form = event.target.closest('form');
            fetch('/save_config', { method: 'POST', body: new URLSearchParams(new FormData(form)) })
            .then(() => {
                const btn = form.querySelector('.save-btn');
                btn.innerText = "✓";
                setTimeout(() => { btn.innerText = "💾"; }, 1000);
            });
        }

        function handleTypeChange(select) {
            const row = select.closest('tr');
            const v = select.value;
            row.querySelector('.input-time').style.display = (v === 'startup' || v === 'hourly') ? 'none' : 'inline-block';
            row.querySelector('.input-day').style.display = (v === 'startup' || v === 'hourly' || v === 'daily') ? 'none' : 'inline-block';
        }
    </script>
</head>
<body class="bg-gray-100 min-h-screen p-4 font-sans text-slate-800">
    <div class="max-w-7xl mx-auto space-y-6">
        <div class="bg-slate-900 p-6 flex justify-between items-center text-white rounded-xl shadow-lg flex-wrap gap-4">
            <div>
                <h1 class="text-2xl font-bold tracking-tight">System Manager</h1>
                <p class="text-slate-400 text-xs mt-1">Host: %s | Port: %s</p>
            </div>
            <div class="flex gap-4 items-center">
                <a href="/log?filename=__server_log__" target="_blank" class="text-slate-300 hover:text-white text-xs border border-slate-600 px-3 py-1 rounded transition hover:bg-slate-800 flex items-center gap-1">
                    Server Log
                </a>
                <div class="text-right border-l border-slate-700 pl-4">
                    <span class="block text-slate-400 text-xs">Aktive Prozesse</span>
                    <span id="active-count" class="font-bold text-green-400 text-lg">%d</span>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Scripts Section -->
            <div class="lg:col-span-2 bg-white shadow-md rounded-xl p-6">
                <div class="flex flex-wrap justify-between items-center mb-4 gap-2">
                    <h2 class="text-lg font-bold">Python Projekte</h2>
                    <form action="/upload" method="post" enctype="multipart/form-data" class="flex gap-2 flex-wrap">
                        <input type="file" name="file" accept=".py" required class="text-xs border rounded p-1" title="Lädt das Skript in einen neuen Ordner hoch">
                        <button type="submit" class="bg-blue-600 text-white text-xs px-3 py-1 rounded hover:bg-blue-700">+ Neues Projekt</button>
                    </form>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs min-w-[600px]">
                        <thead class="bg-gray-50 text-gray-500 uppercase">
                            <tr>
                                <th class="p-3 border-b w-1/4">Projekt / Log</th>
                                <th class="p-3 border-b w-1/6">Status</th>
                                <th class="p-3 border-b w-1/3">Konfiguration</th>
                                <th class="p-3 border-b text-right">Aktion</th>
                            </tr>
                        </thead>
                        <tbody id="script-table-body" class="divide-y divide-gray-100">%s</tbody>
                    </table>
                </div>
            </div>

            <!-- Shared Section -->
            <div class="bg-white shadow-md rounded-xl p-6 h-fit">
                <div class="flex justify-between items-center mb-4 flex-wrap gap-2">
                    <h2 class="text-lg font-bold">Shared Folder</h2>
                    <form action="/upload_shared" method="post" enctype="multipart/form-data" class="flex flex-col gap-2 w-full">
                        <div class="flex gap-2">
                             <input type="file" name="file" required class="text-xs border rounded p-1 flex-grow min-w-0">
                             <button type="submit" class="bg-emerald-600 text-white text-xs px-3 py-1 rounded hover:bg-emerald-700">Upload</button>
                        </div>
                    </form>
                </div>
                <div id="shared-list" class="space-y-2 max-h-96 overflow-y-auto pr-2">%s</div>
            </div>
        </div>
    </div>
</body>
</html>
"""

EDITOR_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Editor: %s</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        function selectAll() { document.getElementById('code').select(); }
        function clearText() { if(confirm('Alles löschen?')) document.getElementById('code').value = ''; }
        function copyText() {
            const el = document.getElementById('code');
            el.select();
            navigator.clipboard.writeText(el.value).then(() => alert('Kopiert!'));
        }
        async function pasteText() {
            try {
                const text = await navigator.clipboard.readText();
                const el = document.getElementById('code');
                const start = el.selectionStart;
                const end = el.selectionEnd;
                el.value = el.value.substring(0, start) + text + el.value.substring(end);
            } catch(e) {
                alert('Bitte nutzen Sie STRG+V zum Einfügen.');
            }
        }
    </script>
</head>
<body class="bg-gray-900 h-screen flex flex-col p-4 text-white">
    <div class="flex justify-between items-center mb-2">
        <h1 class="font-bold font-mono text-lg">Edit Projekt: %s</h1>
        <div class="flex gap-2">
            <button onclick="selectAll()" class="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded text-xs">All</button>
            <button onclick="clearText()" class="bg-red-900 hover:bg-red-700 px-3 py-1 rounded text-xs">Clear</button>
            <button onclick="copyText()" class="bg-blue-900 hover:bg-blue-700 px-3 py-1 rounded text-xs">Copy</button>
            <button onclick="pasteText()" class="bg-green-900 hover:bg-green-700 px-3 py-1 rounded text-xs">Paste</button>
        </div>
    </div>
    <form action="/save_script" method="post" class="flex-1 flex flex-col">
        <input type="hidden" name="filename" value="%s">
        <textarea id="code" name="content" class="flex-1 bg-gray-800 border border-gray-700 p-4 font-mono text-sm leading-relaxed outline-none text-gray-300 resize-none">%s</textarea>
        <div class="flex justify-end gap-3 mt-3">
            <a href="/" class="bg-gray-600 hover:bg-gray-500 px-6 py-2 rounded text-sm font-bold no-underline">Abbrechen</a>
            <button type="submit" class="bg-blue-600 hover:bg-blue-500 px-6 py-2 rounded text-sm font-bold">Speichern</button>
        </div>
    </form>
</body>
</html>
"""

LOG_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Log: %s</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        function hasSelection() {
            const sel = window.getSelection();
            return sel.toString().length > 0;
        }

        function fetchLog() {
            if (hasSelection()) return; 

            const f = "%s";
            fetch('/api/log?filename=' + f)
            .then(r => r.text())
            .then(t => {
                const d = document.getElementById('c');
                const isAtBottom = (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 50;
                
                d.innerText = t;
                
                if (isAtBottom) {
                    window.scrollTo(0, document.body.scrollHeight);
                }
            })
            .catch(e => console.error(e));
        }

        function copyToClipboard() {
            const text = document.getElementById('c').innerText;
            navigator.clipboard.writeText(text).then(() => {
                const btn = document.getElementById('copyBtn');
                const originalText = btn.innerText;
                btn.innerText = "Kopiert!";
                btn.classList.replace('bg-blue-700', 'bg-green-600');
                setTimeout(() => {
                    btn.innerText = originalText;
                    btn.classList.replace('bg-green-600', 'bg-blue-700');
                }, 1500);
            });
        }

        window.onload = function() {
            window.scrollTo(0, document.body.scrollHeight);
            setInterval(fetchLog, 2000);
        };
    </script>
</head>
<body class="bg-gray-900 text-gray-300 p-4 font-mono text-sm h-screen flex flex-col">
    <div class="flex justify-between items-center mb-4 sticky top-0 bg-gray-900 py-2 border-b border-gray-800 z-10">
        <h1 class="text-white font-bold text-xl truncate mr-4">Log: %s</h1>
        <div class="flex gap-2 shrink-0">
            <button id="copyBtn" onclick="copyToClipboard()" class="bg-blue-700 hover:bg-blue-600 text-white px-4 py-1 rounded transition">Copy</button>
            <button onclick="window.close()" class="bg-gray-700 hover:bg-gray-600 text-white px-4 py-1 rounded transition">Schließen</button>
        </div>
    </div>
    <div id="c" class="flex-1 whitespace-pre-wrap pb-10 select-text">%s</div>
</body>
</html>
"""


class ScriptManagerHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the System Manager web interface."""

    def _is_local(self):
        return self.client_address[0] in (
            "127.0.0.1",
            "::1",
            "localhost",
            "::ffff:127.0.0.1",
        )

    def _redirect(self, path="/"):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def _handle_upload(self, target_dir):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return

        if content_length > 0:
            body = self.rfile.read(content_length)
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                return

            headers = b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n"
            msg = email.message_from_bytes(headers + body)

            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue

                    cd = part.get("Content-Disposition")
                    if not cd:
                        continue

                    name = part.get_param("name", header="Content-Disposition")
                    filename = _param_to_text(
                        part.get_param("filename", header="Content-Disposition")
                    )

                    if name == "file" and filename:
                        fn = os.path.basename(filename)

                        if target_dir == UPLOAD_DIR:
                            # Erstellt einen neuen Projektordner für das hochgeladene Skript
                            if not fn.endswith(".py"):
                                fn += ".py"
                            folder_name = fn[:-3]  # ".py" entfernen für Ordnername
                            new_folder_path = os.path.join(UPLOAD_DIR, folder_name)
                            os.makedirs(new_folder_path, exist_ok=True)
                            target_path = os.path.join(new_folder_path, fn)
                        else:
                            # Upload in Shared Folder direkt speichern
                            target_path = os.path.join(target_dir, fn)

                        with open(target_path, "wb") as f:
                            payload = part.get_payload(decode=True)
                            if payload is not None:
                                # Sicherstellen, dass die Daten als bytes geschrieben werden
                                data: bytes = _payload_to_bytes(payload)
                                f.write(data)

                        if target_dir == UPLOAD_DIR:
                            sync_files_with_state()
                        return


    def _handle_api_update_upload(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self.send_error(400, "Bad Request")
            return
        body_bytes = self.rfile.read(content_length)
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Bad Request")
            return
        headers_bytes = b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n"

        msg = email.message_from_bytes(headers_bytes + body_bytes)
        version = "unknown"
        keep_userdata = "true"
        zip_payload = None
        zip_filename = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                cd = part.get("Content-Disposition")
                if not cd:
                    continue
                name = part.get_param("name", header="Content-Disposition")
                if name == "version":
                    val = part.get_payload(decode=True)
                    if val is not None:
                        version = _payload_to_bytes(val).decode(
                            "utf-8", errors="replace"
                        ).strip()
                elif name == "keep_userdata":
                    val = part.get_payload(decode=True)
                    if val is not None:
                        keep_userdata = _payload_to_bytes(val).decode(
                            "utf-8", errors="replace"
                        ).strip().lower()
                elif name == "file":
                    zip_filename = _param_to_text(
                        part.get_param("filename", header="Content-Disposition")
                    )
                    payload = part.get_payload(decode=True)
                    if payload is not None:
                        zip_payload = _payload_to_bytes(payload)
        if not zip_payload or not zip_filename:
            self.send_error(400, "No file uploaded")
            return

        match = re.match("^([A-Za-z0-9" + chr(92) + "-]+)_v", zip_filename)
        project_name = (
            match.group(1) if match else os.path.splitext(str(zip_filename))[0]
        )
        project_dir = os.path.join(UPLOAD_DIR, project_name)
        stop_process_instance(project_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = project_name + "_backup_" + timestamp + ".zip"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        if os.path.exists(project_dir):
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(project_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, project_dir)
                        zf.write(file_path, rel_path)
        keep_extensions = [".json", ".sqlite", ".db"]
        if os.path.exists(project_dir):
            for root, dirs, files in os.walk(project_dir, topdown=False):
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if keep_userdata == "true" and ext in keep_extensions:
                        continue
                    try:
                        os.remove(os.path.join(root, name))
                    except OSError:
                        pass
                for name in dirs:
                    try:
                        os.rmdir(os.path.join(root, name))
                    except OSError:
                        pass
        os.makedirs(project_dir, exist_ok=True)
        temp_zip_path = os.path.join(UPLOAD_DIR, project_name + "_temp.zip")
        with open(temp_zip_path, "wb") as f_zip:
            f_zip.write(zip_payload)

        safe_extract_zip(temp_zip_path, project_dir)
        os.remove(temp_zip_path)
        sync_files_with_state()
        start_process(project_name, manual=True)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        self.wfile.write(
            json.dumps(
                {"status": "success", "version": version, "archive": archive_name}
            ).encode()
        )

    def _gen_table(self):
        rows = ""
        for f in sorted(SCRIPT_STATE.keys()):
            conf = SCRIPT_STATE[f]
            sched = conf.get("scheduler", {})
            args_str = shlex.join(conf.get("args", []))
            is_run = f in ACTIVE_PROCESSES
            pid = str(ACTIVE_PROCESSES[f].pid) if is_run else "-"
            s_act = sched.get("active", False)
            s_type = sched.get("type", "startup")

            edit_btn = f'<a href="/edit?filename={f}" class="block text-center bg-yellow-50 text-yellow-700 border border-yellow-200 hover:bg-yellow-100 rounded py-1 text-[10px] font-bold mt-1">EDIT MAIN</a>'
            if is_run:
                edit_btn = '<span class="block text-center bg-gray-50 text-gray-300 border border-gray-100 rounded py-1 text-[10px] cursor-not-allowed mt-1">EDIT MAIN</span>'

            log_ui = ""
            if os.path.exists(os.path.join(LOG_DIR, f"{f}.log")):
                log_ui = f"""
                <div class="flex items-center gap-1 mt-0.5">
                    <a href="/log?filename={f}" target="_blank" class="text-blue-500 hover:underline text-[10px]">[LOG]</a>
                    <button onclick="sendAction('/delete_log', '{f}', 'Log wirklich leeren?')" class="text-red-300 hover:text-red-500 font-bold text-[10px] px-1" title="Log leeren">✕</button>
                </div>
                """

            row = f"""
            <tr id="row-{f.replace('.','-')}" data-status="{'run' if is_run else 'stop'}" class="border-b border-gray-50">
                <td class="p-3 align-top font-mono">
                    <div class="flex items-center gap-1 text-xs text-gray-400">📁</div>
                    <div class="font-bold truncate max-w-[150px] text-blue-900" title="{f}">{f}</div>
                    {log_ui}
                </td>
                <td class="p-3 align-top">
                    <div class="px-2 py-0.5 rounded text-[10px] {'bg-green-100 text-green-800' if s_act else 'bg-gray-100 text-gray-500'}">SCHED: {'AN' if s_act else 'AUS'}</div>
                    <div class="mt-1 {'text-green-600 font-bold' if is_run else 'text-gray-400'}">{'LÄUFT' if is_run else 'STOPP'}</div>
                    <div class="text-[10px] text-gray-400">PID: {pid}</div>
                </td>
                <td class="p-3 align-top">
                    <form onsubmit="saveConfig(event, '{f}')" class="space-y-1">
                        <input type="hidden" name="filename" value="{f}">
                        <div class="flex gap-1 flex-wrap">
                            <input type="text" name="args" value="{html.escape(args_str)}" class="border rounded p-1 text-[10px] flex-grow min-w-[80px]" placeholder="Args...">
                            <button type="submit" class="save-btn border bg-gray-50 rounded px-1 shrink-0">💾</button>
                        </div>
                        <div class="flex gap-1 items-center flex-wrap">
                            <select name="type" onchange="handleTypeChange(this)" class="border rounded text-[10px] max-w-full">
                                {"".join([f'<option value="{k}" {"selected" if k==s_type else ""}>{k}</option>' for k in ["startup","hourly","daily","weekly","monthly"]])}
                            </select>
                            <input type="time" name="time" value="{sched.get('time','00:00')}" class="input-time border rounded text-[10px]" style="display:{'none' if s_type in ['startup','hourly'] else 'block'}">
                            <input type="number" name="day" value="{sched.get('day',1)}" class="input-day border rounded text-[10px] w-8" style="display:{'none' if s_type in ['startup','hourly','daily'] else 'block'}">
                        </div>
                    </form>
                </td>
                <td class="p-3 align-top text-right space-y-1">
                    <button onclick="sendAction('/{'disable_sched' if s_act else 'enable_sched'}', '{f}')" class="w-full text-[10px] border rounded py-1 {'text-red-500' if s_act else 'text-green-600'}">{'SCHED OFF' if s_act else 'SCHED ON'}</button>
                    <button onclick="sendAction('/force_start', '{f}')" class="w-full bg-blue-600 text-white rounded text-[10px] py-1 hover:bg-blue-700">RUN</button>
                    {f'''<button onclick="sendAction('/stop_proc', '{f}', 'Prozess wirklich beenden?')" class="w-full text-red-500 text-[10px] underline mt-1 hover:text-red-700">Kill</button>''' if is_run else edit_btn}
                    <div class="mt-2 text-right">
                        <button onclick="sendAction('/delete', '{f}', 'Projekt-Ordner mitsamt Inhalt komplett löschen?')" class="text-gray-300 hover:text-red-500 text-[10px]">Ordner löschen</button>
                    </div>
                </td>
            </tr>"""
            rows += row
        return (
            rows
            if rows
            else '<tr><td colspan="4" class="p-4 text-center text-gray-400">Keine Projekte in /scripts gefunden.</td></tr>'
        )

    def _gen_shared(self):
        files = os.listdir(SHARED_DIR)
        if not files:
            return '<p class="text-xs text-gray-400 italic">Ordner leer</p>'
        html_out = ""
        for f in sorted(files):
            html_out += f"""
            <div class="flex justify-between items-center bg-gray-50 p-2 rounded border group">
                <span class="text-xs truncate font-mono pr-2" title="{f}">{f}</span>
                <button onclick="sendAction('/delete_shared', '{f}', 'Datei löschen?')" class="text-gray-300 hover:text-red-500 font-bold">✕</button>
            </div>"""
        return html_out

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET requests."""
        p = urlparse(self.path)

        if p.path.startswith("/api/update/"):
            if not self._is_local():
                self.send_error(
                    403, "Forbidden: Updates only allowed from localhost via SSH"
                )
                return

        if p.path == "/":
            check_zombies()
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                (
                    HTML_TEMPLATE
                    % (
                        sys.platform,
                        PORT,
                        len(ACTIVE_PROCESSES),
                        self._gen_table(),
                        self._gen_shared(),
                    )
                ).encode()
            )
        elif p.path == "/api/update/archives":
            archives_list = []
            if os.path.exists(ARCHIVE_DIR):
                for f_name in os.listdir(ARCHIVE_DIR):
                    if f_name.endswith(".zip"):
                        fp = os.path.join(ARCHIVE_DIR, f_name)
                        st = os.stat(fp)
                        archives_list.append(
                            {
                                "filename": f_name,
                                "size_mb": round(st.st_size / (1024 * 1024), 2),
                                "created": datetime.fromtimestamp(st.st_mtime).strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                            }
                        )
            archives_list.sort(key=lambda x: x["created"], reverse=True)
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(archives_list).encode())
            return
        elif p.path == "/api/status":
            check_zombies()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "table": self._gen_table(),
                        "shared": self._gen_shared(),
                        "count": len(ACTIVE_PROCESSES),
                    }
                ).encode()
            )
        elif p.path == "/api/log":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(
                read_log_tail(parse_qs(p.query).get("filename", [""])[0]).encode()
            )
        elif p.path == "/log":
            f = parse_qs(p.query).get("filename", [""])[0]
            d_name = "Server" if f == "__server_log__" else f
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                (
                    LOG_TEMPLATE % (d_name, f, d_name, html.escape(read_log_tail(f)))
                ).encode()
            )
        elif p.path == "/edit":
            f = parse_qs(p.query).get("filename", [""])[0]
            if f in ACTIVE_PROCESSES:
                self._redirect("/")
                return
            content = read_script_content(f)
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                (EDITOR_TEMPLATE % (f, f, f, html.escape(content))).encode()
            )
        else:
            self.send_error(404)

    def do_POST(self):  # pylint: disable=invalid-name
        """Handle POST requests."""
        p = urlparse(self.path)

        if p.path.startswith("/api/update/"):
            if not self._is_local():
                self.send_error(
                    403, "Forbidden: Updates only allowed from localhost via SSH"
                )
                return

        if p.path == "/api/update/upload":
            self._handle_api_update_upload()
            return

        if p.path == "/api/update/rollback":
            length = int(self.headers.get("Content-Length", 0))
            body_str = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                data = json.loads(body_str)
                filename = data.get("filename")
                keep_userdata = data.get("keep_userdata", True)
                archive_path = os.path.join(ARCHIVE_DIR, filename)
                if not os.path.exists(archive_path):
                    self.send_error(404, "Archive not found")
                    return
                match = re.match("^([A-Za-z0-9" + chr(92) + "-]+)_backup_", filename)
                if match:
                    project_name = match.group(1)
                else:
                    self.send_error(
                        400, "Could not determine project name from archive filename"
                    )
                    return
                project_dir = os.path.join(UPLOAD_DIR, project_name)
                stop_process_instance(project_name)
                keep_extensions = [".json", ".sqlite", ".db"]
                if os.path.exists(project_dir):
                    for root, dirs, files in os.walk(project_dir, topdown=False):
                        for name in files:
                            ext = os.path.splitext(name)[1].lower()
                            if keep_userdata and ext in keep_extensions:
                                continue
                            try:
                                os.remove(os.path.join(root, name))
                            except OSError:
                                pass
                        for name in dirs:
                            try:
                                os.rmdir(os.path.join(root, name))
                            except OSError:
                                pass
                os.makedirs(project_dir, exist_ok=True)
                safe_extract_zip(archive_path, project_dir)
                sync_files_with_state()
                start_process(project_name, manual=True)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "rollback successful"}).encode())
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.send_error(500, str(e))
            return

        # Block 1: Multipart Uploads
        if p.path in ["/upload", "/upload_shared"]:
            target_dir = UPLOAD_DIR if p.path == "/upload" else SHARED_DIR
            self._handle_upload(target_dir)
            self._redirect()
            return

        # Block 2: Standard URL-Encoded POSTs
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)
        try:
            body_str = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            body_str = body_bytes.decode("latin-1")

        params = parse_qs(body_str)

        if p.path == "/save_script":
            f = params.get("filename", [""])[0]
            c = params.get("content", [""])[0]
            if f:
                write_script_content(f, c)
            self._redirect()
            return

        f = params.get("filename", [""])[0]
        if f:
            if p.path == "/save_config":
                if f in SCRIPT_STATE:
                    SCRIPT_STATE[f]["args"] = shlex.split(params.get("args", [""])[0])
                    s = SCRIPT_STATE[f]["scheduler"]
                    s["type"] = params.get("type", ["startup"])[0]
                    s["time"] = params.get("time", ["00:00"])[0]
                    s["day"] = int(params.get("day", ["1"])[0])
                    save_state()
            elif p.path == "/force_start":
                start_process(f, True)
            elif p.path == "/stop_proc":
                stop_process_instance(f)
            elif p.path == "/enable_sched":
                if f in SCRIPT_STATE:
                    SCRIPT_STATE[f]["scheduler"]["active"] = True
                    save_state()
            elif p.path == "/disable_sched":
                if f in SCRIPT_STATE:
                    SCRIPT_STATE[f]["scheduler"]["active"] = False
                    save_state()
            elif p.path == "/delete":
                stop_process_instance(f)
                fp = os.path.join(UPLOAD_DIR, f)
                lp = os.path.join(LOG_DIR, f"{f}.log")
                if os.path.exists(fp) and os.path.isdir(fp):
                    shutil.rmtree(fp)  # Löscht den kompletten Ordner!
                if os.path.exists(lp):
                    try:
                        os.remove(lp)
                    except OSError:
                        pass
                if f in SCRIPT_STATE:
                    del SCRIPT_STATE[f]
                    save_state()
            elif p.path == "/delete_shared":
                fp = os.path.join(SHARED_DIR, f)
                if os.path.exists(fp):
                    os.remove(fp)
            elif p.path == "/delete_log":
                lp = os.path.join(LOG_DIR, f"{f}.log")
                if os.path.exists(lp):
                    try:
                        with open(lp, "w", encoding="utf-8") as tf:
                            tf.write("")
                    except OSError:
                        pass

        self.send_response(200)
        self.end_headers()


def run():
    """Start the HTTP server and initialize the process manager."""
    socketserver.TCPServer.allow_reuse_address = True
    load_state()
    sync_files_with_state()
    for f, c in SCRIPT_STATE.items():
        if (
            c.get("scheduler", {}).get("active")
            and c.get("scheduler", {}).get("type") == "startup"
        ):
            start_process(f)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    with socketserver.TCPServer(("", PORT), ScriptManagerHandler) as httpd:
        print(f"RUNNING ON PORT {PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    run()
