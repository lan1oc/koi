#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small localhost WebSocket event stream for retest agent traces.

The backend is a stdin/stdout sidecar, so this module keeps the WebSocket
implementation dependency-free and only broadcasts server-to-client JSON events.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import socketserver
import struct
import threading
from typing import Any, Dict, Set


_SERVER: socketserver.ThreadingTCPServer | None = None
_PORT = 0
_LOCK = threading.RLock()
_CLIENTS: Set["_RetestWebSocketHandler"] = set()


def _json_safe(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {_json_safe(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _encode_frame(text: str) -> bytes:
    payload = text.encode("utf-8", "replace")
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x81, length)
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", 0x81, 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 127, length)
    return header + payload


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("socket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_client_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = _read_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    mask = _read_exact(sock, 4) if masked else b""
    payload = bytearray(_read_exact(sock, length)) if length else bytearray()
    if masked and payload:
        for index in range(len(payload)):
            payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)


class _ThreadingWebSocketServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _RetestWebSocketHandler(socketserver.BaseRequestHandler):
    def setup(self) -> None:
        self.alive = False

    def handle(self) -> None:
        self.request.settimeout(30)
        if not self._handshake():
            return
        self.alive = True
        with _LOCK:
            _CLIENTS.add(self)
        try:
            while self.alive:
                try:
                    opcode, _payload = _read_client_frame(self.request)
                except socket.timeout:
                    continue
                except Exception:
                    break
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._send_raw(b"\x8a\x00")
        finally:
            self.alive = False
            with _LOCK:
                _CLIENTS.discard(self)

    def _handshake(self) -> bool:
        data = bytearray()
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = self.request.recv(1024)
            if not chunk:
                return False
            data.extend(chunk)
        header_text = data.decode("utf-8", "replace")
        headers: Dict[str, str] = {}
        for line in header_text.splitlines()[1:]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            return False
        accept = base64.b64encode(hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        self.request.sendall(response.encode("ascii"))
        return True

    def send_json(self, payload: Dict[str, Any]) -> bool:
        if not self.alive:
            return False
        try:
            self._send_raw(_encode_frame(json.dumps(_json_safe(payload), ensure_ascii=False)))
            return True
        except Exception:
            self.alive = False
            return False

    def _send_raw(self, data: bytes) -> None:
        self.request.sendall(data)


def ensure_retest_event_stream() -> Dict[str, Any]:
    global _SERVER, _PORT
    with _LOCK:
        if _SERVER is None:
            server = _ThreadingWebSocketServer(("127.0.0.1", 0), _RetestWebSocketHandler)
            _SERVER = server
            _PORT = int(server.server_address[1])
            thread = threading.Thread(target=server.serve_forever, name="koi-retest-ws", daemon=True)
            thread.start()
        return {
            "success": True,
            "host": "127.0.0.1",
            "port": _PORT,
            "ws_url": f"ws://127.0.0.1:{_PORT}/retest-events",
            "clients": len(_CLIENTS),
        }


def publish_retest_event(payload: Dict[str, Any]) -> None:
    ensure_retest_event_stream()
    dead = []
    with _LOCK:
        clients = list(_CLIENTS)
    for client in clients:
        if not client.send_json(payload):
            dead.append(client)
    if dead:
        with _LOCK:
            for client in dead:
                _CLIENTS.discard(client)
