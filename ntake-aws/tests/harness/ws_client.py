"""A minimal receive-only WebSocket client (stdlib) for the Tier-2 nudge test.

The live-sync channel is server→client only (the client never sends — AWS_LLD
§4.1), so the integration test needs just: a TLS connection, the HTTP/1.1
``Upgrade`` handshake (RFC 6455 §4.1), and reading the server's **unmasked** text
frames (§5.2). That is a few dozen stdlib lines — no third-party dependency.
Pings are answered with a pong so a long wait doesn't get the socket closed.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.parse import urlsplit

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455 handshake constant
_OP_TEXT, _OP_CLOSE, _OP_PING, _OP_PONG = 0x1, 0x8, 0x9, 0xA


class WebSocketClosed(Exception):
    """The server closed the socket (or the handshake was refused)."""


class ReceiveOnlyWebSocket:
    """Connect to a ``wss://`` URL and read text messages until closed."""

    def __init__(self, url: str, *, timeout: float = 10.0) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port or 443
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        raw = socket.create_connection((host, port), timeout=timeout)
        self._sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self._sock.settimeout(timeout)
        self._pending = b""
        key = base64.b64encode(os.urandom(16)).decode()
        self._sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        status_line, headers = self._read_http_headers()
        if " 101 " not in f"{status_line} ":
            raise WebSocketClosed(f"handshake refused: {status_line}")
        expected = base64.b64encode(
            hashlib.sha1((key + _GUID).encode()).digest()  # noqa: S324 — RFC 6455
        ).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise WebSocketClosed("handshake accept key mismatch")

    def receive_text(self) -> str:
        """Block (up to the socket timeout) for the next text message."""
        while True:
            opcode, payload = self._read_frame()
            if opcode == _OP_TEXT:
                return payload.decode("utf-8")
            if opcode == _OP_PING:
                self._send_control(_OP_PONG, payload)
            elif opcode == _OP_CLOSE:
                raise WebSocketClosed("server closed the socket")

    def close(self) -> None:
        try:
            self._send_control(_OP_CLOSE, b"")
        except OSError:
            pass
        self._sock.close()

    # --- framing -------------------------------------------------------------

    def _read_http_headers(self) -> tuple[str, dict[str, str]]:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(1024)
            if not chunk:
                raise WebSocketClosed("connection closed during handshake")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        self._pending = rest
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return lines[0], headers

    def _recv_exact(self, n: int) -> bytes:
        out = self._pending[:n]
        self._pending = self._pending[n:]
        while len(out) < n:
            chunk = self._sock.recv(n - len(out))
            if not chunk:
                raise WebSocketClosed("connection closed mid-frame")
            out += chunk
        return out

    def _read_frame(self) -> tuple[int, bytes]:
        b0, b1 = self._recv_exact(2)
        opcode = b0 & 0x0F
        length = b1 & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", self._recv_exact(2))
        elif length == 127:
            (length,) = struct.unpack("!Q", self._recv_exact(8))
        mask = self._recv_exact(4) if b1 & 0x80 else None
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        return opcode, payload

    def _send_control(self, opcode: int, payload: bytes) -> None:
        # Client→server frames must be masked (RFC 6455 §5.3).
        mask = os.urandom(4)
        masked = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        self._sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)
