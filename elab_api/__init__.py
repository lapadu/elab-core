"""elab_api – Local API Bridge client library for E-Lab.

Provides a lightweight Python interface for external scripts to integrate
with the E-Lab ecosystem via ZeroMQ (control plane) and shared memory (data plane).
"""

from .local_node import LocalNode
from .shared_memory_channel import SharedMemoryChannel

__all__ = ["LocalNode", "SharedMemoryChannel"]
