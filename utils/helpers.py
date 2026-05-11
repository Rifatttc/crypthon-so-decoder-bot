# -*- coding: utf-8 -*-
"""
helpers.py
----------
Shared utility functions for the Crypthon & SO Decoder Bot.

Includes:
  - Message splitting (Telegram 4096-char limit)
  - Result formatting for decoders
  - Filename sanitization
  - File extension detection

Author: Crypthon & SO Decoder Bot
"""

import os
import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Telegram message split limit (leave some buffer below 4096)
# ---------------------------------------------------------------------------
TELEGRAM_MAX_CHARS = 3900


def split_message(text: str, max_len: int = TELEGRAM_MAX_CHARS) -> List[str]:
    """
    Split a long string into chunks that fit within Telegram's message limit.

    Attempts to split on newlines for readability. Falls back to hard splits
    if a single line exceeds max_len.

    Args:
        text:    The full text to split.
        max_len: Maximum characters per chunk.

    Returns:
        List of string chunks, each ≤ max_len characters.
    """
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        line_len = len(line)

        # Single line longer than max_len — hard split it
        if line_len > max_len:
            # Flush current chunk first
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0
            # Hard-split the long line
            for i in range(0, line_len, max_len):
                chunks.append(line[i : i + max_len])
            continue

        # Would overflow current chunk — flush and start new
        if current_len + line_len > max_len:
            if current_chunk:
                chunks.append("".join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    # Flush remaining
    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks if chunks else [text[:max_len]]


def format_decode_result(result: Dict[str, Any], filename: str) -> str:
    """
    Format a Crypthon decode result dict into a human-readable Telegram message.

    Args:
        result:   Dictionary returned by decode_crypthon().
        filename: Original filename for display.

    Returns:
        Formatted multi-line string.
    """
    success = result.get("success", False)
    method = result.get("method", "unknown")
    layers = result.get("layers", 0)
    message = result.get("message", "")
    code = result.get("code", "")
    strings = result.get("strings", [])

    # --- Header section ---
    status_icon = "✅" if success else "⚠️"
    header_lines = [
        f"{'═' * 42}",
        f"🔓 CRYPTHON DECODER RESULT",
        f"{'═' * 42}",
        f"📄 ফাইল      : {filename}",
        f"{status_icon} স্ট্যাটাস   : {'সফল' if success else 'আংশিক / ব্যর্থ'}",
        f"🔄 Layers    : {layers}",
        f"🛠️  Method    : {method}",
        f"💬 বার্তা    : {message}",
        f"{'─' * 42}",
        "",
    ]

    # --- Extracted strings (brief preview in header) ---
    if strings:
        header_lines.append(f"📝 উল্লেখযোগ্য Strings ({len(strings)} টি):")
        for s in strings[:10]:
            short = repr(s)
            if len(short) > 80:
                short = short[:77] + "...'"
            header_lines.append(f"  • {short}")
        if len(strings) > 10:
            header_lines.append(f"  ... এবং আরো {len(strings) - 10} টি")
        header_lines.append("")

    # --- Code section ---
    header_lines.append("📜 Decoded Output:")
    header_lines.append("─" * 42)

    full_message = "\n".join(header_lines) + "\n" + (code or "(কোনো output নেই)")
    return full_message


def format_so_result(result: Dict[str, Any], filename: str) -> str:
    """
    Format a .so analysis result dict into a human-readable Telegram message.

    Args:
        result:   Dictionary returned by decode_so_file().
        filename: Original filename for display.

    Returns:
        Formatted multi-line string.
    """
    success = result.get("success", False)
    report = result.get("report", "")
    file_type = result.get("file_type", "unknown")
    message = result.get("message", "")

    if not success:
        return (
            f"❌ .SO FILE ANALYSIS FAILED\n"
            f"📄 ফাইল: {filename}\n"
            f"💬 বার্তা: {message}"
        )

    header = (
        f"{'═' * 42}\n"
        f"🔬 SO FILE ANALYZER RESULT\n"
        f"{'═' * 42}\n"
        f"📄 ফাইল    : {filename}\n"
        f"🔍 Type   : {file_type}\n"
        f"💬 বার্তা  : {message}\n"
        f"{'─' * 42}\n\n"
    )

    return header + report


def sanitize_filename(filename: str) -> str:
    """
    Remove potentially dangerous characters from a filename.
    Keeps alphanumerics, dots, hyphens, underscores.

    Args:
        filename: Raw filename string.

    Returns:
        Sanitized filename string.
    """
    # Keep only safe characters
    safe = re.sub(r"[^\w.\-]", "_", filename)
    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe)
    # Limit length
    return safe[:128]


def get_file_extension(filename: str) -> str:
    """
    Extract the lowercase file extension (with dot) from a filename.
    Returns empty string if no extension.

    Examples:
        "bot.py"         → ".py"
        "lib.cpython.so" → ".so"
        "archive.tar.gz" → ".gz"
        "README"         → ""
    """
    _, ext = os.path.splitext(filename)
    return ext.lower()
