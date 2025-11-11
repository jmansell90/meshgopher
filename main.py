#!/usr/bin/env python3
# main.py
"""
Meshie-driven Gopher navigator for direct messages (ordered sends).

ENV (required/optional):
  MESH_HOST   -> REQUIRED: Meshtastic node hostname/IP (no default)
  MESH_PORT   -> OPTIONAL: Meshtastic TCP port (default: 4403)
"""

import os
import sys
import time
import re
from typing import Dict, Optional, List

from meshie import Meshie
from gopherlib import (
    GopherClient,
    GopherURL,
    parse_gopher_url,
    MenuEntry,
    up_one,
)

RE_MENU_CMD = re.compile(r"^\s*([upnb]|[0-9]|s)\b(.*)$", re.IGNORECASE)
RE_URL_CMD  = re.compile(r"^\s*u\s+(\S+)\s*$", re.IGNORECASE)

MENU_PAGE_SIZE = 10
FILE_PAGE_SIZE = 20

def _get_env_host_port():
    host = os.getenv("MESH_HOST")
    if not host:
        sys.stderr.write(
            "[ERROR] MESH_HOST is not set. Please export MESH_HOST to the Meshtastic node's IP or hostname.\n"
            "Example: export MESH_HOST=192.168.1.50\n"
        )
        sys.exit(2)
    port_raw = os.getenv("MESH_PORT", "4403")
    try:
        port = int(port_raw)
    except ValueError:
        port = 4403
    return host, port

class ViewState:
    def __init__(self, url: GopherURL, view_kind: str, payload):
        self.url = url
        self.view_kind = view_kind  # "menu" | "file" | "binary" | "search"
        self.payload = payload
        self.menu_offset = 0
        self.file_offset = 0
        self.pending_search_endpoint: Optional[MenuEntry] = None

class Session:
    def __init__(self):
        self.client = GopherClient()
        self.history: List[ViewState] = []
        self.current: Optional[ViewState] = None

    def open_url(self, url_str: str) -> str:
        try:
            gurl = parse_gopher_url(url_str)
        except Exception as e:
            return f"Invalid URL: {e}"

        view_kind, payload = self.client.fetch(gurl)
        vs = ViewState(gurl, view_kind, payload)
        if view_kind == "search":
            vs.pending_search_endpoint = payload  # MenuEntry
            self.current = vs
            return self._render_search_prompt()
        else:
            self.current = vs
            self.history = [vs]
            return self.render()

    def _selectable_entries(self) -> List[MenuEntry]:
        if not self.current or self.current.view_kind != "menu":
            return []
        return [e for e in self.current.payload if e.type != "i"]

    def select_index(self, idx: int) -> str:
        if not self.current or self.current.view_kind != "menu":
            return "Not in a menu; numbers apply only to menu listings."

        entries = self._selectable_entries()
        start = self.current.menu_offset
        page_entries = entries[start:start + MENU_PAGE_SIZE]
        if idx < 0 or idx >= len(page_entries):
            return "Invalid selection on this page."

        entry = page_entries[idx]
        entry_url = GopherURL(
            host=entry.host or self.current.url.host,
            port=entry.port or self.current.url.port,
            type=entry.type,
            selector=entry.selector
        )

        if entry.type == "7":
            self.current.pending_search_endpoint = entry
            return self._render_search_prompt(display_title=entry.display)

        view_kind, payload = self.client.fetch(entry_url)
        new_vs = ViewState(entry_url, view_kind, payload)
        self.history.append(new_vs)
        self.current = new_vs
        return self.render()

    def search(self, terms: str) -> str:
        if not self.current:
            return "Open a gopher search endpoint first."
        endpoint = self.current.pending_search_endpoint
        if not endpoint:
            return "No search pending. Select a '7' item first, then use 's <terms>'."

        view_kind, payload = self.client.search(endpoint, terms)
        new_url = GopherURL(host=endpoint.host, port=endpoint.port, type="1", selector=endpoint.selector)
        new_vs = ViewState(new_url, view_kind, payload)
        self.history.append(new_vs)
        self.current = new_vs
        return self.render()

    def up(self) -> str:
        if not self.current:
            return "Nothing open yet. Try: u gopher://gopher.floodgap.com/"
        if len(self.history) > 1:
            self.history.pop()
            self.current = self.history[-1]
            return self.render()

        parent_selector = up_one(self.current.url.selector)
        parent_url = GopherURL(
            host=self.current.url.host,
            port=self.current.url.port,
            type="1",
            selector=parent_selector
        )
        view_kind, payload = self.client.fetch(parent_url)
        new_vs = ViewState(parent_url, view_kind, payload)
        self.history = [new_vs]
        self.current = new_vs
        return self.render()

    def next_page(self) -> str:
        if not self.current:
            return "Nothing open yet."
        if self.current.view_kind == "menu":
            entries = self._selectable_entries()
            if self.current.menu_offset + MENU_PAGE_SIZE >= len(entries):
                return "End of menu."
            self.current.menu_offset += MENU_PAGE_SIZE
            return self.render()
        if self.current.view_kind == "file":
            lines: List[str] = self.current.payload
            if self.current.file_offset + FILE_PAGE_SIZE >= len(lines):
                return "End of file."
            self.current.file_offset += FILE_PAGE_SIZE
            return self.render()
        return "Paging not applicable for this view."

    def prev_page(self) -> str:
        if not self.current:
            return "Nothing open yet."
        if self.current.view_kind == "menu":
            if self.current.menu_offset == 0:
                return "Already at start."
            self.current.menu_offset = max(0, self.current.menu_offset - MENU_PAGE_SIZE)
            return self.render()
        if self.current.view_kind == "file":
            if self.current.file_offset == 0:
                return "Already at start."
            self.current.file_offset = max(0, self.current.file_offset - FILE_PAGE_SIZE)
            return self.render()
        return "Paging not applicable for this view."

    def render(self) -> str:
        if not self.current:
            return "Nothing open yet."
        vs = self.current
        header = f"[gopher://{vs.url.host}:{vs.url.port}/{vs.url.type}{vs.url.selector}]"

        if vs.view_kind == "menu":
            entries = self._selectable_entries()
            if not entries:
                return f"{header}\n(Empty menu)\nCommands: u <URL>, b"

            start = vs.menu_offset
            page = entries[start:start + MENU_PAGE_SIZE]

            lines = [header, f"Showing items {start + 1}-{start + len(page)} of {len(entries)}:"]
            for i, e in enumerate(page):
                n = i  # 0..9 on this page
                disp = e.display or "(no title)"
                lines.append(f"{n}) [{e.type}] {disp}")
            lines.append("Commands: number to select, n (next), p (prev), b (back), u <URL>")
            return "\n".join(lines)

        if vs.view_kind == "file":
            lines = vs.payload
            start = vs.file_offset
            page = lines[start:start + FILE_PAGE_SIZE]
            body = "\n".join(page)
            footer = f"\n[Lines {start + 1}-{start + len(page)} of {len(lines)}]\nCommands: n, p, b, u <URL>"
            return f"{header}\n{body}{footer}"

        if vs.view_kind == "search":
            return self._render_search_prompt()

        if vs.view_kind == "binary":
            blen, note = vs.payload
            return f"{header}\n(Binary content, {blen} bytes) {note}\nCommands: b, u <URL>"

        return f"{header}\n(Unknown view)\nCommands: b, u <URL>"

    def _render_search_prompt(self, display_title: Optional[str] = None) -> str:
        title = f"Search: {display_title}" if display_title else "Search"
        return f"{title}\nSend: s <terms>"

def _extract_text(packet) -> Optional[str]:
    try:
        decoded = packet.get("decoded") or {}
        if isinstance(decoded, dict):
            if "text" in decoded and isinstance(decoded["text"], str):
                return decoded["text"]
            payload = decoded.get("payload")
            if payload and isinstance(payload, (bytes, bytearray)):
                try:
                    return payload.decode("utf-8", errors="replace")
                except Exception:
                    return None
        if "text" in packet and isinstance(packet["text"], str):
            return packet["text"]
    except Exception:
        pass
    return None

def _sender_id(packet) -> Optional[str]:
    for k in ("fromId", "from", "sender", "src"):
        v = packet.get(k)
        if isinstance(v, str) and v:
            return v
    return None

class App:
    def __init__(self, mesh: Meshie):
        self.mesh = mesh
        self.sessions: Dict[str, Session] = {}

    def _get_session(self, sender: str) -> Session:
        if sender not in self.sessions:
            self.sessions[sender] = Session()
        return self.sessions[sender]

    def on_receive(self, packet, interface):
        text = _extract_text(packet)
        if not text:
            return

        sender = _sender_id(packet)
        if not sender:
            return
        session = self._get_session(sender)

        msg = text.strip()

        m_url = RE_URL_CMD.match(msg)
        if m_url:
            url = m_url.group(1)
            out = session.open_url(url)
            return self._reply_dm(sender, packet, out)

        m_cmd = RE_MENU_CMD.match(msg)
        if m_cmd:
            cmd = m_cmd.group(1).lower()
            rest = (m_cmd.group(2) or "").strip()

            if cmd == "n":
                out = session.next_page()
                return self._reply_dm(sender, packet, out)
            if cmd == "p":
                out = session.prev_page()
                return self._reply_dm(sender, packet, out)
            if cmd == "b":
                out = session.up()
                return self._reply_dm(sender, packet, out)
            if cmd == "s":
                if not rest:
                    return self._reply_dm(sender, packet, "Usage: s <search terms>")
                out = session.search(rest)
                return self._reply_dm(sender, packet, out)
            if cmd.isdigit():
                idx = int(cmd)
                out = session.select_index(idx)
                return self._reply_dm(sender, packet, out)

        help_text = (
            "Gopher DM Navigator\n"
            "Commands:\n"
            "  u <URL>    open gopher URL (e.g., gopher://gopher.floodgap.com/1/world)\n"
            "  n / p      next / previous page\n"
            "  b          back / up directory\n"
            "  0..9       select item (menus only)\n"
            "  s <terms>  run search after selecting a type-7 item\n"
        )
        self._reply_dm(sender, packet, help_text)

    def _reply_dm(self, destination_id: str, packet: dict, text: str):
        ch = 0
        if isinstance(packet, dict):
            ch = packet.get("channel", 0)
        self.mesh.send_direct_message_ordered(destination_id, text, channel=ch, chunk_size=190, retries=0)

def LocalOnReceiveBuilder(app: App):
    def handler(packet, interface):
        app.on_receive(packet, interface)
    return handler

def main():
    host, port = _get_env_host_port()
    mesh = Meshie(address=host, port=port)
    app = App(mesh)

    mesh.register_direct_receiver(LocalOnReceiveBuilder(app))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting.")

if __name__ == "__main__":
    main()
