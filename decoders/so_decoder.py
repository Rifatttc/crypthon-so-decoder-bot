# decoders/so_decoder.py
import re
import zlib
import base64
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
    result = {"success": False, "strategy": None, "content": None}
    try:
        raw = base64.b64decode(b64_candidate, validate=False)
        import marshal

        strategies = [
            ("marshal+zlib", lambda x: marshal.loads(zlib.decompress(x))),
            ("zlib_text", lambda x: zlib.decompress(x).decode('utf-8', errors='ignore')),
        ]

        for name, func in strategies:
            try:
                decoded = func(raw)
                text = str(decoded)
                if any(kw in text for kw in ['def ', 'import ', 'password', 'token', 'login']):
                    result["success"] = True
                    result["strategy"] = name
                    result["content"] = text[:3500]
                    return result
            except:
                continue
    except:
        pass
    return result


def decode_so_file(file_path: str) -> Dict[str, Any]:
    result = {
        "success": False,
        "file_type": "ELF Shared Object (.so)",
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

        for s in all_strings:
            if s.startswith("PyInit_"):
                result["module_name"] = s.replace("PyInit_", "")
                break

        core_keywords = ['password', 'token', 'login', 'access_token', 'b-graph', 'mbasic.facebook']
        network_keywords = ['http', 'https', 'proxy', 'requests', 'httpx']

        for s in all_strings:
            lower = s.lower()
            if any(kw in lower for kw in core_keywords):
                result["core_logic"].append(s)
            elif any(kw in lower for kw in network_keywords):
                result["network_strings"].append(s)
            elif s.startswith("Py") and any(x in s for x in ["Import_", "Module_", "Object_"]):
                result["python_api"].append(s)

        raw_text = data.decode('latin-1', errors='ignore')
        b64_list = re.findall(r'[A-Za-z0-9+/=]{120,}', raw_text)

        for b64 in b64_list[:20]:
            recovered = try_recover_code(b64)
            if recovered["success"]:
                result["recovered_code"].append(recovered)
                result["success"] = True

        if result["recovered_code"]:
            result["message"] = "লুকানো কোড পাওয়া গেছে!"
        elif result["core_logic"]:
            result["success"] = True
            result["message"] = "গুরুত্বপূর্ণ লজিক স্ট্রিং পাওয়া গেছে।"
        else:
            result["message"] = "কোনো গুরুত্বপূর্ণ লজিক পাওয়া যায়নি।"

    except Exception as e:
        result["message"] = str(e)

    return result


def format_so_result(result: Dict[str, Any], filename: str) -> str:
    output = "═══════════════════════════════════════════════\n"
    output += "🔬 .so FILE DECODER\n"
    output += "═══════════════════════════════════════════════\n\n"

    output += f"📄 File: {filename}\n"
    output += f"📦 Type: {result.get('file_type', 'Unknown')}\n"
    if result.get("module_name"):
        output += f"🧩 Module: {result['module_name']}\n"
    output += f"📊 Total Strings: {result.get('total_strings', 0)}\n\n"

    if result.get("recovered_code"):
        output += "🔓 RECOVERED CODE:\n"
        for item in result["recovered_code"][:1]:
            output += f"```python\n{item['content']}\n```\n\n"

    if result.get("core_logic"):
        output += "🔥 CORE LOGIC (Password / Login / Token):\n"
        for s in result["core_logic"][:20]:
            output += f"• {s}\n"
        output += "\n"

    if result.get("network_strings"):
        output += "🌐 Network Related:\n"
        for s in result["network_strings"][:15]:
            output += f"• {s}\n"
        output += "\n"

    output += f"ℹ️ {result.get('message', '')}\n"
    output += "═══════════════════════════════════════════════"
    return outputoutput
