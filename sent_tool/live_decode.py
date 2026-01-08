from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from typing import Any, Optional

from .sensor_803405 import (
    combine_serial,
    decode_date_code,
    decode_slow_value,
    pressure_bar_from_digit_value,
    pressure_state_from_digit_value,
)

# Mach protocol message IDs (relevant for reception)
MSG_FAST_RX = 0x95
MSG_SLOW_RX = 0x96
MSG_FAST_ERR = 0x97
MSG_SLOW_ERR = 0x98

# Start/stop channel
MSG_SENT_START = 0x74
MSG_SENT_STOP = 0x75

FAST_ERRTYPE_TEXT = {
    0: "CRC mismatch",
    1: "Framing error (nibble length out of range)",
    2: "Adjacent sync error",
    3: "SENT bus error (wrong sync)",
}

SLOW_ERRTYPE_TEXT = {
    0: "CRC",
    1: "Framing",
    2: "Sync",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _has_timestamp(total_len: int, base_len: int) -> bool:
    # base_len = length without timestamp
    return total_len == base_len + 8


def _decode_fast_nibbles(data_bytes: bytes, swap_within_byte: bool) -> list[int]:
    nibbles: list[int] = []
    for b in data_bytes:
        lo = b & 0x0F
        hi = (b >> 4) & 0x0F
        if swap_within_byte:
            # swapped order inside byte
            nibbles.extend([hi, lo])  # nibble0 in hi, nibble1 in lo
        else:
            nibbles.extend([lo, hi])  # nibble0 in lo, nibble1 in hi
    return nibbles


def decode_frame(msg_id: int, data: bytes, *, swap_fast_data_nibbles: bool = False) -> dict[str, Any]:
    """
    Returns a dict suitable for printing or JSON logging.
    """
    out: dict[str, Any] = {
        "pc_time": now_iso(),
        "msg_id": msg_id,
        "msg_id_hex": f"0x{msg_id:02X}",
        "raw_data_hex": data.hex().upper(),
    }

    if msg_id == MSG_FAST_RX:
        if len(data) < 3:
            out["type"] = "fast_rx"
            out["error"] = "payload too short"
            return out

        channel = data[0]
        status_count = data[1]
        status = status_count & 0x0F
        nibblecnt = (status_count >> 4) & 0x0F

        data_byte_count = int(ceil(nibblecnt / 2.0))
        base_len_no_ts = 2 + data_byte_count + 1  # ch + status_count + data_bytes + crc
        has_ts = _has_timestamp(len(data), base_len_no_ts)

        crc_index = 2 + data_byte_count
        if len(data) < base_len_no_ts:
            out["type"] = "fast_rx"
            out["error"] = "payload length mismatch"
            return out

        data_bytes = data[2:crc_index]
        crc_byte = data[crc_index]
        ts_us: Optional[int] = None
        if has_ts:
            ts_us = int.from_bytes(data[-8:], "little", signed=False)

        crc_rx = crc_byte & 0x0F
        crc_calc = (crc_byte >> 4) & 0x0F

        nibbles = _decode_fast_nibbles(data_bytes, swap_fast_data_nibbles)[:nibblecnt]

        # Sensor-specific (803405): first 3 nibbles form 12-bit digit value
        sensor: dict[str, Any] = {}
        if len(nibbles) >= 3:
            digit_value = (nibbles[0] << 8) | (nibbles[1] << 4) | nibbles[2]
            sensor["digit_value"] = digit_value
            sensor["pressure_bar"] = pressure_bar_from_digit_value(digit_value)
            sensor["pressure_state"] = pressure_state_from_digit_value(digit_value)

        # Rolling counter / invert (if present)
        if len(nibbles) >= 5:
            sensor["rolling_counter"] = (nibbles[3] << 4) | nibbles[4]
        if len(nibbles) >= 6:
            sensor["invert_nibble"] = nibbles[5]
            sensor["invert_ok"] = (nibbles[5] == ((~nibbles[0]) & 0x0F))

        out.update(
            {
                "type": "fast_rx",
                "channel": channel,
                "status_nibble": status,
                "data_nibble_count": nibblecnt,
                "data_nibbles": nibbles,
                "crc_rx": crc_rx,
                "crc_calc": crc_calc,
                "crc_ok": (crc_rx == crc_calc),
                "timestamp_us": ts_us,
                "sensor": sensor,
            }
        )
        return out

    if msg_id == MSG_SLOW_RX:
        # channel, msg_id, data_lsb, data_msb, frame_info, crc_calc, [timestamp 8]
        if len(data) < 6:
            out["type"] = "slow_rx"
            out["error"] = "payload too short"
            return out

        channel = data[0]
        slow_id = data[1]
        raw_val = data[2] | (data[3] << 8)
        frame_info = data[4]
        crc_calc = data[5] & 0x3F

        base_len_no_ts = 6
        has_ts = _has_timestamp(len(data), base_len_no_ts)
        ts_us: Optional[int] = None
        if has_ts:
            ts_us = int.from_bytes(data[-8:], "little", signed=False)

        fmt = (frame_info >> 7) & 0x01
        frametype = (frame_info >> 6) & 0x01
        crc_rx = frame_info & 0x3F

        decoded = decode_slow_value(slow_id, raw_val)

        out.update(
            {
                "type": "slow_rx",
                "channel": channel,
                "slow_id": slow_id,
                "slow_id_hex": f"0x{slow_id:02X}",
                "slow_raw": raw_val,
                "format_bit": fmt,
                "frame_type": "enhanced" if frametype == 1 else "short",
                "crc_rx": crc_rx,
                "crc_calc": crc_calc,
                "crc_ok": (crc_rx == crc_calc),
                "timestamp_us": ts_us,
                "decoded": {
                    "name": decoded.name,
                    "raw": decoded.raw,
                    "text": decoded.text,
                    "value": decoded.value,
                    "unit": decoded.unit,
                },
            }
        )
        return out

    if msg_id == MSG_FAST_ERR:
        if len(data) < 2:
            out["type"] = "fast_error"
            out["error"] = "payload too short"
            return out

        channel = data[0]
        err = data[1]
        errtype = (err >> 4) & 0x03  # bits [5:4]
        frmerrcode = err & 0x0F

        base_len_no_ts = 2
        has_ts = _has_timestamp(len(data), base_len_no_ts)
        ts_us: Optional[int] = None
        if has_ts:
            ts_us = int.from_bytes(data[-8:], "little", signed=False)

        out.update(
            {
                "type": "fast_error",
                "channel": channel,
                "errtype": errtype,
                "errtype_text": FAST_ERRTYPE_TEXT.get(errtype, f"Unknown({errtype})"),
                "framing_error_code": frmerrcode,
                "timestamp_us": ts_us,
            }
        )
        return out

    if msg_id == MSG_SLOW_ERR:
        if len(data) < 2:
            out["type"] = "slow_error"
            out["error"] = "payload too short"
            return out

        channel = data[0]
        err = data[1]
        errtype = (err >> 4) & 0x03  # bits [5:4]

        base_len_no_ts = 2
        has_ts = _has_timestamp(len(data), base_len_no_ts)
        ts_us: Optional[int] = None
        if has_ts:
            ts_us = int.from_bytes(data[-8:], "little", signed=False)

        out.update(
            {
                "type": "slow_error",
                "channel": channel,
                "errtype": errtype,
                "errtype_text": SLOW_ERRTYPE_TEXT.get(errtype, f"Unknown({errtype})"),
                "timestamp_us": ts_us,
            }
        )
        return out

    out["type"] = "other"
    return out


def enrich_state_from_slow_cache(state: dict[str, Any], decoded: dict[str, Any]) -> None:
    """
    Optional: If you want to keep running state (serial/date) while printing,
    you can store parts of slow messages and compose later.
    """
    if decoded.get("type") != "slow_rx":
        return
    d = decoded.get("decoded") or {}
    sid = decoded.get("slow_id")

    if sid == 0x29:
        state["serial_last3"] = decoded.get("slow_raw")
    elif sid == 0x2A:
        state["serial_first3"] = decoded.get("slow_raw")
    elif sid == 0x2B:
        state["date_last3"] = decoded.get("slow_raw")
    elif sid == 0x2C:
        state["date_first2"] = decoded.get("slow_raw")

    if "serial_first3" in state and "serial_last3" in state:
        state["serial_number"] = combine_serial(state["serial_first3"], state["serial_last3"])

    if "date_first2" in state and "date_last3" in state:
        state["date_code"] = decode_date_code(state["date_first2"], state["date_last3"])
