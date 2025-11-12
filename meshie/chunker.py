"""
Utilities for splitting outbound messages into mesh-friendly chunks.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .constants import MAX_DM_BYTES


def chunk_message_smart(message: str, chunk_size: int) -> List[str]:
    """
    Chunk messages with whitespace-aware splitting and paragraph breaks,
    respecting a UTF-8 byte ceiling.
    """
    max_bytes = max(1, min(chunk_size, MAX_DM_BYTES))
    payload = message if message else ""
    if not payload:
        return [""]

    chunks: List[str] = []
    idx = 0
    length = len(payload)

    while idx < length:
        window, window_end = _utf8_window(payload, idx, max_bytes)
        if not window:
            window = payload[idx:min(idx + 1, length)]
            window_end = idx + len(window)

        if window_end >= length:
            chunk_raw = window
            idx = window_end
        else:
            split_idx = _find_split_index(window)
            split_idx = _adjust_split_for_blank_and_short(window, split_idx)
            split_idx = max(1, min(split_idx, len(window)))
            chunk_raw = window[:split_idx]
            idx += split_idx

        cleaned = _trim_chunk_edges(chunk_raw)
        if cleaned:
            chunks.append(cleaned)

    return chunks or [""]


def _find_split_index(window: str) -> int:
    newline_idx = window.rfind("\n")
    if newline_idx > 0:
        return newline_idx + 1
    space_idx = _find_space_split(window)
    if space_idx is not None and space_idx > 0:
        return space_idx
    return len(window)


def _find_space_split(window: str) -> int | None:
    for pos in range(len(window) - 1, -1, -1):
        ch = window[pos]
        if ch in (" ", "\t"):
            return pos + 1
    return None


def _adjust_split_for_blank_and_short(window: str, split_idx: int) -> int:
    split_idx = _remove_trailing_blank_lines(window, split_idx)
    split_idx = _avoid_short_last_line(window, split_idx)
    return split_idx


def _remove_trailing_blank_lines(text: str, split_idx: int) -> int:
    if split_idx <= 0:
        return split_idx
    slice_text = text[:split_idx]
    trimmed = re.sub(r"(?:\r?\n[ \t]*)+$", "", slice_text)
    if trimmed:
        return len(trimmed)
    return split_idx


def _avoid_short_last_line(text: str, split_idx: int) -> int:
    if split_idx <= 0:
        return split_idx
    slice_text = text[:split_idx]
    without_newlines = slice_text.rstrip("\r\n")
    if not without_newlines:
        return split_idx
    last_newline = without_newlines.rfind("\n")
    if last_newline == -1:
        last_line = without_newlines.replace("\r", "")
        if len(last_line) < 5:
            return split_idx
        return split_idx
    last_line = without_newlines[last_newline + 1:].replace("\r", "")
    if len(last_line) < 5:
        return last_newline + 1
    return split_idx


def _trim_chunk_edges(text: str) -> str:
    if not text:
        return ""
    trimmed = re.sub(r"^(?:[ \t]*\r?\n)+", "", text)
    trimmed = re.sub(r"(?:\r?\n[ \t]*)+$", "", trimmed)
    return trimmed.strip("\r")  # retain intentional spaces but drop stray CRs


def _utf8_window(text: str, start: int, max_bytes: int) -> Tuple[str, int]:
    idx = start
    length = len(text)
    used = 0
    while idx < length:
        char_len = _utf8_char_len(text[idx])
        if used + char_len > max_bytes:
            break
        used += char_len
        idx += 1
    if idx == start and idx < length:
        idx += 1
    return text[start:idx], idx


def _utf8_char_len(ch: str) -> int:
    code = ord(ch)
    if code <= 0x7F:
        return 1
    if code <= 0x7FF:
        return 2
    if code <= 0xFFFF:
        return 3
    return 4


__all__ = ["chunk_message_smart"]
