from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

STX = 0x02
ETX = 0x03


@dataclass(frozen=True)
class MachFrame:
    msg_id: int
    data: bytes
    checksum_ok: bool
    checksum: int
    raw: bytes  # full framed bytes (STX..ETX)


def calc_checksum(msg_id: int, datalen: int, data: bytes) -> int:
    # 1-byte sum of ID, DATALEN (2 bytes, LSB first) and all DATA bytes
    lsb = datalen & 0xFF
    msb = (datalen >> 8) & 0xFF
    s = (msg_id + lsb + msb + sum(data)) & 0xFF
    return s


def build_frame(msg_id: int, data: bytes) -> bytes:
    datalen = len(data)
    hdr = bytes([STX, msg_id, datalen & 0xFF, (datalen >> 8) & 0xFF])
    chksum = calc_checksum(msg_id, datalen, data)
    return hdr + data + bytes([chksum, ETX])


class MachStreamParser:
    """
    Streaming parser for Mach Systems STX/ETX framed protocol.
    Frame format: STX (1B) ID (1B) DATALEN (2B LSB first) DATA (N) CHECKSUM (1B) ETX (1B).
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> Iterable[MachFrame]:
        self._buf.extend(chunk)

        frames: list[MachFrame] = []

        while True:
            # search for STX
            try:
                stx_pos = self._buf.index(STX)
            except ValueError:
                self._buf.clear()
                break

            # discard leading noise
            if stx_pos > 0:
                del self._buf[:stx_pos]

            # need at least header: STX + ID + LEN(2)
            if len(self._buf) < 4:
                break

            msg_id = self._buf[1]
            datalen = self._buf[2] | (self._buf[3] << 8)

            total_len = 1 + 1 + 2 + datalen + 1 + 1  # STX + ID + LEN + DATA + CHK + ETX
            if len(self._buf) < total_len:
                break

            raw = bytes(self._buf[:total_len])
            # verify ETX
            if raw[-1] != ETX:
                # resync: drop first byte and try again
                del self._buf[0]
                continue

            data = raw[4 : 4 + datalen]
            chk = raw[4 + datalen]
            chk_calc = calc_checksum(msg_id, datalen, data)
            checksum_ok = (chk == chk_calc)

            frames.append(
                MachFrame(
                    msg_id=msg_id,
                    data=data,
                    checksum_ok=checksum_ok,
                    checksum=chk,
                    raw=raw,
                )
            )

            del self._buf[:total_len]

        return frames
