"""
Sensor definition for i2s Dresden #803405 (IPT1866 30 bar new).

Sources (your PDFs):
- Transfer function: p_rel/bar = 0.00825 * DigitValue - 1.65
- Fast Channel data: 6 nibbles total
  - DigitValue: 12-bit (n1..n3)
  - Rolling Counter: 8-bit (n4..n5)
  - n6: inverted MSB-nibble of DigitValue
- Enhanced serial messages (Slow Channel IDs) + diagnostic code table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# -------- Diagnostics mapping (Slow ID 0x01) --------
DIAG_CODE_TEXT = {
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


@dataclass(frozen=True)
class Sensor803405Config:
    pressure_multiplier: float = 0.00825
    pressure_offset: float = -1.65
    temp_multiplier: float = 0.125
    temp_offset: float = -73.15


CFG = Sensor803405Config()


def pressure_bar_from_digit_value(digit_value: int) -> float:
    return CFG.pressure_multiplier * digit_value + CFG.pressure_offset


def temperature_c_from_tval(tval: int) -> float:
    return CFG.temp_multiplier * tval + CFG.temp_offset


def diag_text(code: Optional[int]) -> str:
    if code is None:
        return ""
    return DIAG_CODE_TEXT.get(code, f"Unknown diagnostic code 0x{code:03X}")


def pressure_state_from_digit_value(d: int) -> str:
    # Based on spec: 0 init, 4090 error, 4088 high clamp, <=1 low clamp
    if d == 0:
        return "Initialization"
    if d == 4090:
        return "ErrorCode"
    if d >= 4088 and d < 4090:
        return "HighClamp"
    if d <= 1:
        return "LowClamp"
    return "OK"


def combine_serial(first3: Optional[int], last3: Optional[int]) -> str:
    # Spec: 0x2A first 3 numerals, 0x29 last 3 numerals
    if first3 is None or last3 is None:
        return ""
    return f"{int(first3):03d}{int(last3):03d}"


def decode_date_code(year2: Optional[int], cw_day: Optional[int]) -> dict:
    """
    Spec says:
      - 0x2B: last 3 numerals of date code (cw, day)
      - 0x2C: first 2 numerals of date code (year)

    We interpret cw_day as:
      cw = cw_day // 10 (00..99)
      day = cw_day % 10  (0..9)  (often day-of-week 1..7)
    """
    out = {
        "date_code_raw": "",
        "year_2digit": None,
        "calendar_week": None,
        "day_in_week": None,
        "date_code_str": "",
    }
    if year2 is None or cw_day is None:
        return out

    year2 = int(year2)
    cw_day = int(cw_day)

    cw = cw_day // 10
    day = cw_day % 10

    out["year_2digit"] = year2
    out["calendar_week"] = cw
    out["day_in_week"] = day
    out["date_code_raw"] = f"{year2:02d}{cw_day:03d}"
    out["date_code_str"] = f"20{year2:02d}-CW{cw:02d}-D{day}"
    return out
