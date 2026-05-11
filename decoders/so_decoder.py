# -*- coding: utf-8 -*-
"""
so_decoder.py
-------------
Analyzes ELF/SO (shared object) files in pure Python.

Capabilities:
  - Identify file type via magic bytes
  - Extract all printable ASCII strings (length ≥ 5)
  - Detect and decode embedded base64 strings
  - Highlight Python-related keywords
  - Report section/segment summary (ELF header parsing)
  - Limit output to avoid Telegram message overflow

Author: Crypthon & SO Decoder Bot
"""

import base64
import re
import struct
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
SOResult = Dict[str, Any]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum length for a string to be considered meaningful
MIN_STRING_LEN = 5

# Maximum characters in final output (Telegram message limit safety)
MAX_OUTPUT_CHARS = 3800

# Python-related keywords to highlight in extracted strings
PYTHON_KEYWORDS = (
    "import",
    "def ",
    "class ",
    "exec",
    "eval",
    "marshal",
    "zlib",
    "base64",
    "compile",
    "subprocess",
    "__import__",
    "os.system",
    "socket",
    "requests",
    "urllib",
    "open(",
    "write(",
    "payload",
    "token",
    "password",
    "secret",
    "api_key",
    "http",
    "https",
)

# Regex to find potential base64 strings in binary data (≥ 40 encoded chars)
_RE_EMBEDDED_B64 = re.compile(
    rb'(?<![A-Za-z0-9+/=])([A-Za-z0-9+/]{40,}(?:={0,2}))(?![A-Za-z0-9+/=])',
)


# ---------------------------------------------------------------------------
# Helper: identify file type from magic bytes
# ---------------------------------------------------------------------------

def _identify_file_type(header: bytes) -> str:
    """
    Identify file type using the first few magic bytes.
    Returns a human-readable type string.
    """
    if len(header) < 4:
        return "Unknown (too short)"

    # ELF (Linux shared object / executable)
    if header[:4] == b'\x7fELF':
        ei_class = header[4] if len(header) > 4 else 0
        ei_data = header[5] if len(header) > 5 else 0
        ei_type = struct.unpack_from('<H', header, 16)[0] if len(header) >= 18 else 0

        arch = "32-bit" if ei_class == 1 else ("64-bit" if ei_class == 2 else "unknown-bit")
        endian = "little-endian" if ei_data == 1 else ("big-endian" if ei_data == 2 else "")
        file_types = {1: "Relocatable", 2: "Executable", 3: "Shared Object (SO)", 4: "Core"}
        ftype = file_types.get(ei_type, f"type={ei_type}")

        return f"ELF {arch} {endian} {ftype}"

    # Mach-O (macOS dylib)
    if header[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe',
                      b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce'):
        return "Mach-O (macOS shared library)"

    # PE (Windows DLL/EXE)
    if header[:2] == b'MZ':
        return "PE (Windows executable/DLL)"

    # ZIP (might be a .whl or Python .zip)
    if header[:2] == b'PK':
        return "ZIP archive (possibly Python wheel)"

    # Python marshal
    if header[:4] in (b'\xe3\x00\x00\x00', b'\x63\x00\x00\x00'):
        return "Python marshal bytecode"

    # Python .pyc
    if header[:2] in (b'\x0d\x0a', b'\x0a\r'):
        return "Python compiled (.pyc)"

    return f"Unknown (magic: {header[:8].hex()})"


# ---------------------------------------------------------------------------
# Helper: parse ELF section names (if possible)
# ---------------------------------------------------------------------------

def _parse_elf_sections(data: bytes) -> List[str]:
    """
    Basic ELF section header parser.
    Returns a list of section name strings (best-effort).
    """
    sections = []
    try:
        if data[:4] != b'\x7fELF':
            return sections

        ei_class = data[4]  # 1 = 32-bit, 2 = 64-bit
        ei_data = data[5]   # 1 = little, 2 = big

        is_64 = (ei_class == 2)
        # Endianness prefix for struct
        endian = '<' if ei_data == 1 else '>'

        if is_64:
            # e_shoff at offset 40 (8 bytes), e_shentsize at 58 (2), e_shnum at 60, e_shstrndx at 62
            e_shoff = struct.unpack_from(endian + 'Q', data, 40)[0]
            e_shentsize = struct.unpack_from(endian + 'H', data, 58)[0]
            e_shnum = struct.unpack_from(endian + 'H', data, 60)[0]
            e_shstrndx = struct.unpack_from(endian + 'H', data, 62)[0]
        else:
            # 32-bit
            e_shoff = struct.unpack_from(endian + 'I', data, 32)[0]
            e_shentsize = struct.unpack_from(endian + 'H', data, 46)[0]
            e_shnum = struct.unpack_from(endian + 'H', data, 48)[0]
            e_shstrndx = struct.unpack_from(endian + 'H', data, 50)[0]

        if e_shoff == 0 or e_shnum == 0:
            return sections

        # Get string table section
        strtab_offset = e_shoff + e_shstrndx * e_shentsize
        if is_64:
            sh_offset = struct.unpack_from(endian + 'Q', data, strtab_offset + 24)[0]
            sh_size = struct.unpack_from(endian + 'Q', data, strtab_offset + 32)[0]
        else:
            sh_offset = struct.unpack_from(endian + 'I', data, strtab_offset + 16)[0]
            sh_size = struct.unpack_from(endian + 'I', data, strtab_offset + 20)[0]

        strtab = data[sh_offset: sh_offset + sh_size]

        # Iterate over section headers
        for i in range(min(e_shnum, 64)):  # Limit to first 64 sections
            sh_base = e_shoff + i * e_shentsize
            name_offset = struct.unpack_from(endian + 'I', data, sh_base)[0]
            # Extract null-terminated name from string table
            end = strtab.find(b'\x00', name_offset)
            if end == -1:
                end = name_offset + 64
            name = strtab[name_offset:end].decode('utf-8', errors='replace')
            if name:
                sections.append(name)

    except Exception:
        pass  # Best-effort; don't crash on malformed ELF

    return sections


# ---------------------------------------------------------------------------
# Core: extract printable strings from binary data
# ---------------------------------------------------------------------------

def _extract_printable_strings(data: bytes, min_len: int = MIN_STRING_LEN) -> List[str]:
    """
    Extract all sequences of printable ASCII characters from binary data.
    This mimics the Unix `strings` command in pure Python.

    Args:
        data: Raw binary bytes.
        min_len: Minimum string length to include.

    Returns:
        List of extracted string candidates.
    """
    results = []
    current = bytearray()

    for byte in data:
        # Printable ASCII range: 0x20 (space) to 0x7E (~), plus tab
        if 0x20 <= byte <= 0x7E or byte == 0x09:
            current.append(byte)
        else:
            if len(current) >= min_len:
                results.append(current.decode('ascii', errors='replace'))
            current = bytearray()

    # Don't forget the last string
    if len(current) >= min_len:
        results.append(current.decode('ascii', errors='replace'))

    return results


# ---------------------------------------------------------------------------
# Core: find and decode embedded base64 strings
# ---------------------------------------------------------------------------

def _find_and_decode_base64(data: bytes) -> List[Tuple[str, str]]:
    """
    Search raw binary data for base64-looking blobs and try to decode them.

    Returns:
        List of (original_b64_snippet, decoded_preview) tuples.
    """
    results = []
    seen = set()

    for match in _RE_EMBEDDED_B64.finditer(data):
        b64_bytes = match.group(1)

        # Deduplicate
        key = b64_bytes[:40]
        if key in seen:
            continue
        seen.add(key)

        # Fix padding
        pad = len(b64_bytes) % 4
        if pad:
            b64_bytes += b'=' * (4 - pad)

        try:
            decoded = base64.b64decode(b64_bytes)
        except Exception:
            continue

        # Only report if decoded result has meaningful content
        if len(decoded) < 10:
            continue

        # Try to show as text
        try:
            preview = decoded.decode('utf-8', errors='replace')
            if not any(c.isprintable() for c in preview[:20]):
                # Looks like garbage — show hex
                preview = f"[binary: {decoded[:32].hex()}...]"
        except Exception:
            preview = f"[binary: {decoded[:32].hex()}...]"

        original_snippet = b64_bytes[:60].decode('ascii', errors='replace')
        results.append((original_snippet + ("..." if len(b64_bytes) > 60 else ""), preview[:200]))

    return results[:10]  # Cap at 10 results


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def decode_so_file(file_path: str) -> SOResult:
    """
    Main entry point for analyzing a .so shared object file.

    Steps:
      1. Read file as raw bytes
      2. Identify file type
      3. Parse ELF sections (if ELF)
      4. Extract all printable strings
      5. Search for Python keywords in strings
      6. Find and decode embedded base64
      7. Build a formatted report

    Args:
        file_path: Path to the .so file to analyze.

    Returns:
        SOResult dict with keys:
            success (bool), report (str), python_strings (list),
            b64_findings (list), file_type (str), message (str)
    """
    # ------------------------------------------------------------------ #
    # Step 1: Read the file                                               #
    # ------------------------------------------------------------------ #
    try:
        with open(file_path, "rb") as fh:
            data = fh.read()
    except Exception as exc:
        return {
            "success": False,
            "report": "",
            "python_strings": [],
            "b64_findings": [],
            "file_type": "unknown",
            "message": f"ফাইল পড়তে সমস্যা হয়েছে: {exc}",
        }

    file_size = len(data)

    # ------------------------------------------------------------------ #
    # Step 2: Identify file type                                          #
    # ------------------------------------------------------------------ #
    file_type = _identify_file_type(data[:64] if len(data) >= 64 else data)

    # ------------------------------------------------------------------ #
    # Step 3: ELF section names                                           #
    # ------------------------------------------------------------------ #
    sections: List[str] = []
    if data[:4] == b'\x7fELF':
        sections = _parse_elf_sections(data)

    # ------------------------------------------------------------------ #
    # Step 4: Extract printable strings                                   #
    # ------------------------------------------------------------------ #
    all_strings = _extract_printable_strings(data)

    # ------------------------------------------------------------------ #
    # Step 5: Highlight Python-related strings                            #
    # ------------------------------------------------------------------ #
    python_strings: List[str] = []
    for s in all_strings:
        lower_s = s.lower()
        if any(kw.lower() in lower_s for kw in PYTHON_KEYWORDS):
            python_strings.append(s)

    # ------------------------------------------------------------------ #
    # Step 6: Embedded base64 detection                                   #
    # ------------------------------------------------------------------ #
    b64_findings = _find_and_decode_base64(data)

    # ------------------------------------------------------------------ #
    # Step 7: Build the report                                            #
    # ------------------------------------------------------------------ #
    report_lines = [
        "╔══════════════════════════════════════╗",
        "║      .so FILE ANALYSIS REPORT        ║",
        "╚══════════════════════════════════════╝\n",
        f"📁 File size    : {file_size:,} bytes ({file_size / 1024:.1f} KB)",
        f"🔍 File type    : {file_type}",
        f"📊 Total strings: {len(all_strings)} found",
        f"🐍 Python-related strings: {len(python_strings)} found",
        f"🔐 Base64 blobs : {len(b64_findings)} found",
        "",
    ]

    # ELF sections
    if sections:
        report_lines.append("📂 ELF Sections:")
        for sec in sections[:20]:  # Limit display
            report_lines.append(f"   • {sec}")
        if len(sections) > 20:
            report_lines.append(f"   ... and {len(sections) - 20} more")
        report_lines.append("")

    # Python-related strings (most important)
    if python_strings:
        report_lines.append("🐍 Python-Related Strings Found:")
        report_lines.append("─" * 40)
        for s in python_strings[:40]:  # Limit to 40
            # Truncate long strings
            display = s[:120] + ("..." if len(s) > 120 else "")
            report_lines.append(f"  {display}")
        if len(python_strings) > 40:
            report_lines.append(f"  ... and {len(python_strings) - 40} more")
        report_lines.append("")
    else:
        report_lines.append("🐍 কোনো Python-related string পাওয়া যায়নি।\n")

    # Base64 findings
    if b64_findings:
        report_lines.append("🔐 Embedded Base64 Strings (decoded preview):")
        report_lines.append("─" * 40)
        for i, (snippet, preview) in enumerate(b64_findings, 1):
            report_lines.append(f"  [{i}] Original: {snippet}")
            report_lines.append(f"      Decoded : {preview}")
            report_lines.append("")
    else:
        report_lines.append("🔐 কোনো embedded base64 string পাওয়া যায়নি।\n")

    # General strings sample
    report_lines.append("📝 General Strings Sample (first 30):")
    report_lines.append("─" * 40)
    for s in all_strings[:30]:
        display = s[:100] + ("..." if len(s) > 100 else "")
        report_lines.append(f"  {display}")
    if len(all_strings) > 30:
        report_lines.append(f"  ... ({len(all_strings) - 30} more strings not shown)")

    report = "\n".join(report_lines)

    # Truncate if too long for Telegram
    if len(report) > MAX_OUTPUT_CHARS:
        report = report[:MAX_OUTPUT_CHARS] + "\n\n... [output truncated]"

    return {
        "success": True,
        "report": report,
        "python_strings": python_strings[:20],
        "b64_findings": b64_findings,
        "file_type": file_type,
        "message": ".so ফাইল থেকে স্ট্রিং এক্সট্র্যাক্ট করা হয়েছে।",
    }
