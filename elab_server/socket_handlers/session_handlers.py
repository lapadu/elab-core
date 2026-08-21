"""Socket.IO handlers for recording, replay and session housekeeping.

Handles: ``session_start``, ``session_stop``, ``get_sessions``,
``replay_load``, ``replay_action``, ``delete_session``,
``get_recorded_providers``.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import sqlite3
import time

from flask_socketio import emit

from .. import config as _config
from ..session_utils import list_recorded_sessions


logger = logging.getLogger(__name__)


def _read_time_sources(cursor) -> dict:
    """Map source_id -> time_source; empty for pre-schema-1 recordings."""
    try:
        cursor.execute("SELECT source_id, time_source FROM session_sources")
        return dict(cursor.fetchall())
    except sqlite3.Error:
        return {}


# pylint: disable=too-many-locals, too-many-statements, unused-argument
def register(socketio, state, recorder, replayer, client_manager):
    """Register session/replay Socket.IO event handlers."""
    # ``client_manager`` is unused here; kept for uniform registrar signature.

    @socketio.on('session_start')
    def cmd_session_start(data):
        """Starts recording a new data session."""
        if replayer.running:
            replayer.control('stop')
            time.sleep(0.2)
        result = recorder.start(data.get('session_id'))
        emit('session_start_result', result)

    @socketio.on('session_stop')
    def cmd_session_stop(_data):
        """Stops the currently active recording session."""
        result = recorder.stop()
        emit('session_stop_result', result)

    @socketio.on('get_sessions')
    def on_get_sessions():
        """Retrieves a list of available recorded sessions."""
        sessions = list_recorded_sessions(_config.SESSION_DIR)
        emit('session_list', sessions)

    @socketio.on('replay_load')
    def on_replay_load(data):
        """Loads a recorded session for playback."""
        session_id = data.get('session_id')
        if state.recording:
            cmd_session_stop({})
            time.sleep(0.2)
        success, msg = replayer.load_session(session_id)
        # The replayer already resolved the span from session_meta (or the log).
        duration = replayer.session_duration_ms if success else 0

        emit('replay_loaded', {
            'success': success,
            'message': msg,
            'session_id': session_id,
            'duration': duration
        })

    @socketio.on('replay_action')
    def on_replay_action(data):
        """Controls the session replayer."""
        if not isinstance(data, dict):
            return
        action = data.get('action')
        value = data.get('value')
        if action in ('play', 'pause', 'stop', 'unload'):
            replayer.control(action, value)
        elif action == 'seek':
            try:
                seek_val = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                logger.warning("replay_action seek: invalid value %r", value)
                return
            if not math.isfinite(seek_val) or seek_val < 0:
                logger.warning("replay_action seek: out-of-range value %r", value)
                return
            replayer.control(action, seek_val)
        elif action == 'speed':
            try:
                speed = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                logger.warning("replay_action speed: invalid value %r", value)
                return
            # Clamp to a sane range so a stray UI slider can't run replay at NaN/inf.
            if not math.isfinite(speed):
                return
            replayer.speed = max(0.1, min(speed, 10.0))

    @socketio.on('delete_session')
    def on_delete_session(data):
        """Deletes a recorded session from the disk."""
        session_id = data.get('session_id')
        if not session_id:
            return

        # --- Security Check ---
        # Ensure the session_id is a simple directory name, no '..' or '/' or '\'.
        if '..' in session_id or '/' in session_id or '\\' in session_id:
            logger.warning(
                "Attempted path traversal on session delete: %s", session_id)
            return

        session_path = os.path.join(_config.SESSION_DIR, session_id)
        if not os.path.isdir(session_path):
            logger.warning(
                "Attempted to delete non-existent session: %s", session_id)
            return

        try:
            shutil.rmtree(session_path)
            logger.info("🗑️ Deleted session: %s", session_id)
            # Refresh the list for all clients.
            on_get_sessions()
        except OSError as e:
            logger.error("Error deleting session %s: %s", session_id, e)

    @socketio.on('get_recorded_providers')
    def on_get_recorded_providers(data):
        """Retrieves the provider manifests for a recorded session."""
        session_id = data.get('session_id')
        db_path = os.path.join(_config.SESSION_DIR, session_id, "session.sqlite")
        if not os.path.exists(db_path):
            emit('recorded_providers', {'providers': []})
            return

        providers = []
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='manifests'")
            if cursor.fetchone() is None:
                logger.warning(
                    "Manifests table not found in %s. Cannot load rec_tasks.",
                    session_id,
                )
                emit('recorded_providers', {'providers': []})
                conn.close()
                return

            # Only include tasks with recorded data in the replay list.
            cursor.execute(
                "SELECT DISTINCT source_id FROM session_log WHERE type = 'DATA_STREAM'")
            recorded_task_ids = {row[0] for row in cursor.fetchall()}
            if not recorded_task_ids:
                logger.warning(
                    "No data streams found in session %s. No rec_tasks will be generated.",
                    session_id,
                )

            # How each track's timestamps were anchored; drives how precisely
            # tracks from different sessions can be aligned.
            time_sources = _read_time_sources(cursor)

            cursor.execute("SELECT manifest FROM manifests")
            rows = cursor.fetchall()
            for row in rows:
                manifest = json.loads(row[0])
                original_provider_id = manifest.get('id')

                rec_provider = manifest.copy()

                # Avoid adding the recorded prefix twice.
                rec_provider_id = original_provider_id
                if not original_provider_id.startswith('rec_'):
                    rec_provider_id = f"rec_{original_provider_id}"
                rec_provider['name'] = f"[REC] {manifest.get('name', 'Unknown')}"
                rec_provider['id'] = rec_provider_id
                rec_provider['originalId'] = original_provider_id
                rec_provider['is_recorded'] = True

                # Preserve the provider-level UI but drop remote URLs that may
                # no longer be reachable during replay.
                prov_ui = dict(manifest.get('ui') or {})
                if prov_ui.get('mode') == 'custom':
                    prov_ui['mode'] = 'generic'
                    prov_ui.pop('url', None)
                    prov_ui.pop('integrity', None)
                rec_provider['ui'] = prov_ui

                if 'tasks' in rec_provider and isinstance(rec_provider['tasks'], list):
                    rec_provider['tasks'] = []
                    for task in manifest.get('tasks', []):
                        original_task_id = task.get('id')

                        if original_task_id not in recorded_task_ids:
                            continue

                        rec_task = task.copy()

                        rec_task_id = original_task_id
                        if not original_task_id.startswith('rec_'):
                            rec_task_id = f"rec_{original_task_id}"

                        rec_task['id'] = rec_task_id
                        rec_task['originalId'] = original_task_id
                        rec_task['name'] = f"[REC] {task.get('name', 'Unknown Task')}"
                        rec_task['is_recorded'] = True
                        if original_task_id in time_sources:
                            rec_task['timeSource'] = time_sources[original_task_id]

                        # Keep the original task UI (views / template) so the
                        # recorded widget looks like the live one. Remote
                        # custom widgets are downgraded to generic because the
                        # provider URL may be unavailable during replay.
                        task_ui = dict(task.get('ui') or {})
                        if task_ui.get('mode') == 'custom':
                            task_ui['mode'] = 'generic'
                            task_ui.pop('url', None)
                            task_ui.pop('integrity', None)
                        rec_task['ui'] = task_ui
                        rec_provider['tasks'].append(rec_task)

                if rec_provider.get('tasks'):
                    providers.append(rec_provider)

        except sqlite3.Error as e:
            logger.error(
                "Error reading recorded providers from '%s': %s", session_id, e)
            providers = []
        finally:
            if conn is not None:
                conn.close()

        logger.debug(
            "Emitting %d recorded providers for session %s.",
            len(providers),
            session_id,
        )
        emit('recorded_providers', {'providers': providers})

    _ = (
        cmd_session_start, cmd_session_stop, on_get_sessions, on_replay_load,
        on_replay_action, on_delete_session, on_get_recorded_providers,
    )
