#!/usr/bin/env python3
# gopherlib.py
import socket
from dataclasses import dataclass
from typing import List, Tuple

DEFAULT_PORT = 70
SOCKET_TIMEOUT = 15

@dataclass
class GopherURL:
    host: str
    port: int
    type: str
    selector: str

def parse_gopher_url(url: str) -> 'GopherURL':
    if not url.lower().startswith("gopher://"):
        raise ValueError("URL must start with gopher://")

    body = url[9:]
    host_port, *rest = body.split("/", 1)
    selector_with_type = rest[0] if rest else ""

    if ":" in host_port:
        host, port_str = host_port.split(":", 1)
        port = int(port_str)
    else:
        host, port = host_port, DEFAULT_PORT

    if selector_with_type == "":
        return GopherURL(host=host, port=port, type="1", selector="")

    type_char = selector_with_type[0]
    selector = selector_with_type[1:] if len(selector_with_type) > 1 else ""

    valid_types = set("0123456789+ghIisTtP;,dcruwWXsM")
    if type_char not in valid_types:
        return GopherURL(host=host, port=port, type="1", selector=selector_with_type)
    return GopherURL(host=host, port=port, type=type_char, selector=selector)

def _recv_all_lines(host: str, port: int, request_selector: str) -> List[str]:
    with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT) as s:
        s.sendall((request_selector + "\r\n").encode("utf-8", errors="replace"))
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            data = s.recv(4096)
            if not data:
                break
            chunks.append(data)
    text = b"".join(chunks).decode("utf-8", errors="replace")
    return text.splitlines()

@dataclass
class MenuEntry:
    type: str
    display: str
    selector: str
    host: str
    port: int

def parse_menu(lines: List[str]) -> List['MenuEntry']:
    out: List[MenuEntry] = []
    for line in lines:
        if line.strip() == ".":
            break
        if not line:
            continue
        type_char = line[0]
        fields = line[1:].split("\t")
        display = fields[0] if len(fields) > 0 else ""
        selector = fields[1] if len(fields) > 1 else ""
        host = fields[2] if len(fields) > 2 else ""
        port = fields[3] if len(fields) > 3 else ""
        try:
            pnum = int(port) if port else DEFAULT_PORT
        except ValueError:
            pnum = DEFAULT_PORT
        out.append(MenuEntry(type=type_char, display=display, selector=selector, host=host, port=pnum))
    return out

class GopherClient:
    def fetch(self, url: GopherURL) -> Tuple[str, object]:
        if url.type == "1":
            lines = _recv_all_lines(url.host, url.port, url.selector)
            entries = parse_menu(lines)
            return "menu", entries

        if url.type == "7":
            return "search", MenuEntry(type="7", display="[SEARCH]", selector=url.selector,
                                       host=url.host, port=url.port)

        if url.type == "0":
            lines = _recv_all_lines(url.host, url.port, url.selector)
            return "file", lines

        try:
            data_lines = _recv_all_lines(url.host, url.port, url.selector)
            joined = "\n".join(data_lines)
            return "binary", (len(joined.encode("utf-8", errors="replace")), "Non-text gopher type")
        except Exception as e:
            return "binary", (0, f"Error fetching: {e}")

    def search(self, endpoint: MenuEntry, query: str) -> Tuple[str, List[MenuEntry]]:
        selector_with_query = f"{endpoint.selector}\t{query}"
        lines = _recv_all_lines(endpoint.host, endpoint.port, selector_with_query)
        return "menu", parse_menu(lines)

def up_one(selector: str) -> str:
    if not selector:
        return ""
    if "/" not in selector:
        return ""
    return selector.rsplit("/", 1)[0]
