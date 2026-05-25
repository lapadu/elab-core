"""Shared memory channel for zero-copy data transfer between bridge and scripts."""
from __future__ import annotations

import logging
import signal
import struct
import threading
import time
from multiprocessing import shared_memory
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Header layout: [write_index (uint64), timestamp_ns (uint64), chunk_size (uint32)]
_HEADER_FMT = "<QQI"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class SharedMemoryChannel:
    """A ring-buffer backed by OS shared memory for zero-copy NumPy transfers.

    Parameters
    ----------
    name : str
        Unique shared memory block name.
    capacity : int
        Number of samples the ring buffer can hold.
    dtype : np.dtype
        Data type of each sample.
    create : bool
        Whether to create (True) or attach to (False) the block.
    """

    def __init__(
        self,
        name: str,
        capacity: int = 65536,
        dtype: np.dtype = np.dtype(np.float32),
        create: bool = False,
    ):
        self.name = name
        self.dtype = dtype
        self._closed = False

        if create:
            self.capacity = capacity
            buf_size = _HEADER_SIZE + capacity * dtype.itemsize
            self._shm = shared_memory.SharedMemory(
                name=name, create=True, size=buf_size
            )
            # Zero-initialize header
            struct.pack_into(_HEADER_FMT, self._shm.buf, 0, 0, 0, 0)
        else:
            self._shm = shared_memory.SharedMemory(name=name, create=False)
            # Derive capacity from the existing block size
            self.capacity = (self._shm.size - _HEADER_SIZE) // dtype.itemsize

        # Map the data portion as a NumPy array (no copy).
        self._array = np.ndarray(
            shape=(self.capacity,),
            dtype=dtype,
            buffer=self._shm.buf,
            offset=_HEADER_SIZE,
        )

    @property
    def write_index(self) -> int:
        """Current writer position in the ring buffer."""
        return struct.unpack_from("<Q", self._shm.buf, 0)[0]

    @property
    def timestamp_ns(self) -> int:
        """Timestamp (nanoseconds) of the last write."""
        return struct.unpack_from("<Q", self._shm.buf, 8)[0]

    def write(self, data: np.ndarray) -> None:
        """Write a chunk of data into the ring buffer (producer side)."""
        n = len(data)
        if n == 0:
            return
        idx = self.write_index % self.capacity
        if idx + n <= self.capacity:
            self._array[idx : idx + n] = data
        else:
            # Wrap around
            first = self.capacity - idx
            self._array[idx:] = data[:first]
            self._array[: n - first] = data[first:]

        new_idx = self.write_index + n
        ts = time.time_ns()
        struct.pack_into(_HEADER_FMT, self._shm.buf, 0, new_idx, ts, n)

    def read_latest(self, count: int) -> np.ndarray:
        """Read the latest *count* samples from the ring buffer (consumer side)."""
        wi = self.write_index
        if wi == 0:
            return np.empty(0, dtype=self.dtype)
        count = min(count, wi, self.capacity)
        end = wi % self.capacity
        start = end - count
        if start >= 0:
            return self._array[start:end].copy()
        # Wrap-around read
        return np.concatenate(
            [self._array[start + self.capacity :], self._array[:end]]
        ).copy()

    def close(self) -> None:
        """Detach from the shared memory block."""
        if self._closed:
            return
        self._closed = True
        try:
            self._shm.close()
        except (BufferError, OSError):
            pass

    def unlink(self) -> None:
        """Remove the shared memory block from the OS (creator only)."""
        try:
            self._shm.unlink()
        except (FileNotFoundError, OSError):
            pass

    def __del__(self) -> None:
        if hasattr(self, "_closed"):
            self.close()
