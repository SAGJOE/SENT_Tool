from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from .sensor_803405 import (
    pressure_bar_from_digit_value,
    pressure_state_from_digit_value,
    temperature_c_from_tval,
    diag_text,
    combine_serial,
    decode_date_code,
)

def _parse_timestamp_to_seconds(series: pd.Series) -> pd.Series:
    try:
        return pd.to_timedelta(series).dt.total_seconds()
    except Exception:
        return pd.Series([np.nan] * len(series), index=series.index)

def _hex_to_bytes(hex_str: str) -> List[int]:
    s = str(hex_str).strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    if len(s) % 2 == 1:
        s = "0" + s
    return [int(s[i:i+2], 16) for i in range(0, len(s), 2)]

def _split_ints(cell: Any) -> List[int]:
    if cell is None or (isinstance(cell, float) and np.isnan(cell)):
        return []
    text = str(cell).strip()
    parts = re.split(r"[,\s;]+", text)
    out = []
    for p in parts:
        if p != "":
            out.append(int(p))
    return out

def _extract_fast_nibbles(row: pd.Series) -> List[int]:
    # Prefer hex field from Mach export
    if "FastDataNibbles" in row and pd.notna(row["FastDataNibbles"]):
        bs = _hex_to_bytes(row["FastDataNibbles"])
        return [b & 0xF for b in bs]  # each nibble stored as byte -> take low nibble

    # Fallback: some exports have "Data" like "0 12 10 10 2 15"
    if "Data" in row and pd.notna(row["Data"]):
        return _split_ints(row["Data"])

    return []

def decode_fast_frames(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    # Filter only valid fast frames if FrameType exists
    if "FrameType" in df.columns:
        fast = df[df["FrameType"].astype(str).str.lower().eq("fast")].copy()
    else:
        fast = df.copy()

    if fast.empty:
        return pd.DataFrame()

    ts_col = "Timestamp" if "Timestamp" in fast.columns else ("Time" if "Time" in fast.columns else None)
    if ts_col is None:
        fast["t_s"] = np.nan
        fast["Timestamp"] = ""
    else:
        fast["t_s"] = _parse_timestamp_to_seconds(fast[ts_col])
        if ts_col != "Timestamp":
            fast["Timestamp"] = fast[ts_col].astype(str)

    fast["nibbles"] = fast.apply(_extract_fast_nibbles, axis=1)

    def _decode_row(n: List[int]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[bool]]:
        # Sensor #803405 expects 6 nibbles:
        # n1..n3 DigitValue (12 bit), n4..n5 rolling counter (8 bit), n6 inverted MSB nibble
        if not isinstance(n, list) or len(n) < 6:
            return (None, None, None, None)
        digit = (n[0] << 8) | (n[1] << 4) | n[2]
        rc = (n[3] << 4) | n[4]
        inv = n[5]
        inv_ok = inv == ((~n[0]) & 0xF)
        return (digit, rc, inv, inv_ok)

    fast[["digit_value", "rolling_counter", "inv_msb_nibble", "inv_ok"]] = fast["nibbles"].apply(
        lambda n: pd.Series(_decode_row(n))
    )

    fast["pressure_bar"] = fast["digit_value"].apply(
        lambda d: np.nan if d is None else pressure_bar_from_digit_value(int(d))
    )
    fast["pressure_state"] = fast["digit_value"].apply(
        lambda d: "" if d is None else pressure_state_from_digit_value(int(d))
    )

    keep = []
    for c in ["t_s", "Timestamp", "ChannelId", "Direction", "FastStatus", "CrcReceived", "CrcCalculated", "FastDataNibbles"]:
        if c in fast.columns:
            keep.append(c)

    out = fast[keep].copy()
    out["nibbles"] = fast["nibbles"]
    out["digit_value"] = fast["digit_value"]
    out["pressure_bar"] = fast["pressure_bar"]
    out["pressure_state"] = fast["pressure_state"]
    out["rolling_counter"] = fast["rolling_counter"]
    out["inv_msb_nibble"] = fast["inv_msb_nibble"]
    out["inv_ok"] = fast["inv_ok"]
    return out

def _parse_id(val: Any) -> Optional[int]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s)

def decode_slow_frames(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    id_col = None
    data_col = None
    for cand in ["Id", "ID", "Slow Id", "SlowId", "MessageId", "Message ID"]:
        if cand in df.columns:
            id_col = cand
            break
    for cand in ["Data", "DATA", "SlowData", "Slow Data"]:
        if cand in df.columns:
            data_col = cand
            break
    ts_col = "Timestamp" if "Timestamp" in df.columns else ("Time" if "Time" in df.columns else None)

    if id_col is None or data_col is None or ts_col is None:
        return pd.DataFrame()

    slow = df.copy()
    slow["t_s"] = _parse_timestamp_to_seconds(slow[ts_col])
    slow["msg_id"] = slow[id_col].apply(_parse_id)

    # Data appears as two bytes in decimal: "LSB MSB" (Intel)
    def _value_from_data(cell: Any) -> Optional[int]:
        parts = _split_ints(cell)
        if len(parts) == 0:
            return None
        if len(parts) == 1:
            return int(parts[0])
        return int(parts[0] + (parts[1] << 8))

    slow["raw_value"] = slow[data_col].apply(_value_from_data)

    slow["name"] = ""
    slow["value_eng"] = np.nan
    slow["unit"] = ""
    slow["text"] = ""

    def _apply_decode(row: pd.Series) -> pd.Series:
        mid = row["msg_id"]
        v = row["raw_value"]
        if mid is None or v is None:
            return row
        mid = int(mid)
        v = int(v)

        if mid == 0x01:
            row["name"] = "DiagnosticCode"
            row["value_eng"] = v
            row["text"] = diag_text(v)
            return row

        if mid == 0x23:
            row["name"] = "InternalTemperature"
            row["value_eng"] = temperature_c_from_tval(v)
            row["unit"] = "°C"
            return row

        if mid == 0x29:
            row["name"] = "SensorID_last3"
            row["value_eng"] = v
            return row
        if mid == 0x2A:
            row["name"] = "SensorID_first3"
            row["value_eng"] = v
            return row
        if mid == 0x2B:
            row["name"] = "DateCode_cw_day"
            row["value_eng"] = v
            return row
        if mid == 0x2C:
            row["name"] = "DateCode_year"
            row["value_eng"] = v
            return row

        row["name"] = f"Unknown_0x{mid:02X}"
        row["value_eng"] = v
        return row

    slow = slow.apply(_apply_decode, axis=1)

    out = slow.copy()
    out["msg_id"] = out["msg_id"].apply(lambda x: "" if x is None else f"0x{int(x):02X}")
    return out

def merge_fast_with_slow(fast_dec: pd.DataFrame, slow_dec: pd.DataFrame) -> pd.DataFrame:
    if fast_dec.empty:
        return fast_dec

    out = fast_dec.sort_values("t_s").copy()
    if slow_dec is None or slow_dec.empty:
        out["internal_temp_c"] = np.nan
        out["diag_code"] = np.nan
        out["diag_text"] = ""
        out["serial_number"] = ""
        out["date_code_str"] = ""
        return out

    slow = slow_dec.sort_values("t_s").copy()
    pivot_val = slow.pivot_table(index="t_s", columns="name", values="value_eng", aggfunc="last").sort_index()
    pivot_txt = slow.pivot_table(index="t_s", columns="name", values="text", aggfunc="last").sort_index()

    merged = pd.merge_asof(out, pivot_val.reset_index(), on="t_s", direction="backward")
    merged = pd.merge_asof(merged, pivot_txt.reset_index(), on="t_s", direction="backward", suffixes=("", "_text"))

    merged["internal_temp_c"] = merged.get("InternalTemperature", np.nan)
    merged["diag_code"] = merged.get("DiagnosticCode", np.nan)
    merged["diag_text"] = merged.get("DiagnosticCode_text", "")
    merged["diag_text"] = merged["diag_text"].fillna("")

    a = merged.get("SensorID_first3", np.nan)
    b = merged.get("SensorID_last3", np.nan)
    merged["serial_number"] = [
        "" if (pd.isna(x) or pd.isna(y)) else combine_serial(int(x), int(y))
        for x, y in zip(a, b)
    ]

    y = merged.get("DateCode_year", np.nan)
    cw = merged.get("DateCode_cw_day", np.nan)
    merged["date_code_str"] = [
        "" if (pd.isna(x) or pd.isna(z)) else decode_date_code(int(x), int(z))["date_code_str"]
        for x, z in zip(y, cw)
    ]
    return merged

def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)
