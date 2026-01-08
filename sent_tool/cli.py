from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Optional

from .live_decode import (
    MSG_SENT_START,
    MSG_SENT_STOP,
    decode_frame,
    enrich_state_from_slow_cache,
)
from .mach_protocol import MachStreamParser, build_frame
from .transports import SerialTransport, TcpTransport


def _parse_hostport(s: str) -> tuple[str, int]:
    if ":" not in s:
        return s, 8000
    host, port_s = s.rsplit(":", 1)
    return host, int(port_s)


def _print_human(decoded: dict, *, print_raw: bool = False) -> None:
    t = decoded.get("pc_time", "")
    typ = decoded.get("type", "other")
    ch = decoded.get("channel", "-")
    ts_us = decoded.get("timestamp_us")

    prefix = f"{t} ch={ch} {typ}"
    if ts_us is not None:
        prefix += f" ts_us={ts_us}"

    raw_suffix = ""
    if print_raw:
        # raw_data_hex is the message payload (not the whole framed packet)
        raw_suffix = f" raw_payload={decoded.get('raw_data_hex', '')} msg={decoded.get('msg_id_hex', '')}"

    if typ == "fast_rx":
        s = decoded.get("status_nibble")
        n = decoded.get("data_nibble_count")
        crc_ok = decoded.get("crc_ok")
        sensor = decoded.get("sensor") or {}
        p = sensor.get("pressure_bar")
        pv = sensor.get("digit_value")
        pst = sensor.get("pressure_state")
        msg = f"{prefix} status=0x{s:X} nibbles={n} crc_ok={crc_ok} digit={pv} p={p:.3f}bar state={pst}{raw_suffix}"
        print(msg)
        return

    if typ == "slow_rx":
        sid = decoded.get("slow_id_hex")
        d = decoded.get("decoded") or {}
        name = d.get("name")
        text = d.get("text")
        value = d.get("value")
        unit = d.get("unit")
        crc_ok = decoded.get("crc_ok")
        if value is not None and unit:
            print(f"{prefix} id={sid} {name}={value:.3f}{unit} crc_ok={crc_ok}{raw_suffix}")
        elif text:
            print(f"{prefix} id={sid} {name}: {text} crc_ok={crc_ok}{raw_suffix}")
        else:
            print(f"{prefix} id={sid} {name} raw={decoded.get('slow_raw')} crc_ok={crc_ok}{raw_suffix}")
        return

    if typ in ("fast_error", "slow_error"):
        print(f"{prefix} {decoded.get('errtype_text')} details={json.dumps(decoded, ensure_ascii=False)}{raw_suffix}")
        return

    print(f"{prefix} msg={decoded.get('msg_id_hex')} data={decoded.get('raw_data_hex')}{raw_suffix}")
    return


CSV_COLUMNS = [
    "pc_time",
    "type",
    "channel",
    "timestamp_us",
    "crc_ok",
    # FAST fields
    "status_nibble",
    "data_nibble_count",
    "data_nibbles",
    "digit_value",
    "pressure_bar",
    "pressure_state",
    "rolling_counter",
    "invert_ok",
    # SLOW fields
    "slow_id_hex",
    "slow_raw",
    "decoded_name",
    "decoded_value",
    "decoded_unit",
    "decoded_text",
    # ERROR fields
    "errtype_text",
    # raw (payload + msg id)
    "msg_id_hex",
    "raw_data_hex",
    # composed state (optional)
    "state_serial_number",
    "state_date_code",
]


def _row_for_csv(decoded: dict) -> dict:
    row = {k: "" for k in CSV_COLUMNS}
    row["pc_time"] = decoded.get("pc_time", "")
    row["type"] = decoded.get("type", "")
    row["channel"] = decoded.get("channel", "")
    row["timestamp_us"] = decoded.get("timestamp_us", "")
    row["crc_ok"] = decoded.get("crc_ok", "")

    row["msg_id_hex"] = decoded.get("msg_id_hex", "")
    row["raw_data_hex"] = decoded.get("raw_data_hex", "")

    if decoded.get("type") == "fast_rx":
        row["status_nibble"] = decoded.get("status_nibble", "")
        row["data_nibble_count"] = decoded.get("data_nibble_count", "")
        n = decoded.get("data_nibbles", [])
        row["data_nibbles"] = " ".join(str(x) for x in n) if isinstance(n, list) else str(n)

        sensor = decoded.get("sensor") or {}
        row["digit_value"] = sensor.get("digit_value", "")
        p = sensor.get("pressure_bar")
        row["pressure_bar"] = f"{p:.6f}" if isinstance(p, (int, float)) else ""
        row["pressure_state"] = sensor.get("pressure_state", "")
        row["rolling_counter"] = sensor.get("rolling_counter", "")
        row["invert_ok"] = sensor.get("invert_ok", "")

    elif decoded.get("type") == "slow_rx":
        row["slow_id_hex"] = decoded.get("slow_id_hex", "")
        row["slow_raw"] = decoded.get("slow_raw", "")
        d = decoded.get("decoded") or {}
        row["decoded_name"] = d.get("name", "")
        v = d.get("value")
        row["decoded_value"] = f"{v:.6f}" if isinstance(v, (int, float)) else ""
        row["decoded_unit"] = d.get("unit", "")
        row["decoded_text"] = d.get("text", "")

    elif decoded.get("type") in ("fast_error", "slow_error"):
        row["errtype_text"] = decoded.get("errtype_text", "")

    state = decoded.get("state") or {}
    if isinstance(state, dict):
        row["state_serial_number"] = state.get("serial_number", "")
        row["state_date_code"] = state.get("date_code", "")

    return row


def cmd_live(args: argparse.Namespace) -> int:
    if args.serial is None and args.tcp is None:
        print("ERROR: specify either --serial COMx or --tcp host:port", file=sys.stderr)
        return 2

    # Connect transport
    if args.serial:
        transport = SerialTransport(args.serial, baud=args.baud, timeout=0.2)
    else:
        host, port = _parse_hostport(args.tcp)
        transport = TcpTransport(host, port=port, timeout=0.5)

    parser = MachStreamParser()

    # Raw output (full framed packets, "as received")
    raw_fh = None
    raw_csv_writer = None
    if args.raw_out:
        raw_path = Path(args.raw_out)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if args.raw_format == "bin":
            raw_fh = raw_path.open("ab")
        elif args.raw_format in ("hex", "csv"):
            raw_fh = raw_path.open("a", newline="", encoding="utf-8")
            if args.raw_format == "csv":
                raw_csv_writer = csv.writer(raw_fh)
                raw_csv_writer.writerow(["pc_time_unix", "msg_id_hex", "len", "raw_hex"])
        else:
            print(f"ERROR: unknown raw format: {args.raw_format}", file=sys.stderr)
            return 2

    # Human CSV output
    out_csv_fh = None
    out_csv_writer = None
    if args.out_csv:
        out_path = Path(args.out_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_csv_fh = out_path.open("w", newline="", encoding="utf-8")
        out_csv_writer = csv.DictWriter(out_csv_fh, fieldnames=CSV_COLUMNS, delimiter=args.csv_sep)
        out_csv_writer.writeheader()

    # Start channel(s)
    if args.start:
        ch = 0xFF if args.all_channels else int(args.channel)
        transport.write(build_frame(MSG_SENT_START, bytes([ch])))

    start_t = time.time()
    seen = 0
    running_state: dict = {}

    try:
        while True:
            if args.duration is not None and (time.time() - start_t) >= float(args.duration):
                break
            if args.count is not None and seen >= int(args.count):
                break

            chunk = transport.read(4096)
            if not chunk:
                continue

            for frame in parser.feed(chunk):
                # write raw output (full framed packet)
                if raw_fh is not None:
                    if args.raw_format == "bin":
                        raw_fh.write(frame.raw)
                        raw_fh.flush()
                    else:
                        raw_hex = frame.raw.hex().upper()
                        if args.raw_format == "hex":
                            raw_fh.write(f"{time.time():.6f} 0x{frame.msg_id:02X} {len(frame.raw)} {raw_hex}\n")
                            raw_fh.flush()
                        elif args.raw_format == "csv" and raw_csv_writer is not None:
                            raw_csv_writer.writerow([time.time(), f"0x{frame.msg_id:02X}", len(frame.raw), raw_hex])
                            raw_fh.flush()

                decoded = decode_frame(
                    frame.msg_id,
                    frame.data,
                    swap_fast_data_nibbles=bool(args.swap_fast_data_nibbles),
                )
                enrich_state_from_slow_cache(running_state, decoded)

                if args.show_state and running_state:
                    decoded["state"] = dict(running_state)

                if out_csv_writer is not None:
                    out_csv_writer.writerow(_row_for_csv(decoded))
                    out_csv_fh.flush()

                if not args.quiet:
                    _print_human(decoded, print_raw=bool(args.print_raw))

                seen += 1

    except KeyboardInterrupt:
        pass
    finally:
        if args.stop_on_exit:
            ch = 0xFF if args.all_channels else int(args.channel)
            try:
                transport.write(build_frame(MSG_SENT_STOP, bytes([ch])))
            except Exception:
                pass

        try:
            transport.close()
        except Exception:
            pass

        if raw_fh is not None:
            try:
                raw_fh.close()
            except Exception:
                pass

        if out_csv_fh is not None:
            try:
                out_csv_fh.close()
            except Exception:
                pass

    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sent-tool", description="SENT CLI tool (Mach Systems SAE J2716 Interface)")
    sub = p.add_subparsers(dest="cmd", required=True)

    live = sub.add_parser("live", help="Read SENT frames directly from the Mach interface and print human-readable lines")
    live.add_argument("--serial", help="Serial port, e.g. COM7")
    live.add_argument("--tcp", help="TCP endpoint, e.g. 192.168.1.100:8000")
    live.add_argument("--baud", type=int, default=115200, help="Serial baud (default: 115200)")

    # NOTE: Mach channels are typically 0-based (0..3) even if GUI shows Channel 1..4
    live.add_argument("--channel", type=int, default=0, help="SENT channel index 0..3 (default: 0)")
    live.add_argument("--all-channels", action="store_true", help="Start/stop all channels (0xFF)")
    live.add_argument("--start", dest="start", action="store_true", default=True, help="Send SENT_START on connect (default)")
    live.add_argument("--no-start", dest="start", action="store_false", help="Do not send SENT_START (only listen)")
    live.add_argument("--stop-on-exit", action="store_true", help="Send SENT_STOP when exiting")

    live.add_argument("--duration", type=float, default=None, help="Stop after N seconds (default: run until Ctrl+C)")
    live.add_argument("--count", type=int, default=None, help="Stop after N received packets")

    # Raw logging (full framed packets)
    live.add_argument("--raw-out", default=None, help="Write RAW received framed packets to a file (as received)")
    live.add_argument("--raw-format", choices=["bin", "hex", "csv"], default="bin", help="RAW output format (default: bin)")
    live.add_argument("--swap-fast-data-nibbles", action="store_true", help="Swap nibbles within each byte for FAST data")

    # Human-readable CSV
    live.add_argument("--out-csv", default=None, help="Write human-readable decoded rows to CSV")
    live.add_argument("--csv-sep", default=",", help="CSV separator (default: , ; use ';' for German Excel)")

    # Console output controls
    live.add_argument("--quiet", action="store_true", help="Do not print to console (useful with --raw-out/--out-csv)")
    live.add_argument("--print-raw", action="store_true", help="Also print raw payload hex to console (default: human only)")
    live.add_argument("--show-state", action="store_true", help="Include composed state (serial/date code) in CSV/console when available")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    if args.cmd == "live":
        return cmd_live(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
