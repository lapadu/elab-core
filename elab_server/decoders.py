"""
Plugin system for data decoders in the E-Lab dispatcher.

Allows registering and executing decoders requested and configured by
clients through their manifests.

Designed to be defensive: client devices (e.g. ESP32) may send malformed,
unsorted or partially-typed configuration / payload data. No client input
should be able to crash decoder instantiation or decoding.
"""
import math
import struct
import bisect
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DecoderRegistry:
    """Central registry for all available decoder plugins."""
    _decoders: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator used to register a new decoder."""
        def wrapper(decoder_cls):
            cls._decoders[name] = decoder_cls
            return decoder_cls
        return wrapper

    @classmethod
    def get_decoder(cls, name: str) -> Optional[type]:
        """Returns the decoder class for a given name."""
        return cls._decoders.get(name)

    @classmethod
    def list_decoders(cls) -> List[str]:
        """Returns the names of all registered decoders."""
        return list(cls._decoders.keys())


class BaseDecoder:
    """Base class for all decoders."""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def decode(self, binary_data: bytes) -> List[float]:
        """Must be implemented by concrete decoders."""
        raise NotImplementedError("Decode method must be implemented.")

    def map_uncertainty(self, uncertainty: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Map incoming uncertainty metadata to the decoder output domain.

        Base implementation is a pass-through. Concrete decoders may override
        this, e.g. to transform raw-domain uncertainty through nonlinear
        calibration tables.
        """
        return uncertainty


# Maps logical data types to Python struct format characters.
_TYPE_MAP: Dict[str, str] = {
    "uint8": "B", "int8": "b",
    "uint16": "H", "int16": "h",
    "uint32": "I", "int32": "i",
    "float32": "f", "float64": "d",
}


@DecoderRegistry.register("generic_binary")
class GenericBinaryDecoder(BaseDecoder):
    """
    Generic decoder that reads binary raw data, scales it, and optionally
    linearizes it against a lookup table.
    """
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # 1. Parse the incoming data format.
        self.data_type = config.get("dataType", "uint16")
        self.endian = "<" if config.get("endianness", "little") == "little" else ">"

        self.fmt_char = _TYPE_MAP.get(self.data_type, "H")
        self.byte_size = struct.calcsize(self.fmt_char)

        # 2. Scaling parameters - coerce defensively, fall back to safe defaults
        #    so a malformed manifest from an ESP32 cannot crash __init__.
        self.zero_val = self._safe_float(config.get("zeroValue", 0.0), 0.0)
        self.val_range = self._safe_float(config.get("valueRange", 1.0), 1.0)
        self.meas_range = self._safe_float(config.get("measurementRange", 1.0), 1.0)
        if self.val_range == 0.0:
            self.val_range = 1.0  # Prevent division by zero.

        # Pre-compute the combined scaling factor used in the hot path.
        self._scale = self.meas_range / self.val_range

        # 3. Optional linearization table.
        # Expected format: [[raw_x1, real_y1], [raw_x2, real_y2], ...]
        self.lin_x: List[float] = []
        self.lin_y: List[float] = []
        self._has_lin_table = False

        raw_table = config.get("linearizationTable") or []
        if raw_table:
            self._build_lin_table(raw_table)

        # Updated by decode(); used to map raw-domain uncertainty into the
        # post-decoding value domain using the local transfer slope.
        self._last_scaled_value: Optional[float] = None

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        """Convert value to float; fall back to default for non-finite or
        non-numeric input. Never raises."""
        try:
            f = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(f):
            return default
        return f

    def _build_lin_table(self, raw_table: Any) -> None:
        """Validate and store the linearization table.

        Rejects malformed entries silently (with a warning) instead of
        crashing decoder init when a client sends garbage.
        """
        if not isinstance(raw_table, list):
            logger.warning("linearizationTable is not a list, ignoring.")
            return

        cleaned: List[tuple] = []
        for entry in raw_table:
            # Accept [x, y] pairs or (x, y) tuples; skip anything else.
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            try:
                x = float(entry[0])
                y = float(entry[1])
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            cleaned.append((x, y))

        if len(cleaned) < 2:
            if raw_table:
                logger.warning(
                    "linearizationTable invalid or has <2 usable entries, "
                    "linearization disabled."
                )
            return

        # Sort a local copy by X; never mutate the caller's config object.
        cleaned.sort(key=lambda p: p[0])

        # Enforce strictly monotonic X to keep bisect/interpolation well-defined.
        # Duplicates are dropped (first occurrence wins).
        prev_x: Optional[float] = None
        for x, y in cleaned:
            if prev_x is not None and x <= prev_x:
                logger.warning(
                    "linearizationTable contains duplicate or non-monotonic X "
                    "(%.6g <= %.6g); duplicate entries ignored.", x, prev_x
                )
                continue
            self.lin_x.append(x)
            self.lin_y.append(y)
            prev_x = x

        self._has_lin_table = len(self.lin_x) >= 2

    def _linearize(self, val: float) -> float:
        """Runs a fast linear interpolation in pure Python."""
        if not self._has_lin_table:
            return val

        # Find the matching interval via binary search in O(log n).
        idx = bisect.bisect_right(self.lin_x, val)

        # Clamp values that fall outside the lookup table.
        if idx == 0:
            return self.lin_y[0]
        if idx == len(self.lin_x):
            return self.lin_y[-1]

        # Interpolate between the two nearest points.
        x0, y0 = self.lin_x[idx - 1], self.lin_y[idx - 1]
        x1, y1 = self.lin_x[idx], self.lin_y[idx]

        # x1 != x0 is guaranteed by the strictly-monotonic check above.
        return y0 + (y1 - y0) * ((val - x0) / (x1 - x0))

    def _local_slope(self, scaled_val: float) -> float:
        """Return local dy/dx slope of the linearization transfer function.

        For values outside the calibration table the output is clamped, hence
        the local derivative is treated as 0.
        """
        if not self._has_lin_table:
            return 1.0

        idx = bisect.bisect_right(self.lin_x, scaled_val)
        if idx == 0 or idx == len(self.lin_x):
            return 0.0

        x0, y0 = self.lin_x[idx - 1], self.lin_y[idx - 1]
        x1, y1 = self.lin_x[idx], self.lin_y[idx]
        dx = x1 - x0
        if dx == 0.0:
            return 0.0
        return (y1 - y0) / dx

    def adc_lsb_decoded(self) -> float:
        """Return one raw-code LSB represented in decoded output units."""
        if self._last_scaled_value is None:
            slope = 1.0 if not self._has_lin_table else 0.0
        else:
            slope = self._local_slope(self._last_scaled_value)
        return abs(slope * self._scale)

    def decode(self, binary_data: Optional[bytes]) -> List[float]:
        """
        Converts a byte array into decoded float values.

        binary_data is expected to be a bytes/bytearray object received
        through Socket.IO. None or empty buffers are tolerated.
        """
        if not binary_data:
            return []

        # Compute the number of elements in the payload.
        total_len = len(binary_data)
        num_elements = total_len // self.byte_size
        if num_elements == 0:
            return []

        # Warn on (but tolerate) misaligned payloads from buggy clients.
        remainder = total_len % self.byte_size
        if remainder:
            logger.warning(
                "Misaligned binary payload: %d bytes, dataType=%s (%d B); "
                "%d trailing byte(s) discarded.",
                total_len, self.data_type, self.byte_size, remainder,
            )

        # Build the struct format string, e.g. "<2560H".
        fmt = f"{self.endian}{num_elements}{self.fmt_char}"

        try:
            raw_values = struct.unpack(
                fmt, binary_data[:num_elements * self.byte_size]
            )
        except struct.error as e:
            logger.error(
                "struct.unpack failed (%s) for fmt=%s len=%d",
                e, fmt, total_len,
            )
            return []

        zero = self.zero_val
        scale = self._scale

        # Fast path: no linearization -> simple scaling list comprehension.
        if not self._has_lin_table:
            scaled_vals = [(r - zero) * scale for r in raw_values]
            if scaled_vals:
                self._last_scaled_value = float(scaled_vals[-1])
            return scaled_vals

        # Slow path: scale + per-sample linearization.
        linearize = self._linearize
        out: List[float] = []
        last_scaled: Optional[float] = None
        for r in raw_values:
            scaled_val = (r - zero) * scale
            out.append(linearize(scaled_val))
            last_scaled = float(scaled_val)
        self._last_scaled_value = last_scaled
        return out

    def map_uncertainty(self, uncertainty: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Map raw-domain uncertainty to decoded-domain uncertainty.

        Expected optional input fields:
        - domain: "raw" | "decoded"
        - systematicAbs: absolute systematic bound in current domain
        - randomSigma: 1-sigma random uncertainty in current domain
        """
        if not isinstance(uncertainty, dict):
            return uncertainty

        mapped = dict(uncertainty)
        domain = mapped.get("domain", "decoded")
        if domain != "raw":
            mapped["domain"] = "decoded"
            return mapped

        slope_scale = self.adc_lsb_decoded()

        for key in ("systematicAbs", "randomSigma"):
            val = mapped.get(key)
            try:
                f = float(val)
            except (TypeError, ValueError):
                continue
            if math.isfinite(f):
                mapped[key] = abs(f) * slope_scale

        mapped["domain"] = "decoded"
        mapped["mappedBy"] = "generic_binary_local_derivative"
        return mapped
