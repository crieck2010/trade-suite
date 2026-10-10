"""Transports: a minimal RFC 6455 WebSocket client and a REST-polling fallback.

Both transports expose the same interface so sources degrade gracefully::

    transport.connect()
    for raw in transport.iter_messages():
        ...
    transport.close()

``WebSocketTransport`` is a deliberately *minimal* WebSocket client built on
``socket`` + ``ssl`` from the standard library: opening handshake with
``Sec-WebSocket-Accept`` validation, text/binary frames, client-side masking
(RFC 6455 section 5.3 requires clients to mask), fragmentation reassembly,
ping/pong keepalive, and the close handshake. It is NOT a hardened
networking library: no compression extensions, no proxy support, no
subprotocol negotiation, and only the opcodes we need. See
``docs/METHODOLOGY.md`` for what is and isn't covered.

``PollingTransport`` wraps a ``fetch_fn() -> list[raw]`` callable (typically
a REST endpoint) behind the same interface, with de-duplication, so a source
keeps working when its WebSocket endpoint is unavailable.

Threading: one reader thread per stream. ``iter_messages()`` itself is a
blocking generator; :mod:`trade_stream.runner` runs it on a dedicated thread
and never blocks it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlparse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketError(Exception):
    """Base error for transport failures."""


class HandshakeError(WebSocketError):
    """The opening handshake failed (bad status or bad Accept key)."""


class StaleConnectionError(WebSocketError):
    """No frames and no pong arrived within the staleness window."""


def _encode_frame(opcode: int, payload: bytes, *, mask: bool, fin: bool = True) -> bytes:
    first = (0x80 if fin else 0x00) | (opcode & 0x0F)
    mask_bit = 0x80 if mask else 0x00
    n = len(payload)
    if n < 126:
        header = struct.pack("!BB", first, mask_bit | n)
    elif n < 0x10000:
        header = struct.pack("!BBH", first, mask_bit | 126, n)
    else:
        header = struct.pack("!BBQ", first, mask_bit | 127, n)
    if not mask:
        return header + payload
    key = os.urandom(4)
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return header + key + masked


class _Reader:
    """Buffered exact-reader over a socket (handshake leftovers stay usable)."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def read_exactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise WebSocketError("connection closed by peer")
            self._buf += chunk
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def read_until(self, delim: bytes, limit: int = 65536) -> bytes:
        while delim not in self._buf:
            if len(self._buf) > limit:
                raise HandshakeError("handshake response too large")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise HandshakeError("connection closed during handshake")
            self._buf += chunk
        idx = self._buf.index(delim) + len(delim)
        out = bytes(self._buf[:idx])
        del self._buf[:idx]
        return out


def _decode_frame(reader: _Reader) -> tuple[bool, int, bytes]:
    hdr = reader.read_exactly(2)
    b1, b2 = hdr[0], hdr[1]
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", reader.read_exactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", reader.read_exactly(8))[0]
    key = reader.read_exactly(4) if masked else b""
    payload = reader.read_exactly(length) if length else b""
    if masked:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload


class WebSocketTransport:
    """Minimal RFC 6455 client. One instance = one connection.

    Pass ``_sock`` only in tests to inject an already-connected socket
    (e.g. one end of :func:`socket.socketpair`); the handshake still runs
    over it.
    """

    def __init__(
        self,
        url: str,
        headers: dict | None = None,
        timeout: float = 10.0,
        _sock: socket.socket | None = None,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self._injected = _sock
        self._sock: socket.socket | None = None
        self._reader: _Reader | None = None
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self.last_recv_ts = 0.0
        self.last_pong_ts = 0.0

    # -- lifecycle -----------------------------------------------------
    def connect(self) -> None:
        if self._injected is not None:
            self._sock = self._injected
        else:
            parts = urlparse(self.url)
            if parts.scheme not in ("ws", "wss"):
                raise WebSocketError(f"unsupported scheme: {parts.scheme}")
            host, port = parts.hostname, parts.port or (443 if parts.scheme == "wss" else 80)
            raw = socket.create_connection((host, port), timeout=self.timeout)
            if parts.scheme == "wss":
                ctx = ssl.create_default_context()
                self._sock = ctx.wrap_socket(raw, server_hostname=host)
            else:
                self._sock = raw
        self._sock.settimeout(self.timeout)
        self._reader = _Reader(self._sock)
        self._handshake()
        now = time.time()
        self.last_recv_ts = now
        self.last_pong_ts = now
        self._stop.clear()

    def _handshake(self) -> None:
        assert self._sock is not None and self._reader is not None
        parts = urlparse(self.url)
        key = base64.b64encode(os.urandom(16)).decode()
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        lines = [
            f"GET {target} HTTP/1.1",
            f"Host: {parts.hostname}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for hk, hv in self.headers.items():
            lines.append(f"{hk}: {hv}")
        lines += ["", ""]
        self._sock.sendall("\r\n".join(lines).encode())
        raw = self._reader.read_until(b"\r\n\r\n").decode("latin-1")
        head, _, _ = raw.partition("\r\n\r\n")
        status, _, rest = head.partition("\r\n")
        if "101" not in status.split(" ", 2)[1:2]:
            raise HandshakeError(f"handshake failed: {status.strip()}")
        accept = None
        for line in rest.split("\r\n"):
            name, _, value = line.partition(":")
            if name.strip().lower() == "sec-websocket-accept":
                accept = value.strip()
        expected = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()
        ).decode()
        if accept != expected:
            raise HandshakeError("bad Sec-WebSocket-Accept from server")

    def close(self, code: int = 1000) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._send_frame(OP_CLOSE, struct.pack("!H", code), mask=True)
            except OSError:
                pass
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    # -- framing -------------------------------------------------------
    def _send_frame(self, opcode: int, payload: bytes, mask: bool = True) -> None:
        assert self._sock is not None
        with self._send_lock:
            self._sock.sendall(_encode_frame(opcode, payload, mask=mask))

    def send_text(self, text: str) -> None:
        self._send_frame(OP_TEXT, text.encode("utf-8"), mask=True)

    def ping(self, payload: bytes = b"") -> None:
        self._send_frame(OP_PING, payload, mask=True)

    def iter_messages(self, stale_after: float | None = None):
        """Yield decoded messages. Handles fragmentation, ping/pong, close.

        Text frames yield ``str``; binary frames yield ``bytes``. Raises
        :class:`StaleConnectionError` when no frame *and* no pong arrives
        within ``stale_after`` seconds.
        """
        assert self._reader is not None
        fragments: list[bytes] = []
        frag_opcode: int | None = None
        while not self._stop.is_set():
            try:
                fin, opcode, payload = _decode_frame(self._reader)
            except socket.timeout:
                if stale_after is not None and (
                    time.time() - self.last_recv_ts > stale_after
                ):
                    raise StaleConnectionError(
                        f"no data for {stale_after:.0f}s; reconnecting"
                    )
                continue
            self.last_recv_ts = time.time()
            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload, mask=True)
                continue
            if opcode == OP_PONG:
                self.last_pong_ts = time.time()
                continue
            if opcode == OP_CLOSE:
                try:
                    self._send_frame(OP_CLOSE, payload, mask=True)
                except OSError:
                    pass
                return
            if opcode == OP_CONT:
                if frag_opcode is None:
                    continue  # stray continuation; ignore
                fragments.append(payload)
                if fin:
                    data = b"".join(fragments)
                    done_opcode = frag_opcode
                    fragments, frag_opcode = [], None
                    yield self._decode_data(done_opcode, data)
                continue
            if opcode in (OP_TEXT, OP_BIN):
                if fin:
                    yield self._decode_data(opcode, payload)
                else:
                    fragments, frag_opcode = [payload], opcode
                continue
            # unknown opcode: ignore per robustness principle

    @staticmethod
    def _decode_data(opcode: int, data: bytes):
        if opcode == OP_TEXT:
            return data.decode("utf-8")
        return data


class PollingTransport:
    """REST-polling fallback behind the WebSocket interface.

    ``fetch_fn`` is a zero-argument callable returning a list of raw
    messages (e.g. ``lambda: requests.get(url).json()`` — any HTTP client
    works; stdlib ``urllib`` keeps it dependency-free). Messages are
    de-duplicated by ``dedupe_key`` so re-polls don't double-deliver.
    """

    def __init__(
        self,
        fetch_fn,
        interval: float = 5.0,
        dedupe_key=None,
        history: int = 1000,
    ) -> None:
        self._fetch = fetch_fn
        self.interval = interval
        self._dedupe_key = dedupe_key or (
            lambda m: json.dumps(m, sort_keys=True, default=str)
        )
        self._seen: list = []
        self._seen_set: set = set()
        self._history = history
        self._stop = threading.Event()

    def connect(self) -> None:
        self._stop.clear()

    def close(self) -> None:
        self._stop.set()

    def _is_new(self, raw) -> bool:
        try:
            key = self._dedupe_key(raw)
        except Exception:
            return True  # undedupeable: deliver rather than drop
        if key in self._seen_set:
            return False
        self._seen.append(key)
        self._seen_set.add(key)
        if len(self._seen) > self._history:
            old = self._seen.pop(0)
            self._seen_set.discard(old)
        return True

    def iter_messages(self, stale_after: float | None = None):
        """Yield de-duplicated messages; ``stale_after`` accepted and ignored.

        Polling is self-healing by construction (each poll is a fresh
        request), so staleness detection doesn't apply — the parameter
        exists only so the runner can treat all transports uniformly.
        """
        while not self._stop.is_set():
            try:
                raws = self._fetch() or []
            except Exception:
                raws = []  # a failed poll is a gap, not a crash
            for raw in raws:
                if self._is_new(raw):
                    yield raw
            self._stop.wait(self.interval)
