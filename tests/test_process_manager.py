"""Tests for elab_server.process_manager.ClientProcessManager."""
# Tests intentionally exercise protected helpers and compact local stubs.
# pylint: disable=protected-access,missing-class-docstring,missing-function-docstring

import io
import logging
import subprocess
import threading
from typing import cast
from unittest.mock import patch, MagicMock

from elab_server.process_manager import ClientProcessManager, _SCRIPT_FILENAME_RE


class TestScriptFilenameRegex:
    """Tests for the filename validation regex."""

    def test_valid_filenames(self):
        """Normal .py filenames should match."""
        valid = [
            "FrequenceCounterClient.py",
            "TempTestClient.py",
            "my_script.py",
            "test123.py",
            "A.py",
        ]
        for name in valid:
            assert _SCRIPT_FILENAME_RE.match(name), f"{name} should be valid"

    def test_rejects_path_traversal(self):
        """Path traversal attempts should be rejected."""
        invalid = [
            "../evil.py",
            "..\\evil.py",
            "../../etc/passwd",
            "/absolute/path.py",
            "subdir/script.py",
        ]
        for name in invalid:
            assert not _SCRIPT_FILENAME_RE.match(name), f"{name} should be rejected"

    def test_rejects_dot_prefix(self):
        """Hidden files starting with . should be rejected."""
        assert not _SCRIPT_FILENAME_RE.match(".hidden.py")

    def test_rejects_non_py(self):
        """Non-.py extensions should be rejected."""
        invalid = ["script.sh", "binary.exe", "config.json"]
        for name in invalid:
            assert not _SCRIPT_FILENAME_RE.match(name), f"{name} should be rejected"

    def test_rejects_shell_metacharacters(self):
        """Shell injection characters should be rejected."""
        invalid = [
            "script;rm -rf.py",
            "script$(cmd).py",
            "script`cmd`.py",
            "script|pipe.py",
        ]
        for name in invalid:
            assert not _SCRIPT_FILENAME_RE.match(name), f"{name} should be rejected"

    def test_rejects_empty_and_special(self):
        """Empty strings and special names should be rejected."""
        assert not _SCRIPT_FILENAME_RE.match("")
        assert not _SCRIPT_FILENAME_RE.match("__init__.py")  # starts with __


def _make_pm(tmp_path):
    """Create a ClientProcessManager with a temp clients_dir, bypassing __init__."""
    scripts_dir = tmp_path / "elab_clients"
    scripts_dir.mkdir(exist_ok=True)
    pm = ClientProcessManager.__new__(ClientProcessManager)
    pm.clients_dir = str(scripts_dir)
    pm.running_processes = {}
    pm._stop = threading.Event()
    pm._python = "python"
    return pm, scripts_dir


class TestClientProcessManager:
    """Tests for ClientProcessManager core logic."""

    def test_resolve_script_path_valid(self, tmp_path):
        """Valid script should resolve to its absolute path."""
        pm, scripts_dir = _make_pm(tmp_path)
        script = scripts_dir / "TestClient.py"
        script.write_text("# test")

        path, err = pm._resolve_script_path("TestClient.py")
        assert err is None
        assert path == str(script.resolve())

    def test_resolve_script_path_traversal_blocked(self, tmp_path):
        """Path traversal should be blocked."""
        pm, _ = _make_pm(tmp_path)
        # Create file outside
        outside = tmp_path / "evil.py"
        outside.write_text("# evil")

        path, err = pm._resolve_script_path("../evil.py")
        assert path is None
        assert err is not None
        assert "Invalid" in err or "traversal" in err.lower()

    def test_resolve_script_path_nonexistent(self, tmp_path):
        """Non-existent script should return error."""
        pm, _ = _make_pm(tmp_path)

        path, err = pm._resolve_script_path("nonexistent.py")
        assert path is None
        assert err is not None
        assert "not found" in err.lower()

    def test_resolve_script_invalid_filename(self, tmp_path):
        """Invalid filenames should be rejected before path resolution."""
        pm, _ = _make_pm(tmp_path)

        path, err = pm._resolve_script_path("../../etc/passwd")
        assert path is None
        assert err is not None
        assert "Invalid" in err

    def test_resolve_script_non_string(self, tmp_path):
        """Non-string input should be rejected."""
        pm, _ = _make_pm(tmp_path)

        path, err = pm._resolve_script_path(cast(str, None))
        assert path is None
        assert err is not None
        assert "Invalid" in err

    def test_scan_scripts(self, tmp_path):
        """scan_scripts should list .py files in clients directory."""
        pm, scripts_dir = _make_pm(tmp_path)
        (scripts_dir / "Client1.py").write_text("# c1")
        (scripts_dir / "Client2.py").write_text("# c2")
        (scripts_dir / "__init__.py").write_text("")  # should be excluded
        (scripts_dir / "assets").mkdir()  # should be excluded (not .py)

        with patch('elab_server.process_manager._FROZEN', False):
            scripts = pm.scan_scripts()

        names = [s["filename"] for s in scripts]
        assert "Client1.py" in names
        assert "Client2.py" in names
        assert "__init__.py" not in names

    def test_scan_scripts_missing_dir(self, tmp_path):
        """Missing directory should return empty list without crashing."""
        pm, _ = _make_pm(tmp_path)
        pm.clients_dir = str(tmp_path / "nonexistent")

        scripts = pm.scan_scripts()
        assert not scripts

    def test_running_state_in_scan(self, tmp_path):
        """Running scripts should be reported as isRunning=True."""
        pm, scripts_dir = _make_pm(tmp_path)
        (scripts_dir / "Running.py").write_text("# r")

        # Simulate a running process
        class FakeProc:
            def poll(self):
                return None  # still running
        pm.running_processes = {"Running.py": FakeProc()}

        with patch('elab_server.process_manager._FROZEN', False):
            scripts = pm.scan_scripts()

        running = [s for s in scripts if s["filename"] == "Running.py"]
        assert len(running) == 1
        assert running[0]["isRunning"] is True

    def test_scan_excludes_asset_files(self, tmp_path):
        """Files with 'asset' in the name should be excluded."""
        pm, scripts_dir = _make_pm(tmp_path)
        (scripts_dir / "asset_helper.py").write_text("# skip")
        (scripts_dir / "RealClient.py").write_text("# keep")

        with patch('elab_server.process_manager._FROZEN', False):
            scripts = pm.scan_scripts()

        names = [s["filename"] for s in scripts]
        assert "RealClient.py" in names
        assert "asset_helper.py" not in names


class TestStartScript:
    """Tests for start_script."""

    def test_start_script_success(self, tmp_path):
        """Starting a valid script should succeed."""
        pm, scripts_dir = _make_pm(tmp_path)
        (scripts_dir / "MyClient.py").write_text("# client")

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")

        with patch('elab_server.process_manager._FROZEN', False), \
             patch('elab_server.process_manager.subprocess.Popen', return_value=mock_proc):
            ok, msg = pm.start_script("MyClient.py")

        assert ok is True
        assert "12345" in msg
        assert "MyClient.py" in pm.running_processes

    def test_start_already_running(self, tmp_path):
        """Starting an already-running script should fail."""
        pm, scripts_dir = _make_pm(tmp_path)
        (scripts_dir / "Running.py").write_text("# r")

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        pm.running_processes["Running.py"] = mock_proc

        ok, msg = pm.start_script("Running.py")
        assert ok is False
        assert "Already running" in msg

    def test_start_invalid_filename(self, tmp_path):
        """Invalid filenames should be rejected."""
        pm, _ = _make_pm(tmp_path)

        ok, msg = pm.start_script("../evil.py")
        assert ok is False
        assert "Invalid" in msg

    def test_start_nonexistent_script(self, tmp_path):
        """Non-existent scripts should fail."""
        pm, _ = _make_pm(tmp_path)

        ok, msg = pm.start_script("ghost.py")
        assert ok is False
        assert "not found" in msg.lower()

    def test_start_popen_oserror(self, tmp_path):
        """OSError from Popen should be handled gracefully."""
        pm, scripts_dir = _make_pm(tmp_path)
        (scripts_dir / "Broken.py").write_text("# broken")

        with patch('elab_server.process_manager._FROZEN', False), \
             patch('elab_server.process_manager.subprocess.Popen',
                   side_effect=OSError("No such interpreter")):
            ok, msg = pm.start_script("Broken.py")

        assert ok is False
        assert "No such interpreter" in msg


class TestStopScript:
    """Tests for stop_script."""

    def test_stop_running_script(self, tmp_path):
        """Stopping a running script should terminate it."""
        pm, _ = _make_pm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        pm.running_processes["MyClient.py"] = mock_proc

        ok, msg = pm.stop_script("MyClient.py")
        assert ok is True
        assert "Stopped" in msg
        assert "MyClient.py" not in pm.running_processes
        mock_proc.terminate.assert_called_once()

    def test_stop_not_running(self, tmp_path):
        """Stopping a non-running script should fail."""
        pm, _ = _make_pm(tmp_path)

        ok, _msg = pm.stop_script("NotRunning.py")
        assert ok is False
        assert "Not running" in _msg

    def test_stop_force_kill_on_timeout(self, tmp_path):
        """If terminate times out, the process should be killed."""
        pm, _ = _make_pm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), 0]
        pm.running_processes["Stubborn.py"] = mock_proc

        ok, _msg = pm.stop_script("Stubborn.py")
        assert ok is True
        mock_proc.kill.assert_called_once()
        assert "Stubborn.py" not in pm.running_processes

    def test_stop_oserror(self, tmp_path):
        """OSError during terminate should be handled."""
        pm, _ = _make_pm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.terminate.side_effect = OSError("Permission denied")
        pm.running_processes["Protected.py"] = mock_proc

        ok, msg = pm.stop_script("Protected.py")
        assert ok is False
        assert "Error" in msg
        assert "Protected.py" not in pm.running_processes


class TestShutdown:
    """Tests for the shutdown method."""

    def test_shutdown_stops_all_processes(self, tmp_path):
        """Shutdown should stop all running scripts."""
        pm, _ = _make_pm(tmp_path)
        mock_proc1 = MagicMock()
        mock_proc1.wait.return_value = 0
        mock_proc2 = MagicMock()
        mock_proc2.wait.return_value = 0
        pm.running_processes = {
            "Client1.py": mock_proc1,
            "Client2.py": mock_proc2,
        }

        pm.shutdown()

        assert pm._stop.is_set()
        mock_proc1.terminate.assert_called_once()
        mock_proc2.terminate.assert_called_once()

    def test_shutdown_handles_exception_in_stop(self, tmp_path):
        """Shutdown should not crash if a stop_script call fails."""
        pm, _ = _make_pm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.terminate.side_effect = Exception("unexpected")
        pm.running_processes = {"Bad.py": mock_proc}

        # Should not raise
        pm.shutdown()
        assert pm._stop.is_set()


class TestCleanupZombies:
    """Tests for the _cleanup_zombies background thread."""

    def test_removes_finished_processes(self, tmp_path):
        """Finished processes should be removed from running_processes."""
        pm, _ = _make_pm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # finished
        pm.running_processes["Done.py"] = mock_proc

        # Run one cleanup iteration then stop
        call_count = 0
        def limited_wait(timeout=None):
            _ = timeout
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                pm._stop.set()
                return True
            return False

        pm._stop.wait = limited_wait
        pm._cleanup_zombies()

        assert "Done.py" not in pm.running_processes


class TestLogOutput:
    """Tests for the _log_output stream parser."""

    def test_parses_log_levels(self, tmp_path):
        """Log lines with [LEVEL] should be logged at the correct level."""
        pm, _ = _make_pm(tmp_path)
        lines = [
            b"[INFO] Starting up\n",
            b"[ERROR] Something failed\n",
            b"[WARNING] Low memory\n",
            b"[DEBUG] Verbose detail\n",
            b"Simple output\n",
            b"",  # sentinel for readline
        ]
        stream = io.BytesIO(b"".join(lines))

        with patch.object(logging.getLogger('elab_server.process_manager'), 'log') as mock_log:
            pm._log_output(stream, "TestClient.py")

        levels = [call.args[0] for call in mock_log.call_args_list]
        assert logging.INFO in levels
        assert logging.ERROR in levels
        assert logging.WARNING in levels
        assert logging.DEBUG in levels

    def test_handles_broken_pipe(self, tmp_path):
        """OSError from a broken pipe should not crash."""
        pm, _ = _make_pm(tmp_path)

        stream = MagicMock()
        stream.readline.side_effect = OSError("broken pipe")

        # Should not raise
        pm._log_output(stream, "Broken.py")
