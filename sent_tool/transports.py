from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Optional, Protocol

import serial  # type: ignore


class Transport(Protocol):
    def read(self, n: int = 4096) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


@dataclass
class SerialTransport:
    port: str
    baud: int = 115200
    timeout: float = 0.2

    def __post_init__(self) -> None:
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)

    def read(self, n: int = 4096) -> bytes:
        return self._ser.read(n)

    def write(self, data: bytes) -> int:
        return self._ser.write(data)

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


@dataclass
class TcpTransport:
    host: str
    port: int = 8000
    timeout: float = 0.5

    def __post_init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))

    def read(self, n: int = 4096) -> bytes:
        try:
            return self._sock.recv(n)
        except socket.timeout:
            return b""

    def write(self, data: bytes) -> int:
        return self._sock.send(data)

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
