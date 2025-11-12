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
import shlex
from typing import Dict, Optional, List

from meshie import Meshie
from localgopher import start_local_gopher
from gopherlib import (
    GopherClient,
    GopherURL,
    parse_gopher_url,
    MenuEntry,
    up_one,
)

RE_MENU_CMD = re.compile(r"^\s*([upnbx]|[0-9]|s)\b(.*)$", re.IGNORECASE)
RE_URL_CMD  = re.compile(r"^\s*u\s+(\S+)\s*$", re.IGNORECASE)

HELP_TEXT = (
    "MeshGopher — Meshtastic DM Gopher Navigator\n"
    "\n"
    "Browse Gopher menus and files completely over direct messages. "
    "MeshGopher keeps replies ordered, paginates automatically, and never posts to broadcast.\n"
    "\n"
    "Commands:\n"
    "  u <URL>    open a gopher URL (e.g., gopher://gopher.floodgap.com/1/world)\n"
    "  n / p      next / previous page when paging menus or files\n"
    "  b          go back / up a directory\n"
    "  0..9       select an item on the current menu page\n"
    "  s <terms>  run a search (use s field=value for multi-field queries)\n"
    "  x          show the current gopher URL for bookmarking\n"
    "  h / help   show this project overview\n"
    "\n"
    "Examples:\n"
    "  u gopher://gopher.floodgap.com/1/world\n"
    "  s space news\n"
    "\n"
    "Source & docs live in this repository. Happy gophering!"
)

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

        entry_type = (entry.type or "").lower()
        if entry_type in ("7", "t"):
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
            return "No search pending. Select a type-7/T item first, then use 's <terms>'."
        if not terms.strip():
            return self._render_search_prompt()

        payload_query = self._build_search_query(endpoint, terms)
        if not payload_query:
            return "Provide search terms (or field=value pairs) for this endpoint."

        view_kind, payload = self.client.search(endpoint, payload_query)
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

    def current_url(self) -> str:
        if not self.current:
            return "Nothing open yet."
        url = self.current.url
        selector = url.selector or ""
        url_str = f"gopher://{url.host}:{url.port}/{url.type}{selector}"
        return f"Current URL:\n{url_str}\n\nUse: u {url_str}"

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
                return f"{header}\n(Empty menu)"

            start = vs.menu_offset
            page = entries[start:start + MENU_PAGE_SIZE]

            lines = [header, f"Showing items {start + 1}-{start + len(page)} of {len(entries)}:"]
            for i, e in enumerate(page):
                n = i  # 0..9 on this page
                disp = e.display or "(no title)"
                lines.append(f"{n}) [{e.type}] {disp}")
            return "\n".join(lines)

        if vs.view_kind == "file":
            lines = vs.payload
            start = vs.file_offset
            page = lines[start:start + FILE_PAGE_SIZE]
            body = "\n".join(page)
            footer = f"\n[Lines {start + 1}-{start + len(page)} of {len(lines)}]"
            return f"{header}\n{body}{footer}"

        if vs.view_kind == "search":
            return self._render_search_prompt()

        if vs.view_kind == "binary":
            blen, note = vs.payload
            return f"{header}\n(Binary content, {blen} bytes) {note}"

        return f"{header}\n(Unknown view)"

    def _render_search_prompt(self, display_title: Optional[str] = None) -> str:
        title = f"Search: {display_title}" if display_title else "Search"
        endpoint = self.current.pending_search_endpoint if self.current else None
        lines = [title]
        if endpoint and (endpoint.type or "").upper() == "T":
            lines.append("(Veronica/WAIS search)")
        fields = self._search_fields(endpoint)
        prompts = self._search_prompts(endpoint)
        if fields:
            lines.append(f"Fields: {', '.join(fields)}")
            lines.append("Send: s field=value ... (use quotes for spaces)")
        else:
            lines.append("Send: s <terms>")
        if prompts:
            lines.append("Notes:")
            for note in prompts:
                lines.append(f"  {note}")
        return "\n".join(lines)

    @staticmethod
    def _search_fields(endpoint: Optional[MenuEntry]) -> List[str]:
        if not endpoint or not endpoint.attributes:
            return []
        for key in ("FIELDS", "FIELD", "SEARCHFIELDS"):
            if key in endpoint.attributes:
                return [line.strip() for line in endpoint.attributes[key] if line.strip()]
        return []

    @staticmethod
    def _search_prompts(endpoint: Optional[MenuEntry]) -> List[str]:
        if not endpoint or not endpoint.attributes:
            return []
        notes: List[str] = []
        for key in ("PROMPT", "ABSTRACT"):
            if key in endpoint.attributes:
                notes.extend([line.strip() for line in endpoint.attributes[key] if line.strip()])
        return notes

    def _build_search_query(self, endpoint: MenuEntry, terms: str) -> str:
        tokens = shlex.split(terms)
        if not tokens:
            return ""
        fields = self._search_fields(endpoint)
        named: Dict[str, str] = {}
        positional: List[str] = []
        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                named[key.strip().lower()] = value
            else:
                positional.append(token)

        values: List[str] = []
        if fields:
            pos_iter = iter(positional)
            for field in fields:
                lookup_key = field.lower()
                if lookup_key in named:
                    values.append(named.pop(lookup_key))
                else:
                    try:
                        values.append(next(pos_iter))
                    except StopIteration:
                        values.append("")
            residual = list(pos_iter) + list(named.values())
            if residual:
                values.extend(residual)
        else:
            values = [" ".join(tokens)]
        return "\t".join(values)

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

def _local_gopher_base_url() -> Optional[str]:
    explicit = os.getenv("LOCAL_GOPHER_URL")
    if explicit:
        return explicit.rstrip("/")
    host = (
        os.getenv("LOCAL_GOPHER_CLIENT_HOST")
        or os.getenv("LOCAL_GOPHER_HOST")
        or "localhost"
    )
    if host == "0.0.0.0":
        host = "localhost"
    port_raw = os.getenv("LOCAL_GOPHER_PORT", "7070")
    try:
        port = int(port_raw)
    except ValueError:
        port = 7070
    return f"gopher://{host}:{port}/1"

def _resolve_local_gopher_alias(raw: str) -> Optional[str]:
    token = raw.strip()
    if not token or not token.lower().startswith("local"):
        return None
    base = _local_gopher_base_url()
    if not base:
        return None
    if token.lower() == "local":
        selector = ""
    elif token.lower().startswith("local/"):
        selector = token[6:]
    else:
        return None
    selector = selector.lstrip("/")
    return base + selector

def _maybe_start_local_gopher():
    root = os.getenv("LOCAL_GOPHER_ROOT", "server")
    if not root:
        return None
    if not os.path.isdir(root):
        if os.getenv("LOCAL_GOPHER_ROOT"):
            print(f"[LocalGopher] Root path not found: {root}")
        return None
    host = os.getenv("LOCAL_GOPHER_HOST", "0.0.0.0")
    port_raw = os.getenv("LOCAL_GOPHER_PORT", "7070")
    try:
        port = int(port_raw)
    except ValueError:
        port = 7070
    try:
        server = start_local_gopher(root, host=host, port=port)
        print(f"[LocalGopher] Serving {root} on gopher://{host}:{port}/")
        return server
    except OSError as exc:
        print(f"[LocalGopher] Failed to start server: {exc}")
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
        if not msg:
            return self._send_help(sender, packet)

        normalized = msg.lower()
        if normalized in ("h", "help"):
            return self._send_help(sender, packet)

        m_url = RE_URL_CMD.match(msg)
        if m_url:
            url = m_url.group(1)
            alias = _resolve_local_gopher_alias(url)
            if alias:
                url = alias
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
            if cmd == "x":
                out = session.current_url()
                return self._reply_dm(sender, packet, out)
            if cmd == "s":
                out = session.search(rest)
                return self._reply_dm(sender, packet, out)
            if cmd.isdigit():
                idx = int(cmd)
                out = session.select_index(idx)
                return self._reply_dm(sender, packet, out)

        return self._send_help(sender, packet)

    def _reply_dm(self, destination_id: str, packet: dict, text: str):
        ch = 0
        if isinstance(packet, dict):
            ch = packet.get("channel", 0)
        self.mesh.send_direct_message_ordered(destination_id, text, channel=ch, chunk_size=200, retries=0)

    def _send_help(self, destination_id: str, packet: dict):
        self._reply_dm(destination_id, packet, HELP_TEXT)

def LocalOnReceiveBuilder(app: App):
    def handler(packet, interface):
        app.on_receive(packet, interface)
    return handler

def main():
    host, port = _get_env_host_port()
    local_gopher = _maybe_start_local_gopher()
    mesh = Meshie(address=host, port=port)
    app = App(mesh)

    mesh.register_direct_receiver(LocalOnReceiveBuilder(app))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting.")
    finally:
        if local_gopher:
            local_gopher.shutdown()
            local_gopher.server_close()

if __name__ == "__main__":
    main()
