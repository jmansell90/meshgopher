"""
Meshie client implementation (connection handling, DM helpers, chunked sends).
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

import meshtastic
import meshtastic.tcp_interface
from pubsub import pub

from .chunker import chunk_message_smart
from .filters import is_direct_to, is_text_packet


class Meshie:
    def __init__(self, address: str, port: int = 4403, verbose: bool = True):
        self.address = address
        self.port = port
        self.verbose = verbose

        # Pace between multi-chunk sends to preserve ordering & avoid RF bursts
        self.inter_chunk_delay_sec: float = 1.2

        # Callback registries
        self.callbacks: List[Callable] = []     # generic: all packets
        self.dm_callbacks: List[Callable] = []  # DM-only

        if self.verbose:
            print(f"[Meshie] Connecting to {address}:{port} …")

        try:
            self.interface = meshtastic.tcp_interface.TCPInterface(
                address, portNumber=port
            )
        except Exception as e:
            print(f"[Meshie] Failed to connect: {e}")
            raise

        # Connection lifecycle events
        pub.subscribe(self._on_connection_established, "meshtastic.connection.established")
        pub.subscribe(self._on_connection_lost, "meshtastic.connection.lost")

        # Packet subscriptions — split text vs any to avoid duplicate DM dispatch
        pub.subscribe(self._on_receive_text, "meshtastic.receive.text")   # decoded TEXT packets
        pub.subscribe(self._on_receive_any,  "meshtastic.receive")        # catch-all (no DM dispatch here)

        # Ensure device is ready (myInfo, nodes, channels, etc.)
        try:
            self.interface.waitForConfig()
        except Exception as e:
            print(f"[Meshie] Warning: waitForConfig failed: {e}")

        # Cache our identity for DM filtering
        self.my_user = None
        self.my_id: Optional[str] = None
        try:
            self.my_user = self.interface.getMyUser()  # dict with 'id', 'longName', etc.
            if isinstance(self.my_user, dict):
                self.my_id = self.my_user.get("id")
            if self.verbose:
                print(f"[Meshie] my_id={self.my_id}")
        except Exception as e:
            print(f"[Meshie] Warning: could not read my user: {e}")

        # Keep process alive (meshtastic lib handles actual RX/TX in background)
        self.listener_thread = threading.Thread(target=self._run_listener, daemon=True)
        self.listener_thread.start()

    # ---------- Public API ----------

    def register_receiver(self, callback: Callable):
        """
        Register a generic receiver: callback(packet, interface)
        Receives ALL packets (including DMs), useful for logging/metrics.
        """
        self.callbacks.append(callback)

    def register_direct_receiver(self, callback: Callable):
        """
        Register a DM-only receiver: callback(packet, interface)
        Triggered only when a decoded TEXT message is addressed to this node.
        """
        self.dm_callbacks.append(callback)

    def send_message(self, message: str, channel: int = 0):
        """
        Broadcast a text message on a given channel.
        """
        try:
            self.interface.sendText(message, channelIndex=channel)
            if self.verbose:
                print(f"[Meshie] broadcast ch={channel}: {message!r}")
        except Exception as e:
            print(f"[Meshie] Error sending broadcast: {e}")

    def send_direct_message(
        self,
        destination_id: str,
        message: str,
        channel: int = 0,
        wantAck: bool = False,
        wantResponse: bool = False,
    ):
        """
        Send a *direct* text message to a specific node id (e.g. '!abcd1234').
        This is fire-and-forget; if you want ordered multi-chunk behavior, use
        send_direct_message_ordered().
        """
        try:
            self.interface.sendText(
                message,
                destinationId=destination_id,
                channelIndex=channel,
                wantAck=wantAck,
                wantResponse=wantResponse,
            )
            if self.verbose:
                print(f"[Meshie] DM -> {destination_id} ch={channel}: {message!r}")
        except Exception as e:
            print(f"[Meshie] Error sending DM: {e}")

    def send_direct_message_ordered(
        self,
        destination_id: str,
        message: str,
        channel: int = 0,
        chunk_size: int = 190,
        retries: int = 0,
    ):
        """
        Send a (possibly long) message as *ordered* chunks with simple pacing.
        We request radio ACKs but DO NOT block on waitForAckNak(), since it may
        not return reliably over TCP. Instead, we pace between chunks.

        Args:
          destination_id: Node ID like '!abcd1234'
          message:        Full message to chunk and send
          channel:        Channel index to use (DM still uses this index)
          chunk_size:     Max bytes per chunk (UTF-8, capped at 200)
          retries:        Per-chunk retry attempts on sendText exceptions
        """
        chunks = chunk_message_smart(message, chunk_size)

        total = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            attempt = 0
            while True:
                attempt += 1
                try:
                    if self.verbose:
                        print(
                            f"[Meshie] DM (paced) -> {destination_id} ch={channel} "
                            f"chunk {idx}/{total} attempt {attempt}"
                        )
                    self.interface.sendText(
                        chunk,
                        destinationId=destination_id,
                        channelIndex=channel,
                        wantAck=True,        # ask radio for ack, but don't block on it
                        wantResponse=False,
                    )
                    # Key pacing: give air time so chunks keep order over the mesh
                    time.sleep(self.inter_chunk_delay_sec)
                    break
                except Exception as e:
                    if attempt > retries:
                        print(f"[Meshie] DM chunk failed after {retries} retries: {e}")
                        raise
                    time.sleep(1.5)  # simple backoff and retry

    # ---------- Internals ----------

    def _on_connection_established(self, interface, topic=pub.AUTO_TOPIC):
        if self.verbose:
            node_id = self.my_id or "(unknown)"
            print(f"[Meshie] connection.established; my_id={node_id}")

    def _on_connection_lost(self, interface, topic=pub.AUTO_TOPIC):
        print("[Meshie] connection.lost")

    def _on_receive_text(self, packet, interface, topic=pub.AUTO_TOPIC):
        try:
            is_dm = is_text_packet(packet) and is_direct_to(packet, self.my_id)
            if is_dm:
                for cb in list(self.dm_callbacks):
                    try:
                        cb(packet, interface)
                    except Exception as e:
                        print(f"[Meshie] DM callback error: {e}")
            for cb in list(self.callbacks):
                try:
                    cb(packet, interface)
                except Exception as e:
                    print(f"[Meshie] receiver callback error: {e}")
        except Exception as e:
            print(f"[Meshie] _on_receive_text error: {e}")

    def _on_receive_any(self, packet, interface, topic=pub.AUTO_TOPIC):
        try:
            for cb in list(self.callbacks):
                try:
                    cb(packet, interface)
                except Exception as e:
                    print(f"[Meshie] receiver callback error: {e}")
        except Exception as e:
            print(f"[Meshie] _on_receive_any error: {e}")

    def _run_listener(self):
        while True:
            time.sleep(1)


__all__ = ["Meshie"]
