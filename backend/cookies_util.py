import base64
import json
import os
import re
from pathlib import Path

COOKIE_HEADER = "# Netscape HTTP Cookie File\n"

YOUTUBE_COOKIE_HINTS = (
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LOGIN_INFO",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "VISITOR_INFO1_LIVE",
)


def cookie_storage_path() -> Path:
    return Path(__file__).parent / "cookies.txt"


def decode_cookie_blob(raw: str) -> str:
    text = (raw or "").strip().lstrip("\ufeff")
    if not text:
        return ""

    if text.lower().startswith("base64:"):
        decoded = base64.b64decode(text.split(":", 1)[1].strip())
        text = decoded.decode("utf-8", errors="replace")

    looks_escaped = "\\n" in text or "\\t" in text
    has_real_newlines = "\n" in text or "\r" in text
    if looks_escaped and not has_real_newlines:
        try:
            text = bytes(text, "utf-8").decode("unicode_escape")
        except Exception:
            text = text.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

    return text.strip().lstrip("\ufeff")


def _is_youtube_domain(domain: str) -> bool:
    d = domain.lower().lstrip("#httponly_").lstrip(".")
    return d.endswith("youtube.com") or d.endswith("google.com") or d.endswith("youtube-nocookie.com")


def _netscape_line(domain: str, include_sub: bool, path: str, secure: bool, expiry: int, name: str, value: str, http_only: bool = False) -> str:
    domain = (domain or "").strip()
    if not domain:
        return ""
    if http_only and not domain.lower().startswith("#httponly_"):
        domain = f"#HttpOnly_{domain}"
    flag = "TRUE" if include_sub or domain.startswith(".") else "FALSE"
    sec = "TRUE" if secure else "FALSE"
    return f"{domain}\t{flag}\t{path or '/'}\t{sec}\t{int(expiry or 0)}\t{name}\t{value}"


def _from_json_cookies(payload) -> list[str]:
    cookies = payload
    if isinstance(payload, dict):
        cookies = payload.get("cookies") or payload.get("Cookies") or []
    if not isinstance(cookies, list):
        return []

    lines = []
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("Name") or "")
        value = str(item.get("value") or item.get("Value") or "")
        if not name:
            continue
        domain = str(item.get("domain") or item.get("Domain") or ".youtube.com")
        path = str(item.get("path") or item.get("Path") or "/")
        secure = bool(item.get("secure") or item.get("Secure"))
        http_only = bool(item.get("httpOnly") or item.get("httponly") or item.get("HttpOnly"))
        expiry = item.get("expirationDate") or item.get("expires") or item.get("expiry") or 0
        try:
            expiry = int(float(expiry))
        except (TypeError, ValueError):
            expiry = 0
        include_sub = domain.startswith(".") or bool(item.get("hostOnly") is False)
        if not _is_youtube_domain(domain):
            continue
        line = _netscape_line(domain, include_sub, path, secure, expiry, name, value, http_only)
        if line:
            lines.append(line)
    return lines


def _from_header_string(text: str) -> list[str]:
    cleaned = text
    if cleaned.lower().startswith("cookie:"):
        cleaned = cleaned.split(":", 1)[1]
    cleaned = cleaned.replace("\n", " ").strip()
    if "=" not in cleaned or ";" not in cleaned and cleaned.count("=") < 2:
        if ";" not in cleaned and cleaned.count("=") == 1:
            pass
        elif ";" not in cleaned:
            return []

    lines = []
    for part in cleaned.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue
        lines.append(_netscape_line(".youtube.com", True, "/", True, 0, name, value, False))
    return lines


def _from_netscape_text(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if line.lower().startswith("#httponly_"):
                line = line
            else:
                continue

        parts = re.split(r"\t+", line)
        if len(parts) < 7:
            parts = re.split(r"\s+", line, maxsplit=6)
        if len(parts) < 7:
            continue
        domain, flag, path, secure, expiry, name, value = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        if not _is_youtube_domain(domain):
            continue
        try:
            expiry_i = int(float(expiry))
        except (TypeError, ValueError):
            expiry_i = 0
        include_sub = flag.upper() == "TRUE"
        is_secure = secure.upper() == "TRUE"
        http_only = domain.lower().startswith("#httponly_")
        if http_only:
            domain = re.sub(r"(?i)^#httponly_", "", domain)
        built = _netscape_line(domain, include_sub, path, is_secure, expiry_i, name, value, http_only)
        if built:
            lines.append(built)
    return lines


def normalize_cookie_text(raw: str) -> str:
    text = decode_cookie_blob(raw)
    if not text:
        raise ValueError("Cookie mətni boşdur.")

    lines: list[str] = []
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("JSON cookie faylı oxunmadı. Netscape və ya Cookie-Editor formatı göndərin.") from exc
        lines = _from_json_cookies(payload)
    elif "\t" in text or re.search(r"TRUE\s+/", text) or "# Netscape" in text or "# HTTP Cookie File" in text:
        lines = _from_netscape_text(text)
        if not lines:
            lines = _from_header_string(text)
    else:
        lines = _from_header_string(text)
        if not lines:
            lines = _from_netscape_text(text)

    if not lines:
        raise ValueError(
            "Cookie qəbul olunmadı. Netscape cookies.txt, Cookie-Editor JSON, və ya "
            "Cookie header formatı göndərin (youtube.com cookie-ləri olmalıdır)."
        )

    names = {line.split("\t")[5] for line in lines if line.count("\t") >= 6}
    if not any(name in names for name in YOUTUBE_COOKIE_HINTS):
        raise ValueError(
            "Faylda YouTube login cookie-ləri yoxdur. Incognito pəncərədə YouTube-a daxil olub "
            "https://www.youtube.com/robots.txt səhifəsindən cookies.txt ixrac edin."
        )

    unique = []
    seen = set()
    for line in lines:
        key = line.split("\t")[5] if line.count("\t") >= 6 else line
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)

    return COOKIE_HEADER + "\n".join(unique) + "\n"


def write_cookie_file(raw: str, dest: Path | None = None) -> Path:
    path = dest or cookie_storage_path()
    normalized = normalize_cookie_text(raw)
    path.write_text(normalized, encoding="utf-8")
    return path


def cookie_status(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {"loaded": False, "count": 0, "has_login": False, "path": None}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"loaded": False, "count": 0, "has_login": False, "path": None}
    names = []
    for line in text.splitlines():
        if not line or line.startswith("#") and not line.lower().startswith("#httponly_"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            names.append(parts[5])
    return {
        "loaded": True,
        "count": len(names),
        "has_login": any(n in YOUTUBE_COOKIE_HINTS for n in names),
        "path": str(Path(path).name),
    }
