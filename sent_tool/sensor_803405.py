from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# From provided sensor spec:
# Transfer function: p_rel / bar = 0.00825 * DigitValue - 1.65
def pressure_bar_from_digit_value(digit_value: int) -> float:
    return 0.00825 * float(digit_value) - 1.65


# Spec: used pressure signal range / codes
PRESSURE_INIT_DIGIT_VALUE = 0
PRESSURE_LOW_CLAMP_MAX_DIGIT_VALUE = 1
PRESSURE_HIGH_CLAMP_MIN_DIGIT_VALUE = 4088
PRESSURE_ERROR_DIGIT_VALUE = 4090  # Error Code 4090


def pressure_state_from_digit_value(digit_value: int) -> str:
    """
    Human-readable state derived from DigitValue ranges from the spec.
    """
    if digit_value == PRESSURE_ERROR_DIGIT_VALUE:
        return "ERROR_CODE_4090"
    if digit_value >= PRESSURE_HIGH_CLAMP_MIN_DIGIT_VALUE and digit_value < PRESSURE_ERROR_DIGIT_VALUE:
        return "HIGH_CLAMP"
    if digit_value == PRESSURE_INIT_DIGIT_VALUE:
        return "INITIALIZATION"
    if 0 < digit_value <= PRESSURE_LOW_CLAMP_MAX_DIGIT_VALUE:
        return "LOW_CLAMP"
    return "OK"


def temperature_c_from_tval(tval: int) -> float:
    # T / °C = 0.125 * Tval - 73.15
    return 0.125 * float(tval) - 73.15


DIAG_ERROR_TEXT: dict[int, str] = {
    0x000: "No error",
    0x900: "Sensor supply undervoltage",
    0x901: "Sensor supply overvoltage",
    0xFC1: "IC internal hardware error",
    0xFC2: "IC internal ADC or Gain error",
    0xF01: "Bridge connections check failed",
    0xF02: "Bridge output short check failed",
    0xF03: "Bridge common mode check failed",
    0xF04: "Pressure ADC saturation error",
    0xD05: "Internal IC Temperature error",
    0xF05: "Internal math saturation",
}


SLOW_ID_DEFINITION: dict[int, str] = {
    0x01: "DiagnosticErrorCodes",
    0x03: "SensorType",
    0x04: "ManufacturerType",
    0x05: "ManufacturerCode",
    0x06: "SENTStandardRevision",
    0x07: "PressureCharacteristicX1",
    0x08: "PressureCharacteristicX2",
    0x09: "PressureCharacteristicY1",
    0x0A: "PressureCharacteristicY2",
    0x23: "InternalTemperature",
    0x29: "SensorIdSerialLast3",
    0x2A: "SensorIdSerialFirst3",
    0x2B: "DateCodeLast3",
    0x2C: "DateCodeFirst2",
}


@dataclass(frozen=True)
class DecodedSlow:
    msg_id: int
    name: str
    raw: int
    text: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None


def decode_slow_value(msg_id: int, raw_value: int) -> DecodedSlow:
    """
    Decodes the 12-bit data field of an enhanced slow message according to the sensor spec.
    """
    name = SLOW_ID_DEFINITION.get(msg_id, f"UnknownSlowId_0x{msg_id:02X}")

    # 0x01: Diagnostic error code
    if msg_id == 0x01:
        return DecodedSlow(
            msg_id=msg_id,
            name=name,
            raw=raw_value,
            text=DIAG_ERROR_TEXT.get(raw_value, f"Unknown diagnostic code 0x{raw_value:03X}"),
        )

    # 0x23: Internal temperature
    if msg_id == 0x23:
        t_c = temperature_c_from_tval(raw_value)
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, value=t_c, unit="°C")

    # 0x07 / 0x08: Pressure characteristic X1/X2 are given in bar in the spec
    # Example values: X1 = 0x000 (0 bar), X2 = 0x0F5 (30 bar)
    if msg_id == 0x07:
        # Keep raw for traceability, but present meaning.
        return DecodedSlow(
            msg_id=msg_id,
            name=name,
            raw=raw_value,
            value=0.0,
            unit="bar",
            text=f"X1 = 0 bar (raw=0x{raw_value:03X})",
        )

    if msg_id == 0x08:
        return DecodedSlow(
            msg_id=msg_id,
            name=name,
            raw=raw_value,
            value=30.0,
            unit="bar",
            text=f"X2 = 30 bar (raw=0x{raw_value:03X})",
        )

    # 0x09 / 0x0A: Pressure characteristic Y1/Y2 are DigitValues (12-bit) in the spec
    # Example values: Y1 = 0x0C8 (200), Y2 = 0xEFC (3836)
    if msg_id in (0x09, 0x0A):
        p = pressure_bar_from_digit_value(raw_value)
        label = "Y1" if msg_id == 0x09 else "Y2"
        return DecodedSlow(
            msg_id=msg_id,
            name=name,
            raw=raw_value,
            value=p,
            unit="bar",
            text=f"{label}: DigitValue={raw_value} -> {p:.3f} bar",
        )

    # Common "static info" IDs – give readable text
    if msg_id == 0x03:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"Sensor type = 0x{raw_value:03X}")
    if msg_id == 0x04:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"Manufacturer type = 0x{raw_value:03X}")
    if msg_id == 0x05:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"Manufacturer code = 0x{raw_value:03X}")
    if msg_id == 0x06:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"SENT standard revision = 0x{raw_value:03X}")

    # IDs used to compose serial/date
    if msg_id == 0x29:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"serial last3 = {raw_value:03d}")
    if msg_id == 0x2A:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"serial first3 = {raw_value:03d}")
    if msg_id == 0x2B:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"date last3 (cw/day) = {raw_value:03d}")
    if msg_id == 0x2C:
        return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"date first2 (year) = {raw_value:02d}")

    # fallback
    return DecodedSlow(msg_id=msg_id, name=name, raw=raw_value, text=f"0x{raw_value:X} ({raw_value})")


def combine_serial(first3: int, last3: int) -> str:
    return f"{first3:03d}{last3:03d}"


def decode_date_code(year_2digits: int, last3: int) -> str:
    # last3 = last 3 numerals of date code (cw, day) -> assume CW is two digits, day is one digit
    cw = last3 // 10
    day = last3 % 10
    return f"YY={year_2digits:02d}, CW={cw:02d}, D={day:d}"
