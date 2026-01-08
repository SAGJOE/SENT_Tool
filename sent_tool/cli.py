from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .decode_mach_csv import decode_fast_frames, decode_slow_frames, load_csv, merge_fast_with_slow


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sent-tool",
        description="Decode Mach SAE J2716 Interface CSV exports into human-readable engineering values (sensor #803405).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decode", help="Decode fast and/or slow CSV and write decoded CSV.")
    d.add_argument("--fast", type=str, required=False, help="Path to Mach 'Data Trace' CSV export (Fast Channel).")
    d.add_argument("--slow", type=str, required=False, help="Path to Mach 'Slow Data Trace' CSV export.")
    d.add_argument("-o", "--out", type=str, required=True, help="Output CSV path.")
    d.add_argument("--out-slow", type=str, required=False, help="Optional: also write decoded slow events CSV.")
    d.add_argument("--out-fast", type=str, required=False, help="Optional: also write decoded fast frames CSV.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "decode":
        if not args.fast and not args.slow:
            print("ERROR: Provide at least --fast or --slow", file=sys.stderr)
            return 2

        fast_df = pd.DataFrame()
        slow_df = pd.DataFrame()

        if args.fast:
            fast_df = load_csv(args.fast)
        if args.slow:
            slow_df = load_csv(args.slow)

        fast_dec = decode_fast_frames(fast_df) if not fast_df.empty else pd.DataFrame()
        slow_dec = decode_slow_frames(slow_df) if not slow_df.empty else pd.DataFrame()

        merged = merge_fast_with_slow(fast_dec, slow_dec)

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_csv(out_path, index=False, sep=";", decimal=",")

        if args.out_fast and not fast_dec.empty:
            Path(args.out_fast).parent.mkdir(parents=True, exist_ok=True)
            fast_dec.to_csv(args.out_fast, index=False)

        if args.out_slow and not slow_dec.empty:
            Path(args.out_slow).parent.mkdir(parents=True, exist_ok=True)
            slow_dec.to_csv(args.out_slow, index=False)

        print(f"OK: wrote {out_path}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
