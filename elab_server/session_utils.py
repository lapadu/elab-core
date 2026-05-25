"""Session-related helper utilities shared across server modules."""

from __future__ import annotations

import os


def list_recorded_sessions(session_dir: str) -> list[str]:
    """Return session ids that contain a ``session.sqlite`` database."""
    if not os.path.exists(session_dir):
        return []

    sessions: list[str] = []
    for entry in os.listdir(session_dir):
        candidate_dir = os.path.join(session_dir, entry)
        if (
            os.path.isdir(candidate_dir)
            and os.path.exists(os.path.join(candidate_dir, "session.sqlite"))
        ):
            sessions.append(entry)

    sessions.sort(reverse=True)
    return sessions
