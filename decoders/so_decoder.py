# decoders/so_decoder.py
import re
import zlib
imoutputport base64
from typing import Dict, Any, List

def extract_strings(data: bytes, min_len: int = 5) -> List[str]:
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


def try_recover_code(b64_candidate: str) -> Dict[str, Any]:
    """Try multiple decoding strategies"""
    result = {"success": False, "strategy": None, "content": None}

    try:
        raw = base64.b64decode(b64_candidate, validate=False)

        strategies = [
            ("marshal+zlib", lambda x: marshal.loads(zlib.decompress(x))),
            ("zlib+text", lambda x: zlib.decompress(x).decode('utf-8', errors='ignore')),
            ("raw_text", lambda x: x.decode('utf-8', errors='ignore')),
        ]

        import marshal
        for name, func in strategies:
            try:
                decoded = func(raw)
                text = str(decoded)
                if any(kw in text for kw in ['def ', 'import ', 'password', 'token', 'login', 'facebook']):
                    result["success"] = True
                    result["strategy"] = name
                    result["content"] = text[:4000]
                    return result
            except:
                continue
    except:
        pass

    return result


def decode_so_file(file_path: str) -> Dict[str, Any]:
    result = {
        "success": False,
        "module_name": None,
        "total_strings": 0,
        "core_logic": [],
        "network_strings": [],
        "python_api": [],
        "recovered_code": [],
        "message": ""
    }

    try:
        with open(file_path, "rb") as f:
            data = f.read()

        all_strings = extract_strings(data)
        result["total_strings"] = len(all_strings)

        # Find module name
        for s in all_strings:
            if s.startswith("PyInit_"):
                result["module_name"] = s.replace("PyInit_", "")
                break

        # Keywords
        core_keywords = ['password', 'token', 'login', 'access_token', 'b-graph', 'mbasic.facebook']
        network_keywords = ['http', 'https', 'proxy', 'requests', 'httpx', 'mechanize']
        python_api_keywords = ['PyImport_', 'PyModule_', 'PyObject_', 'PyDict_']

        for s in all_strings:
            lower_s = s.lower()

            if any(kw in lower_s for kw in core_keywords):
                result["core_logic"].append(s)
            elif any(kw in lower_s for kw in network_keywords):
                result["network_strings"].append(s)
            elif any(kw in s for kw in python_api_keywords):
                result["python_api"].append(s)

        # Find and decode long base64
        raw_text = data.decode('latin-1', errors='ignore')
        b64_list = re.findall(r'[A-Za-z0-9+/=]{120,}', raw_text)

        for b64 in b64_list[:25]:
            recovered = try_recover_code(b64)
            if recovered["success"]:
                result["recovered_code"].append({
                    "strategy": recovered["strategy"],
                    "content": recovered["content"]
                })
                result["success"] = True

        if result["recovered_code"]:
            result["message"] = "লুকানো Python কোড/লজিক সফলভাবে রিকভার করা হয়েছে!"
        elif result["core_logic"]:
            result["success"] = True
            result["message"] = "গুরুত্বপূর্ণ লজিক স্ট্রিং পাওয়া গেছে।"
        else:
            result["message"] = "সরাসরি Python সোর্স কোড পাওয়া যায়নি।"

    except Exception as e:
        result["message"] = f"Error: {str(e)}"

    return result


def format_so_result(result: Dict[str, Any], filename: str) -> str:
    output = "═══════════════════════════════════════════════\n"
    output += "🔬 .so FILE DECODER - MAXIMUM RECOVERY\n"
    output += "═══════════════════════════════════════════════\n\n"

    output += f"📄 File          : {filename}\n"
    output += f"📦 Total Strings : {result.get('total_strings', 0)}\n"
    if result.get("module_name"):
        output += f"🧩 Module        : {result['module_name']}\n"
    output += "\n"

    # Recovered Code
    if result.get("recovered_code"):
        output += "🔓 RECOVERED HIDDEN CODE:\n"
        for i, item in enumerate(result["recovered_code"][:2], 1):
            output += f"\n[Strategy: {item['strategy']}]\n"
            output += f"```python\n{item['content']}\n```\n"
        output += "\n"

    # Core Logic (Most Important)
    if result.get("core_logic"):
        output += "🔥 CORE LOGIC STRINGS (Password/Login/Token):\n"
        for s in result["core_logic"][:30]:
            output += f"• {s}\n"
        output += "\n"

    # Network Related
    if result.get("network_strings"):
        output += "🌐 NETWORK & API STRINGS:\n"
        for s in result["network_strings"][:20]:
            output += f"• {s}\n"
        output += "\n"

    # Python C API
    if result.get("python_api"):
        output += "🐍 PYTHON C API:\n"
        for s in result["python_api"][:15]:
            output += f"• {s}\n"
        output += "\n"

    output += f"ℹ️ Status: {result.get('message', '')}\n"
    output += "═══════════════════════════════════════════════"

    return output
