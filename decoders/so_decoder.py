# decoders/so_decoder.py
import re
import zlib
import base64
from typing import Dict, Any, List

def extraoutputings(data: bytes, min_len: int = 5) -> List[str]:
    """Extract all printable strings from binary"""
    strings = []
    current = []
    for byte in data:
        if 32 <= byte <= 126:
            current.append(chr(byte))
        else:
            if len(current) >= min_len:
                strings.append(''.join(current))
            current = []
    if len(current) >= min_len:
        strings.append(''.join(current))
    return strings


def try_decode_base64_payload(b64_str: str) -> Dict[str, Any]:
    """Try to recover Python code from base64 string"""
    result = {"success": False, "type": None, "data": None}

    try:
        raw = base64.b64decode(b64_str, validate=False)

        # Strategy 1: zlib → marshal
        try:
            decompressed = zlib.decompress(raw)
            import marshal
            code_obj = marshal.loads(decompressed)
            result["success"] = True
            result["type"] = "marshal+zlib"
            result["data"] = str(code_obj)
            return result
        except:
            pass

        # Strategy 2: Direct zlib
        try:
            text = zlib.decompress(raw).decode('utf-8', errors='ignore')
            if any(x in text for x in ['def ', 'import ', 'password', 'token', 'login']):
                result["success"] = True
                result["type"] = "zlib"
                result["data"] = text[:3500]
                return result
        except:
            pass

        # Strategy 3: Raw base64 text
        text = raw.decode('utf-8', errors='ignore')
        if len(text) > 80 and any(x in text for x in ['def ', 'import ', 'password', 'token']):
            result["success"] = True
            result["type"] = "base64"
            result["data"] = text[:3000]
            return result

    except:
        pass

    return result


def decode_so_file(file_path: str) -> Dict[str, Any]:
    result = {
        "success": False,
        "filename": "",
        "total_strings": 0,
        "module_name": None,
        "important_logic": [],
        "python_api": [],
        "b64_recovered": [],
        "message": ""
    }

    try:
        with open(file_path, "rb") as f:
            data = f.read()

        all_strings = extract_strings(data)
        result["total_strings"] = len(all_strings)

        # Find PyInit_ module name
        for s in all_strings:
            if s.startswith("PyInit_"):
                result["module_name"] = s.replace("PyInit_", "")
                break

        # Important keywords for cracking tools
        important_keywords = [
            'password', 'token', 'login', 'access_token', 'b-graph.facebook',
            'mbasic.facebook', 'proxyscrape', 'ThreadPool', ' mechanize',
            'httpx', 'requests', 'Facebook', 'graph', 'auth/login'
        ]

        for s in all_strings:
            # Python C API
            if s.startswith("Py") and any(x in s for x in ["Import", "Module", "Dict", "Object"]):
                result["python_api"].append(s)

            # Core logic strings
            if any(kw.lower() in s.lower() for kw in important_keywords):
                if len(s) > 10:
                    result["important_logic"].append(s)

        # Search long base64 inside binary
        raw_text = data.decode('latin-1', errors='ignore')
        b64_list = re.findall(r'[A-Za-z0-9+/=]{100,}', raw_text)

        for b64 in b64_list[:20]:
            recovered = try_decode_base64_payload(b64)
            if recovered["success"]:
                result["b64_recovered"].append({
                    "type": recovered["type"],
                    "preview": recovered["data"][:2000] if recovered["data"] else ""
                })
                result["success"] = True

        if result["b64_recovered"]:
            result["message"] = "লুকানো Python কোড/লজিক পাওয়া গেছে!"
        elif result["important_logic"]:
            result["success"] = True
            result["message"] = "গুরুত্বপূর্ণ লজিক স্ট্রিং পাওয়া গেছে।"
        else:
            result["message"] = "সরাসরি Python সোর্স কোড পাওয়া যায়নি।"

    except Exception as e:
        result["message"] = f"Error: {str(e)}"

    return result


def format_so_result(result: Dict[str, Any], filename: str) -> str:
    output = "════════════════════════════════════════\n"
    output += "🔬 .so FILE DECODER RESULT\n"
    output += "════════════════════════════════════════\n\n"
    output += f"📄 File       : {filename}\n"
    output += f"📦 Total Strings : {result.get('total_strings', 0)}\n"

    if result.get("module_name"):
        output += f"🧩 Module Name  : {result['module_name']}\n"

    output += "\n"

    # Recovered code from base64
    if result.get("b64_recovered"):
        output += "🔓 সম্ভাব্য লুকানো কোড:\n"
        for item in result["b64_recovered"][:2]:
            output += f"Type: {item['type']}\n"
            output += f"```python\n{item['preview']}\n```\n\n"

    # Important logic (Facebook cracking related)
    if result.get("important_logic"):
        output += "🔥 গুরুত্বপূর্ণ লজিক স্ট্রিংস:\n"
        for s in result["important_logic"][:25]:
            output += f"• {s}\n"
        output += "\n"

    # Python C API
    if result.get("python_api"):
        output += "🐍 Python C API:\n"
        for s in result["python_api"][:15]:
            output += f"• {s}\n"
        output += "\n"

    output += f"ℹ️ {result.get('message', '')}\n"
    output += "════════════════════════════════════════"

    return output
