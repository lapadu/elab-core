"""Socket.IO handlers for client-side Python script process management.

Handles: ``get_available_scripts``, ``start_client_script``,
``stop_client_script``.
"""
from __future__ import annotations

import logging

from flask_socketio import emit


logger = logging.getLogger(__name__)


# pylint: disable=unused-argument
def register(socketio, state, recorder, replayer, client_manager):
    """Register process-management Socket.IO event handlers."""
    # ``state``, ``recorder`` and ``replayer`` unused; kept for uniform signature.

    @socketio.on('get_available_scripts')
    def handle_get_scripts():
        """Scans the clients directory for available Python scripts."""
        emit('available_scripts', client_manager.scan_scripts())

    @socketio.on('start_client_script')
    def handle_start_script(data):
        """Starts a Python client script in a new process."""
        filename = data.get('filename')
        success, msg = client_manager.start_script(filename)
        if success:
            emit('available_scripts',
                 client_manager.scan_scripts(), broadcast=True)
        else:
            logger.error("Failed to start script %s: %s", filename, msg)

    @socketio.on('stop_client_script')
    def handle_stop_script(data):
        """Stops a running Python client script."""
        filename = data.get('filename')
        client_manager.stop_script(filename)
        emit('available_scripts', client_manager.scan_scripts(), broadcast=True)

    _ = (handle_get_scripts, handle_start_script, handle_stop_script)
