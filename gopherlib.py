#!/usr/bin/env python3
# gopherlib.py
import socket
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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

    valid_types = set("0123456789+ghIisTtP;,dcruwWXsMT")
    if type_char not in valid_types:
        return GopherURL(host=host, port=port, type="1", selector=selector_with_type)
    return GopherURL(host=host, port=port, type=type_char, selector=selector)

def _recv_all_lines(host: str, port: int, request_selector: str, suffix: str = "") -> List[str]:
    request = f"{request_selector}{suffix}\r\n"
    with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT) as s:
        s.sendall(request.encode("utf-8", errors="replace"))
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
    attributes: Optional[Dict[str, List[str]]] = field(default=None)

def _make_menu_entry(type_char: str, display: str, selector: str, host: str, port: str,
                     attributes: Optional[Dict[str, List[str]]] = None) -> MenuEntry:
    try:
        pnum = int(port) if port else DEFAULT_PORT
    except ValueError:
        pnum = DEFAULT_PORT
    return MenuEntry(
        type=type_char or "i",
        display=display,
        selector=selector,
        host=host or "",
        port=pnum,
        attributes=attributes.copy() if attributes else None,
    )

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
        out.append(_make_menu_entry(type_char, display, selector, host, port))
    return out

def parse_menu_plus(lines: List[str]) -> List[MenuEntry]:
    entries: List[MenuEntry] = []
    current_entry: Optional[MenuEntry] = None
    current_attr: Optional[str] = None
    attr_buffer: List[str] = []

    def _flush_attr():
        nonlocal current_attr, attr_buffer, current_entry
        if current_entry is None or current_attr is None:
            attr_buffer.clear()
            current_attr = None
            return
        attrs = current_entry.attributes or {}
        attrs.setdefault(current_attr, []).extend(attr_buffer)
        current_entry.attributes = attrs
        attr_buffer.clear()
        current_attr = None

    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line:
            continue
        if line == ".":
            if current_attr:
                _flush_attr()
                continue
            break
        if line.startswith("+INFO:"):
            if current_attr:
                _flush_attr()
            info_line = line[len("+INFO:"):]
            if not info_line:
                continue
            entry = _make_menu_entry_from_info(info_line)
            entries.append(entry)
            current_entry = entry
            continue
        if line.startswith("+") and line.endswith(":") and ":" in line[1:]:
            if current_attr:
                _flush_attr()
            current_attr = line[1:-1].upper()
            attr_buffer.clear()
            continue
        if current_attr:
            attr_buffer.append(line)

    if current_attr:
        _flush_attr()

    return entries

def _make_menu_entry_from_info(info_line: str) -> MenuEntry:
    type_char = info_line[0] if info_line else "i"
    fields = info_line[1:].split("\t") if len(info_line) > 1 else []
    display = fields[0] if len(fields) > 0 else ""
    selector = fields[1] if len(fields) > 1 else ""
    host = fields[2] if len(fields) > 2 else ""
    port = fields[3] if len(fields) > 3 else ""
    return _make_menu_entry(type_char, display, selector, host, port, attributes={})

def _looks_like_gopher_plus(lines: List[str]) -> bool:
    for line in lines:
        if not line:
            continue
        return line.startswith("+INFO:")
    return False

def _fetch_menu(host: str, port: int, selector: str) -> List[MenuEntry]:
    try:
        plus_lines = _recv_all_lines(host, port, selector, suffix="\t+")
        if _looks_like_gopher_plus(plus_lines):
            return parse_menu_plus(plus_lines)
    except Exception:
        pass
    lines = _recv_all_lines(host, port, selector)
    return parse_menu(lines)

class GopherClient:
    def fetch(self, url: GopherURL) -> Tuple[str, object]:
        type_char = url.type.lower()
        if type_char == "1":
            entries = _fetch_menu(url.host, url.port, url.selector)
            return "menu", entries

        if type_char in ("7", "t"):
            return "search", MenuEntry(
                type=url.type,
                display="[SEARCH]",
                selector=url.selector,
                host=url.host,
                port=url.port,
                attributes=None,
            )

        if url.type == "0":
            lines = _recv_all_lines(url.host, url.port, url.selector)
            return "file", lines

        try:
            data_lines = _recv_all_lines(url.host, url.port, url.selector)
            joined = "\n".join(data_lines)
            return "binary", (len(joined.encode("utf-8", errors="replace")), "Non-text gopher type")
        except Exception as e:
            return "binary", (0, f"Error fetching: {e}")

    def search(self, endpoint: MenuEntry, query_payload: str) -> Tuple[str, List[MenuEntry]]:
        if query_payload:
            selector_with_query = f"{endpoint.selector}\t{query_payload}"
        else:
            selector_with_query = endpoint.selector
        entries = _fetch_menu(endpoint.host, endpoint.port, selector_with_query)
        return "menu", entries

def up_one(selector: str) -> str:
    if not selector:
        return ""
    if "/" not in selector:
        return ""
    return selector.rsplit("/", 1)[0]
