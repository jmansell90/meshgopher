"""
Minimal file-backed Gopher server for local demos/custom content.
"""

from __future__ import annotations

import os
import socket
import socketserver
import threading
from typing import Optional

CRLF = "\r\n"
DEFAULT_MAP_NAMES = ("gophermap", ".gophermap")


class LocalGopherServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, host: str, port: int, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        super().__init__((host, port), GopherRequestHandler)


class GopherRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        selector = self._read_selector()
        response = self._dispatch(selector)
        try:
            self.request.sendall(response)
        except BrokenPipeError:
            pass

    def _read_selector(self) -> str:
        chunks = []
        self.request.settimeout(10)
        while True:
            data = self.request.recv(1024)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        selector_line = raw.split("\n", 1)[0]
        selector = selector_line.rstrip("\r")
        return selector

    def _dispatch(self, selector: str) -> bytes:
        server: LocalGopherServer = self.server  # type: ignore[assignment]
        path_part = selector.split("\t", 1)[0]  # ignore queries for now
        rel_path = path_part.lstrip("/")
        fs_path = os.path.join(server.root_dir, rel_path)

        if not rel_path:
            return self._serve_menu(server.root_dir)

        if os.path.isdir(fs_path):
            return self._serve_menu(fs_path)

        if os.path.isfile(fs_path):
            return self._serve_text_file(fs_path)

        return self._serve_error(f"Selector not found: {path_part or '/'}")

    def _serve_menu(self, directory: str) -> bytes:
        map_path = _find_gophermap(directory)
        if not map_path:
            return self._serve_error(f"No gophermap in {os.path.relpath(directory)}")

        try:
            with open(map_path, "r", encoding="utf-8") as fh:
                lines = [line.rstrip("\r\n") for line in fh]
        except OSError as exc:
            return self._serve_error(f"Failed to read menu: {exc}")

        if not lines or lines[-1] != ".":
            lines.append(".")

        joined = CRLF.join(lines) + CRLF
        return joined.encode("utf-8")

    def _serve_text_file(self, file_path: str) -> bytes:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            return self._serve_error(f"Failed to read file: {exc}")

        body = content.replace("\r\n", "\n").replace("\r", "\n")
        body = body.rstrip("\n")
        payload = body + CRLF + "." + CRLF
        return payload.encode("utf-8")

    def _serve_error(self, message: str) -> bytes:
        lines = [f"3{message}\tfake\tlocalhost\t0", "."]
        return (CRLF.join(lines) + CRLF).encode("utf-8")


def _find_gophermap(directory: str) -> Optional[str]:
    for name in DEFAULT_MAP_NAMES:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def start_local_gopher(
    root_dir: str,
    host: str = "0.0.0.0",
    port: int = 7070,
) -> LocalGopherServer:
    server = LocalGopherServer(host, port, root_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


__all__ = ["LocalGopherServer", "start_local_gopher"]
