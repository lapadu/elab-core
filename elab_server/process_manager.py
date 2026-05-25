"""Manages client processes."""
import os
import glob
import re
import subprocess
import sys
import threading
import logging

logger = logging.getLogger(__name__)

# Strict filename whitelist: simple python script names only. No path
# separators, no dot-prefix, no shell metacharacters.
_SCRIPT_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.py$")

# True when running inside a PyInstaller bundle.
_FROZEN = getattr(sys, 'frozen', False)

# When frozen, pre-built client executables live next to the main binary
# in a ``client_bins/`` directory.  Each .py script has a corresponding
# .exe (Windows) or executable (Linux/Mac) with the same stem name.
_CLIENT_BINS_DIR = (
    os.path.join(os.path.dirname(sys.executable), 'client_bins')
    if _FROZEN else None
)

class ClientProcessManager:
    """A class to manage client processes."""
    def __init__(self, clients_dir=os.path.join("elab_clients_core", "python", "clients")):
        # In a PyInstaller bundle, data files live under sys._MEIPASS/_internal.
        # The .spec adds elab_clients_core/ there. In dev mode, the client library
        # loads runnable scripts from elab_clients_core/python/clients.
        if _FROZEN:
            base = os.path.join(getattr(sys, '_MEIPASS', ''), clients_dir)
        else:
            base = os.path.join(os.path.dirname(
                os.path.abspath(__file__)), "..", clients_dir)
        self.clients_dir = os.path.abspath(base)
        self._python = sys.executable  # used in dev mode only
        logger.info("ClientProcessManager: clients_dir=%s  frozen=%s",
                    self.clients_dir, _FROZEN)
        if _FROZEN and _CLIENT_BINS_DIR:
            logger.info("ClientProcessManager: client_bins=%s", _CLIENT_BINS_DIR)
        self.running_processes = {}
        self._stop = threading.Event()
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_zombies, daemon=True)
        self.cleanup_thread.start()

    def _cleanup_zombies(self):
        """Cleans up zombie processes."""
        while not self._stop.is_set():
            if self._stop.wait(5):
                return
            to_remove = []
            for filename, proc in list(self.running_processes.items()):
                if proc.poll() is not None:
                    to_remove.append(filename)
            for filename in to_remove:
                logger.warning("Zombie process detected: %s", filename)
                del self.running_processes[filename]

    def scan_scripts(self):
        """Scans the clients directory for Python scripts.

        In frozen (PyInstaller) mode, only scripts that have a matching
        pre-built executable in ``client_bins/`` are reported as runnable.
        """
        scripts = []
        if not os.path.exists(self.clients_dir):
            logger.warning("Client directory not found: %s", self.clients_dir)
            return scripts
        files = glob.glob(os.path.join(self.clients_dir, "*.py"))
        for file_path in files:
            filename = os.path.basename(file_path)
            if filename.startswith("__") or "asset" in filename.lower():
                continue
            # In frozen mode, skip scripts without a pre-built binary.
            if _FROZEN and not self._client_exe(filename):
                logger.debug("Skipping %s – no pre-built binary found", filename)
                continue
            scripts.append({
                "id": f"script_{filename}",
                "name": filename,
                "filename": filename,
                "isRunning": filename in self.running_processes,
            })
        return scripts

    @staticmethod
    def _client_exe(script_filename: str) -> str | None:
        """Return the path to the pre-built exe for *script_filename*, or None."""
        if not _CLIENT_BINS_DIR:
            return None
        stem = os.path.splitext(script_filename)[0]
        ext = '.exe' if sys.platform == 'win32' else ''
        candidate = os.path.join(_CLIENT_BINS_DIR, stem + ext)
        return candidate if os.path.isfile(candidate) else None

    def _log_output(self, stream, filename):
        """Reads and logs output from a stream, parsing the log level."""
        log_level_mapping = {
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'DEBUG': logging.DEBUG,
        }
        try:
            for line in iter(stream.readline, b''):
                try:
                    log_line = line.decode('utf-8', errors='replace').rstrip()
                except (UnicodeDecodeError, AttributeError):
                    continue
                if not log_line:
                    continue

                match = re.search(r'\[(INFO|WARNING|ERROR|DEBUG)\]', log_line)

                level = logging.INFO  # Default to INFO
                if match:
                    level = log_level_mapping.get(match.group(1), logging.INFO)

                logger.log(level, "[%s] %s", filename, log_line)
        except (OSError, ValueError) as e:
            # Pipe closed unexpectedly (process killed); exit cleanly.
            logger.debug("Log stream for %s closed: %s", filename, e)
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _resolve_script_path(self, filename: str):
        """Validate *filename* and return its absolute path inside clients_dir.

        Returns (path, error). On rejection ``path`` is None and ``error`` is
        a short human-readable message.
        """
        if not isinstance(filename, str) or not _SCRIPT_FILENAME_RE.match(filename):
            return None, "Invalid script filename"
        clients_root = os.path.realpath(self.clients_dir)
        candidate = os.path.realpath(os.path.join(clients_root, filename))
        # Containment check: candidate must be a direct child of clients_root.
        try:
            common = os.path.commonpath([clients_root, candidate])
        except ValueError:
            return None, "Path traversal blocked"
        if common != clients_root or os.path.dirname(candidate) != clients_root:
            logger.warning(
                "Rejected script path outside clients_dir: %s -> %s",
                filename, candidate,
            )
            return None, "Path traversal blocked"
        if not os.path.isfile(candidate):
            return None, "Script not found"
        return candidate, None

    def start_script(self, filename):
        """Starts a client script."""
        if filename in self.running_processes and self.running_processes[filename].poll() is None:
            return False, "Already running"
        filepath, err = self._resolve_script_path(filename)
        if err:
            logger.warning("start_script rejected %r: %s", filename, err)
            return False, err
        try:
            # pylint: disable=consider-using-with
            assert filepath is not None  # guaranteed by _resolve_script_path
            env = os.environ.copy()
            if _FROZEN:
                client_exe = self._client_exe(filename)
                if not client_exe:
                    return False, "No pre-built binary for this script"
                cmd = [client_exe]
                cwd = os.path.dirname(client_exe)
            else:
                cmd = [self._python, filepath]
                cwd = self.clients_dir
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=False  # Ensure stdout/stderr are bytes
            )
            self.running_processes[filename] = proc

            # Start logging threads
            stdout_thread = threading.Thread(
                target=self._log_output,
                args=(proc.stdout, filename),
                daemon=True
            )
            stderr_thread = threading.Thread(
                target=self._log_output,
                args=(proc.stderr, filename),
                daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()

            logger.info("Started script: %s (PID:%d)", filename, proc.pid)
            return True, f"Started (PID:{proc.pid})"
        except OSError as e:
            logger.error("Failed to start %s: %s", filename, e)
            return False, str(e)


    def stop_script(self, filename):
        """Stops a client script."""
        if filename not in self.running_processes:
            return False, "Not running"
        proc = self.running_processes[filename]
        try:
            proc.terminate()
            logger.debug("Sent SIGTERM to %s", filename)
            try:
                proc.wait(timeout=5)
                logger.info("Process %s terminated gracefully", filename)
            except subprocess.TimeoutExpired:
                logger.warning("Process %s did not terminate, sending SIGKILL", filename)
                proc.kill()
                proc.wait(timeout=2)
                logger.warning("Process %s killed forcefully", filename)
            del self.running_processes[filename]
            return True, "Stopped"
        except OSError as e:
            logger.error("Error stopping %s: %s", filename, e)
            if filename in self.running_processes:
                del self.running_processes[filename]
            return False, f"Error:{str(e)}"

    def shutdown(self) -> None:
        """Terminate the cleanup thread and all running client processes.

        Safe to call multiple times. Used during graceful server shutdown so
        no Python child process is left dangling.
        """
        self._stop.set()
        for filename in list(self.running_processes.keys()):
            try:
                self.stop_script(filename)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error during shutdown of %s: %s", filename, exc)
