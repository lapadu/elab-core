"""Tests for elab_api.SharedMemoryChannel."""
import uuid

import numpy as np
import pytest

from elab_api.shared_memory_channel import SharedMemoryChannel


def _unique_name() -> str:
    return f"test_shm_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def channel():
    """Create and clean up a shared memory channel."""
    name = _unique_name()
    ch = SharedMemoryChannel(name=name, capacity=1024, create=True)
    yield ch
    ch.close()
    ch.unlink()


class TestSharedMemoryChannel:
    """Tests for the SharedMemoryChannel ring-buffer."""

    def test_write_and_read(self, channel: SharedMemoryChannel):
        """Written data can be read back."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        channel.write(data)
        result = channel.read_latest(5)
        np.testing.assert_array_equal(result, data)

    def test_read_latest_partial(self, channel: SharedMemoryChannel):
        """Reading fewer samples than written returns the most recent ones."""
        data = np.arange(10, dtype=np.float32)
        channel.write(data)
        result = channel.read_latest(3)
        np.testing.assert_array_equal(result, np.array([7.0, 8.0, 9.0], dtype=np.float32))

    def test_wrap_around(self, channel: SharedMemoryChannel):
        """Data wraps correctly around the ring buffer."""
        # Fill most of the buffer
        big = np.arange(1020, dtype=np.float32)
        channel.write(big)
        # Write more to cause wrap
        extra = np.array([9001.0, 9002.0, 9003.0, 9004.0, 9005.0], dtype=np.float32)
        channel.write(extra)
        result = channel.read_latest(5)
        np.testing.assert_array_equal(result, extra)

    def test_read_empty(self, channel: SharedMemoryChannel):
        """Reading from an empty channel returns an empty array."""
        result = channel.read_latest(10)
        assert len(result) == 0

    def test_write_index_advances(self, channel: SharedMemoryChannel):
        """Write index advances with each write."""
        assert channel.write_index == 0
        channel.write(np.ones(10, dtype=np.float32))
        assert channel.write_index == 10
        channel.write(np.ones(5, dtype=np.float32))
        assert channel.write_index == 15

    def test_attach_existing(self, channel: SharedMemoryChannel):
        """A second channel can attach to the same SHM block and read data."""
        data = np.array([42.0, 43.0], dtype=np.float32)
        channel.write(data)

        reader = SharedMemoryChannel(name=channel.name, create=False)
        try:
            result = reader.read_latest(2)
            np.testing.assert_array_equal(result, data)
        finally:
            reader.close()

    def test_timestamp_updates(self, channel: SharedMemoryChannel):
        """Timestamp is updated on each write."""
        assert channel.timestamp_ns == 0
        channel.write(np.ones(1, dtype=np.float32))
        assert channel.timestamp_ns > 0
