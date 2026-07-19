"""Single source of truth for the dispatcher version.

Bump ``__version__`` here. Everything else (`/api/health`, the connect
handshake, the discovery beacon, log banner) reads from this module.
"""
__version__ = "3.3.0"
