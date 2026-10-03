#!/usr/bin/env python3
"""⚠️ THROWAWAY Session-1.5 WebSocket post-back check (deleted with the tracer). ⚠️

No websocat / wscat / pip install needed — raw stdlib: a TLS socket, a hand-rolled
RFC 6455 handshake, and one frame read. Connects to the tracer WebSocket $connect
(unauthenticated in the tracer) and prints the single hard-coded nudge the server
posts back, proving the API-GW → $connect → postToConnection loop (AWS_HLD §8).

Run:  .venv/bin/python scripts/ws_check.py
"""

from __future__ import annotations

import base64
import os
import socket
import ssl

HOST = "4n0hoilz7i.execute-api.us-east-1.amazonaws.com"
PATH = "/dev"  # the WebSocket stage
PORT = 443


def _decode_text_frame(data: bytes) -> str:
    """Minimal RFC 6455 unmasked server text-frame decode (len < 65536)."""
    if len(data) < 2:
        return ""
    length = data[1] & 0x7F
    idx = 2
    if length == 126:
        length = int.from_bytes(data[2:4], "big")
        idx = 4
    return data[idx : idx + length].decode("utf-8", "replace")


def main() -> None:
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET {PATH} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    ctx = ssl.create_default_context()
    with socket.create_connection((HOST, PORT), timeout=15) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST) as s:
            s.sendall(handshake.encode())
            resp = s.recv(4096)
            status = resp.split(b"\r\n", 1)[0].decode("latin1")
            print("handshake:", status)
            if b"101" not in resp.split(b"\r\n", 1)[0]:
                print("full response:\n", resp.decode("latin1", "replace")[:500])
                return
            # Read the server's post-back frame (the hard-coded nudge).
            s.settimeout(10)
            try:
                frame = s.recv(4096)
                print("post-back:", _decode_text_frame(frame))
            except TimeoutError:
                print("post-back: (none received within 10s)")


if __name__ == "__main__":
    main()
