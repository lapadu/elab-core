"""Tests for elab_server.decoders.GenericBinaryDecoder."""
import struct
from typing import cast, Type

import pytest

from elab_server.decoders import DecoderRegistry, BaseDecoder


GBD: Type[BaseDecoder] = cast(
    Type[BaseDecoder],
    DecoderRegistry.get_decoder("generic_binary"),
)


def _pack(fmt: str, values):
    return b"".join(struct.pack(fmt, v) for v in values)


def test_registry_has_generic_binary():
    """Decoder registry must contain the generic_binary entry."""
    assert GBD is not None, "generic_binary decoder must be registered"


def test_basic_uint16_no_lin_table():
    """Scale formula (raw - zero) * (mRange / vRange) is applied correctly."""
    # Output = (raw - zeroValue) * (measurementRange / valueRange)
    dec = GBD({
        "dataType": "uint16",
        "zeroValue": 100,
        "valueRange": 10.0,
        "measurementRange": 1.0,
    })
    out = dec.decode(_pack("<H", [200, 300, 400]))
    assert out == pytest.approx([10.0, 20.0, 30.0])


def test_empty_payload_is_safe():
    """Empty bytes must return an empty list without raising."""
    dec = GBD({"dataType": "uint8"})
    assert dec.decode(b"") == []


def test_none_payload_is_safe():
    """None payload must return an empty list without raising."""
    dec = GBD({"dataType": "uint8"})
    assert dec.decode(None) == []  # type: ignore[arg-type]


def test_misaligned_payload_truncates_gracefully():
    """Trailing bytes that do not fill a complete sample must be silently dropped."""
    dec = GBD({"dataType": "uint16"})
    out = dec.decode(b"\x01\x00\x99")
    assert len(out) == 1


def test_zero_value_range_falls_back_to_one():
    """valueRange=0 must not cause a division-by-zero crash."""
    dec = GBD({"dataType": "uint16", "valueRange": 0.0})
    assert dec.decode(_pack("<H", [10])) == [10.0]


def test_lin_table_interpolation():
    """Linearization table interpolates linearly between anchor points."""
    dec = GBD({
        "dataType": "uint16",
        "valueRange": 1.0,
        "measurementRange": 1.0,
        "linearizationTable": [[0, 0.0], [100, 10.0]],
    })
    out = dec.decode(_pack("<H", [0, 50, 100]))
    assert out == pytest.approx([0.0, 5.0, 10.0])


def test_lin_table_with_nan_and_duplicates_is_filtered():
    """NaN entries and duplicate X values in the table must be silently dropped."""
    dec = GBD({
        "dataType": "uint16",
        "valueRange": 1.0,
        "measurementRange": 1.0,
        "linearizationTable": [
            [0, 0.0],
            [float("nan"), 1.0],
            [50, 5.0],
            [50, 5.0],
            [100, 10.0],
        ],
    })
    out = dec.decode(_pack("<H", [25]))
    assert out == pytest.approx([2.5])


def test_unknown_data_type_falls_back_to_uint16_safely():
    """Unknown dataType must not crash init; decoder falls back to uint16 format."""
    dec = GBD({"dataType": "frobnicate"})
    out = dec.decode(b"\x01\x02\x03\x04")
    assert len(out) == 2  # 4 bytes / 2 B per uint16


def test_garbage_lin_table_disables_linearization():
    """Non-list linearizationTable must be silently ignored; raw values pass through."""
    dec = GBD({
        "dataType": "uint16",
        "valueRange": 1.0,
        "measurementRange": 1.0,
        "linearizationTable": "totally invalid",
    })
    out = dec.decode(_pack("<H", [42]))
    assert out == [42.0]
