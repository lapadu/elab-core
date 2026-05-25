"""Extended tests for elab_server.decoders - additional coverage."""

import struct
import random
from typing import cast, Type

import pytest

from elab_server.decoders import DecoderRegistry, BaseDecoder

GBD: Type[BaseDecoder] = cast(
    Type[BaseDecoder],
    DecoderRegistry.get_decoder("generic_binary"),
)


def _pack(fmt: str, values):
    return b"".join(struct.pack(fmt, v) for v in values)


class TestDecoderRegistry:
    """Tests for the DecoderRegistry itself."""

    def test_list_decoders(self):
        """list_decoders should return at least generic_binary."""
        names = DecoderRegistry.list_decoders()
        assert "generic_binary" in names

    def test_get_unknown_decoder(self):
        """Unknown decoder name returns None."""
        assert DecoderRegistry.get_decoder("nonexistent") is None

    def test_register_new_decoder(self):
        """Custom decoder can be registered and retrieved."""

        @DecoderRegistry.register("test_custom")
        # pylint: disable=missing-class-docstring,missing-function-docstring,unused-variable,too-few-public-methods
        class CustomDecoder(BaseDecoder):
            def decode(self, binary_data):
                _ = binary_data
                return [42.0]

        assert DecoderRegistry.get_decoder("test_custom") is not None
        decoder_cls = DecoderRegistry.get_decoder("test_custom")
        assert decoder_cls is not None
        dec = decoder_cls({})
        assert dec.decode(b"") == [42.0]


class TestGenericBinaryDecoderFormats:
    """Tests for different data type formats."""

    def test_int8_decode(self):
        """int8 decoder correctly interprets signed bytes."""
        dec = GBD({"dataType": "int8", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<3b", -128, 0, 127)
        out = dec.decode(data)
        assert out == pytest.approx([-128.0, 0.0, 127.0])

    def test_uint8_decode(self):
        """uint8 decoder correctly interprets unsigned bytes."""
        dec = GBD({"dataType": "uint8", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<3B", 0, 128, 255)
        out = dec.decode(data)
        assert out == pytest.approx([0.0, 128.0, 255.0])

    def test_int16_decode(self):
        """int16 decoder correctly interprets signed 16-bit."""
        dec = GBD({"dataType": "int16", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<2h", -1000, 1000)
        out = dec.decode(data)
        assert out == pytest.approx([-1000.0, 1000.0])

    def test_uint32_decode(self):
        """uint32 decoder correctly interprets unsigned 32-bit."""
        dec = GBD({"dataType": "uint32", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<2I", 0, 100000)
        out = dec.decode(data)
        assert out == pytest.approx([0.0, 100000.0])

    def test_int32_decode(self):
        """int32 decoder correctly interprets signed 32-bit."""
        dec = GBD({"dataType": "int32", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<2i", -50000, 50000)
        out = dec.decode(data)
        assert out == pytest.approx([-50000.0, 50000.0])

    def test_float32_decode(self):
        """float32 decoder correctly interprets IEEE 754 floats."""
        dec = GBD({"dataType": "float32", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<3f", 3.14, -2.71, 0.0)
        out = dec.decode(data)
        assert out == pytest.approx([3.14, -2.71, 0.0], abs=1e-5)

    def test_float64_decode(self):
        """float64 decoder correctly interprets doubles."""
        dec = GBD({"dataType": "float64", "valueRange": 1, "measurementRange": 1})
        data = struct.pack("<2d", 1e-10, 1e10)
        out = dec.decode(data)
        assert out == pytest.approx([1e-10, 1e10])

    def test_big_endian(self):
        """Big-endian decoding should swap byte order."""
        dec = GBD(
            {
                "dataType": "uint16",
                "endianness": "big",
                "valueRange": 1,
                "measurementRange": 1,
            }
        )
        data = struct.pack(">2H", 256, 512)
        out = dec.decode(data)
        assert out == pytest.approx([256.0, 512.0])


class TestGenericBinaryDecoderScaling:
    """Tests for scaling formula."""

    def test_scaling_formula(self):
        """Output = (raw - zeroValue) * (measurementRange / valueRange)."""
        dec = GBD(
            {
                "dataType": "uint16",
                "zeroValue": 2048,
                "valueRange": 4096.0,
                "measurementRange": 3.3,
            }
        )
        data = _pack("<H", [0, 2048, 4096])
        out = dec.decode(data)
        expected = [
            (0 - 2048) * (3.3 / 4096),
            (2048 - 2048) * (3.3 / 4096),
            (4096 - 2048) * (3.3 / 4096),
        ]
        assert out == pytest.approx(expected)

    def test_safe_float_non_numeric(self):
        """Non-numeric config values should fall back to defaults."""
        dec = GBD(
            {
                "dataType": "uint8",
                "zeroValue": "not_a_number",
                "valueRange": None,
                "measurementRange": [1, 2],
            }
        )
        # Should use defaults: zero=0, valueRange=1, measurementRange=1
        out = dec.decode(struct.pack("<B", 10))
        assert out == pytest.approx([10.0])

    def test_safe_float_infinity(self):
        """Infinity config values should fall back to defaults."""
        dec = GBD(
            {
                "dataType": "uint8",
                "zeroValue": float("inf"),
                "valueRange": float("-inf"),
            }
        )
        # inf -> default 0.0, -inf -> default 1.0
        out = dec.decode(struct.pack("<B", 5))
        assert out == pytest.approx([5.0])


class TestLinearizationTable:
    """Tests for the linearization table feature."""

    def test_clamp_below_table(self):
        """Values below the table minimum should clamp to first Y."""
        dec = GBD(
            {
                "dataType": "int16",
                "valueRange": 1,
                "measurementRange": 1,
                "linearizationTable": [[10, 1.0], [100, 10.0]],
            }
        )
        out = dec.decode(struct.pack("<h", 0))
        assert out == pytest.approx([1.0])

    def test_clamp_above_table(self):
        """Values above the table maximum should clamp to last Y."""
        dec = GBD(
            {
                "dataType": "int16",
                "valueRange": 1,
                "measurementRange": 1,
                "linearizationTable": [[10, 1.0], [100, 10.0]],
            }
        )
        out = dec.decode(struct.pack("<h", 200))
        assert out == pytest.approx([10.0])

    def test_multi_segment_interpolation(self):
        """Multi-segment table interpolates correctly in each segment."""
        dec = GBD(
            {
                "dataType": "uint16",
                "valueRange": 1,
                "measurementRange": 1,
                "linearizationTable": [[0, 0], [50, 5], [100, 20]],
            }
        )
        # At 25 -> between [0,0] and [50,5] -> 2.5
        # At 75 -> between [50,5] and [100,20] -> 12.5
        data = _pack("<H", [25, 75])
        out = dec.decode(data)
        assert out == pytest.approx([2.5, 12.5])

    def test_empty_table_disables_linearization(self):
        """Empty table should just do plain scaling."""
        dec = GBD(
            {
                "dataType": "uint8",
                "valueRange": 1,
                "measurementRange": 1,
                "linearizationTable": [],
            }
        )
        out = dec.decode(struct.pack("<B", 42))
        assert out == pytest.approx([42.0])

    def test_single_entry_table_disables_linearization(self):
        """Table with < 2 usable entries disables linearization."""
        dec = GBD(
            {
                "dataType": "uint8",
                "valueRange": 1,
                "measurementRange": 1,
                "linearizationTable": [[50, 5.0]],
            }
        )
        out = dec.decode(struct.pack("<B", 42))
        assert out == pytest.approx([42.0])

    def test_non_monotonic_x_is_filtered(self):
        """Non-monotonic X entries should be filtered out."""
        dec = GBD(
            {
                "dataType": "uint16",
                "valueRange": 1,
                "measurementRange": 1,
                "linearizationTable": [[0, 0], [50, 5], [50, 6], [100, 10]],
            }
        )
        # Duplicate x=50 is dropped, so table is [[0,0], [50,5], [100,10]]
        out = dec.decode(_pack("<H", [25]))
        assert out == pytest.approx([2.5])


class TestDecoderLargePayload:
    """Tests for performance with large payloads."""

    def test_large_uint16_payload(self):
        """1024 samples should decode without issues."""
        dec = GBD(
            {
                "dataType": "uint16",
                "valueRange": 4096,
                "measurementRange": 3.3,
                "zeroValue": 2048,
            }
        )
        # Simulate 1024 ADC readings
        random.seed(42)
        values = [random.randint(0, 4095) for _ in range(1024)]
        data = struct.pack(f"<{len(values)}H", *values)
        out = dec.decode(data)
        assert len(out) == 1024
        # All values should be in reasonable range
        assert all(-2.0 < v < 2.0 for v in out)
