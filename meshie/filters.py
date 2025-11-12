"""
Helpers for classifying incoming Meshtastic packets.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import meshtastic


def is_text_packet(packet: Dict[str, Any]) -> bool:
    """
    Heuristic: treat packets with decoded.text or portnum TEXT_MESSAGE_APP as text.
    portnum may be a string ('TEXT_MESSAGE_APP') or an int; handle both.
    """
    try:
        decoded = packet.get("decoded") or {}
        if isinstance(decoded.get("text"), str):
            return True
        port = decoded.get("portnum")
        if port == "TEXT_MESSAGE_APP":
            return True
        try:
            return int(port) == getattr(
                meshtastic.portnums_pb2.PortNum,
                "TEXT_MESSAGE_APP",
                -999,
            )
        except Exception:
            return False
    except Exception:
        return False


def is_direct_to(packet: Dict[str, Any], my_id: Optional[str]) -> bool:
    if not my_id:
        return False
    return packet.get("toId") == my_id


__all__ = ["is_text_packet", "is_direct_to"]
