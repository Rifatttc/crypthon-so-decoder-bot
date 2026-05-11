# -*- coding: utf-8 -*-
"""
crypthon_decoder.py
-------------------
Decodes Crypthon-style obfuscated Python files commonly used in
Bangladesh/India communities.

Supported obfuscation patterns:
  - base64 → zlib.decompress → marshal.loads
  - marshal → zlib → base64 (any order)
  - Multiple nested layers (up to 5-6 deep)
  - exec(compile(..., '<string>', 'exec'))
  - exec(marshal.loads(...))
  - Long base64 strings embedded in .py source

Author: Crypthon & SO Decoder Bot
"""

import base64
import dis
import io
import marshal
import re
import types
import zlib
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Type alias for the result dictionary
# ---------------------------------------------------------------------------
DecodeResult = Dict[str, Any]


# ---------------------------------------------------------------------------
# Regex patterns used to extract payloads from Python source code
# ---------------------------------------------------------------------------

# Matches a long base64-like string (quoted, any quotes, ≥ 40 chars)
_RE_BASE64_STRING = re.compile(
    r"""(?:b?["'])((?:[A-Za-z0-9+/=]{4}){10,}(?:[A-Za-z0-9+/=]{0,3}))(?:["'])""",
    re.DOTALL,
)

# Matches base64.b64decode(...) or base64.decodebytes(...) patterns
_RE_B64_CALL = re.compile(
    r"""base64\.(?:b64decode|decodebytes|decodestring)\s*\(\s*(?:b?)(['"])(.*?)\1\s*\)""",
    re.DOTALL,
)

# Matches zlib.decompress(...)
_RE_ZLIB_CALL = re.compile(r"""zlib\.decompress\s*\(""")

# Matches marshal.loads(...)
_RE_MARSHAL_CALL = re.compile(r"""marshal\.loads\s*\(""")

# Matches exec(...) / eval(...)
_RE_EXEC_CALL = re.compile(r"""(?:exec|eval)\s*\(""")

# Matches compile(...)
_RE_COMPILE_CALL = re.compile(r"""compile\s*\(""")


# ---------------------------------------------------------------------------
# Helper: safely decode a base64 payload (handles padding issues)
# ---------------------------------------------------------------------------

def _safe_b64decode(data: bytes | str) -> Optional[bytes]:
    """
    Attempt to base64-decode data, fixing padding if needed.
    Returns decoded bytes or None on failure.
    """
    if isinstance(data, str):
        data = data.strip().encode()
    else:
        data = data.strip()

    # Fix padding
    pad = len(data) % 4
    if pad:
        data += b"=" * (4 - pad)

    try:
        return base64.b64decode(data)
    except Exception:
        try:
            return base64.b64decode(data, validate=False)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Helper: try all decompression methods on raw bytes
# ---------------------------------------------------------------------------

def _try_decompress(data: bytes) -> Optional[bytes]:
    """
    Try zlib decompression with multiple wbits values.
    Returns decompressed bytes or None.
    """
    # wbits values to try: standard zlib, raw deflate, gzip
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(data, wbits)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Helper: try marshal.loads on bytes
# ---------------------------------------------------------------------------

def _try_marshal_loads(data: bytes) -> Optional[types.CodeType]:
    """
    Try to unmarshal bytes into a Python code object.
    Returns code object or None.
    """
    try:
        return marshal.loads(data)
    except Exception:
        # Sometimes there's a 4-byte magic header to skip
        for skip in (4, 8, 12, 16):
            try:
                return marshal.loads(data[skip:])
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Core: disassemble a code object to readable text
# ---------------------------------------------------------------------------

def _disassemble_code_object(code_obj: types.CodeType) -> str:
    """
    Disassemble a Python code object using dis.dis() and return as string.
    """
    buf = io.StringIO()
    try:
        dis.dis(code_obj, file=buf)
    except Exception as exc:
        return f"[Disassembly error: {exc}]"
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Core: extract all readable strings from a code object tree
# ---------------------------------------------------------------------------

def _extract_strings_from_code(
    code_obj: types.CodeType,
    collected: Optional[List[str]] = None,
) -> List[str]:
    """
    Recursively walk a code object and collect all string constants.
    Filters to strings that look meaningful (printable, length ≥ 4).
    """
    if collected is None:
        collected = []

    for const in code_obj.co_consts:
        if isinstance(const, str) and len(const) >= 4:
            # Keep only printable strings
            if all(c.isprintable() or c in ("\n", "\t") for c in const):
                collected.append(const)
        elif isinstance(const, bytes) and len(const) >= 4:
            try:
                decoded = const.decode("utf-8", errors="replace")
                collected.append(f"[bytes] {decoded}")
            except Exception:
                pass
        elif isinstance(const, types.CodeType):
            # Recurse into nested code objects (inner functions, lambdas, etc.)
            _extract_strings_from_code(const, collected)

    return collected


# ---------------------------------------------------------------------------
# Core: single-layer decode attempt — tries all known transformations
# ---------------------------------------------------------------------------

def _single_layer_decode(data: bytes) -> Tuple[Optional[bytes], str]:
    """
    Attempt to peel off one layer of obfuscation from raw bytes.

    Returns:
        (decoded_bytes, method_description) or (None, "") if all methods fail.
    """
    # --- Strategy 1: base64 → zlib → marshal (most common Crypthon pattern) ---
    b64_decoded = _safe_b64decode(data)
    if b64_decoded:
        zlib_decoded = _try_decompress(b64_decoded)
        if zlib_decoded:
            return zlib_decoded, "base64 → zlib"
        # Maybe base64 → marshal directly
        code = _try_marshal_loads(b64_decoded)
        if code:
            return b64_decoded, "base64 (→ marshal)"
        # base64 only might reveal another base64 layer
        return b64_decoded, "base64"

    # --- Strategy 2: zlib only ---
    zlib_decoded = _try_decompress(data)
    if zlib_decoded:
        return zlib_decoded, "zlib"

    return None, ""


# ---------------------------------------------------------------------------
# Main public function: multi-layer decode
# ---------------------------------------------------------------------------

def decode_crypthon(file_path: str) -> DecodeResult:
    """
    Main entry point for decoding a Crypthon-obfuscated Python file.

    Steps:
      1. Read the file as text (source code extraction)
      2. Extract the longest / most likely obfuscated payload using regex
      3. Attempt multi-layer decoding (up to MAX_LAYERS)
      4. If we reach a marshal code object, disassemble + extract strings
      5. Return a structured result dict

    Args:
        file_path: Path to the .py file to decode.

    Returns:
        DecodeResult dict with keys:
            success (bool), code (str), method (str),
            layers (int), strings (list), message (str)
    """
    MAX_LAYERS = 8  # Safety limit to prevent infinite loops

    # ------------------------------------------------------------------ #
    # Step 1: Read the file                                                #
    # ------------------------------------------------------------------ #
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            source_text = fh.read()
    except Exception as exc:
        return {
            "success": False,
            "code": "",
            "method": "",
            "layers": 0,
            "strings": [],
            "message": f"ফাইল পড়তে সমস্যা হয়েছে: {exc}",
        }

    # ------------------------------------------------------------------ #
    # Step 2: Extract the obfuscated payload from source                  #
    # ------------------------------------------------------------------ #
    # We try multiple extraction strategies and pick the longest result.

    payload: Optional[bytes] = None
    extraction_method = ""

    # Strategy A: Find all base64 strings in source, pick the longest
    all_b64_matches = _RE_BASE64_STRING.findall(source_text)
    if all_b64_matches:
        # Sort by length descending, pick the longest
        longest = max(all_b64_matches, key=len)
        decoded = _safe_b64decode(longest)
        if decoded and len(decoded) > 20:
            payload = decoded
            extraction_method = "regex-extracted base64 string"

    # Strategy B: If file itself looks like raw base64 (no Python syntax)
    if payload is None:
        stripped = source_text.strip()
        # Check if the whole file is one big base64 blob
        if re.match(r'^[A-Za-z0-9+/=\n]+$', stripped) and len(stripped) > 40:
            decoded = _safe_b64decode(stripped)
            if decoded:
                payload = decoded
                extraction_method = "whole-file base64"

    # Strategy C: File is binary-like — read raw bytes
    if payload is None:
        try:
            with open(file_path, "rb") as fh:
                raw_bytes = fh.read()
            # Try zlib directly on raw file
            zlib_result = _try_decompress(raw_bytes)
            if zlib_result:
                payload = zlib_result
                extraction_method = "raw zlib compressed file"
            else:
                payload = raw_bytes
                extraction_method = "raw file bytes"
        except Exception:
            pass

    if payload is None:
        return {
            "success": False,
            "code": source_text[:2000],
            "method": "none",
            "layers": 0,
            "strings": [],
            "message": "কোনো obfuscated payload খুঁজে পাওয়া যায়নি। ফাইলটি সম্ভবত obfuscate করা নয়।",
        }

    # ------------------------------------------------------------------ #
    # Step 3: Multi-layer decode loop                                      #
    # ------------------------------------------------------------------ #
    current_data = payload
    layers_decoded = 0
    methods_used: List[str] = [extraction_method]
    final_code_object: Optional[types.CodeType] = None

    for layer in range(MAX_LAYERS):
        # First, check if current_data is already a valid marshal code object
        code_obj = _try_marshal_loads(current_data)
        if code_obj is not None:
            final_code_object = code_obj
            layers_decoded = layer + 1
            methods_used.append(f"marshal.loads (layer {layer + 1})")
            break

        # Try to peel off one layer
        next_data, method = _single_layer_decode(current_data)

        if next_data is None:
            # No further decoding possible
            break

        # Sanity check: decoded data should be non-trivially smaller or different
        if next_data == current_data:
            break  # No progress, stop

        layers_decoded += 1
        methods_used.append(f"{method} (layer {layers_decoded})")
        current_data = next_data

    # ------------------------------------------------------------------ #
    # Step 4: Try to marshal the final data if not done yet               #
    # ------------------------------------------------------------------ #
    if final_code_object is None and layers_decoded > 0:
        final_code_object = _try_marshal_loads(current_data)
        if final_code_object:
            methods_used.append("marshal.loads (final)")

    # ------------------------------------------------------------------ #
    # Step 5: Build the output                                             #
    # ------------------------------------------------------------------ #
    if final_code_object is not None:
        # We have a proper code object — disassemble it
        disasm = _disassemble_code_object(final_code_object)
        strings = _extract_strings_from_code(final_code_object)

        # Build a human-readable representation
        output_parts = [
            "# ========== DECODED BYTECODE (dis.dis output) ==========\n",
            disasm,
            "\n\n# ========== EXTRACTED STRING CONSTANTS ==========\n",
        ]
        for i, s in enumerate(strings[:80], 1):  # Limit to 80 strings
            output_parts.append(f"# [{i:02d}] {repr(s)}\n")

        if not strings:
            output_parts.append("# (কোনো string constant পাওয়া যায়নি)\n")

        return {
            "success": True,
            "code": "".join(output_parts),
            "method": " → ".join(methods_used),
            "layers": layers_decoded,
            "strings": strings[:50],
            "message": "ডিকোড সফল হয়েছে! Bytecode disassembly দেখানো হচ্ছে।",
        }

    elif layers_decoded > 0:
        # We decoded some layers but couldn't get a code object
        # Try to interpret as text (maybe it's Python source after all)
        try:
            decoded_text = current_data.decode("utf-8", errors="replace")
        except Exception:
            decoded_text = repr(current_data[:500])

        return {
            "success": True,
            "code": decoded_text,
            "method": " → ".join(methods_used),
            "layers": layers_decoded,
            "strings": [],
            "message": (
                "আংশিক ডিকোড সফল হয়েছে! "
                "সম্পূর্ণ Python source পাওয়া যায়নি, আংশিক রেজাল্ট দিচ্ছি..."
            ),
        }

    else:
        # Complete failure — return source as-is with a note
        return {
            "success": False,
            "code": source_text[:3000],
            "method": "none",
            "layers": 0,
            "strings": [],
            "message": (
                "দুঃখিত, পুরোপুরি ডিকোড করা সম্ভব হয়নি। "
                "ফাইলটি অচেনা encryption বা custom obfuscation ব্যবহার করতে পারে। "
                "মূল source code দেখানো হচ্ছে।"
            ),
        }


# ---------------------------------------------------------------------------
# Utility: detect if a file is likely Crypthon/obfuscated
# ---------------------------------------------------------------------------

def is_likely_obfuscated(source_text: str) -> bool:
    """
    Quick heuristic check: does this file look obfuscated?
    Returns True if it exhibits common obfuscation indicators.
    """
    indicators = 0

    # Very long single-line strings are suspicious
    lines = source_text.splitlines()
    for line in lines:
        stripped = line.strip()
        if len(stripped) > 200 and re.match(r'^[A-Za-z0-9+/=\'\"b]+$', stripped):
            indicators += 2

    # Presence of typical obfuscation function calls
    if _RE_B64_CALL.search(source_text):
        indicators += 1
    if _RE_ZLIB_CALL.search(source_text):
        indicators += 1
    if _RE_MARSHAL_CALL.search(source_text):
        indicators += 2
    if _RE_EXEC_CALL.search(source_text):
        indicators += 1
    if _RE_COMPILE_CALL.search(source_text):
        indicators += 1

    # Very few lines with very long content = obfuscated
    if len(lines) <= 10 and any(len(l) > 500 for l in lines):
        indicators += 2

    return indicators >= 3
