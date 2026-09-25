import os
import re
import uuid
import shutil
import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

from cookies_util import cookie_status, cookie_storage_path, decode_cookie_blob, write_cookie_file

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

BIN_DIR = Path(__file__).parent / "bin"
BIN_DIR.mkdir(exist_ok=True)

PLATFORM_PATTERNS = {
    "youtube":   [r"youtube\.com", r"youtu\.be"],
    "tiktok":    [r"tiktok\.com", r"vm\.tiktok\.com"],
    "instagram": [r"instagram\.com"],
    "twitter":   [r"twitter\.com", r"x\.com"],
    "facebook":  [r"facebook\.com", r"fb\.watch"],
    "reddit":    [r"reddit\.com"],
    "pinterest": [r"pinterest\.com", r"pin\.it"],
}

def detect_platform(url: str) -> str:
    lower = url.lower()
    for platform, patterns in PLATFORM_PATTERNS.items():
        if any(re.search(p, lower) for p in patterns):
            return platform
    return "generic"

def get_youtube_id(url: str) -> str | None:
    patterns = [
        r'(?:v=|/shorts/|youtu\.be/|/embed/)([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def canonicalize_url(url: str) -> str:
    """Strip playlist/radio params so YouTube tab extractor is not used."""
    video_id = get_youtube_id(url)
    if video_id:
        if "/shorts/" in url.lower():
            return f"https://www.youtube.com/shorts/{video_id}"
        return f"https://www.youtube.com/watch?v={video_id}"
    return url

def sanitize_filename(title: str, max_length: int = 120) -> str:
    # Clean filename preserving alphanumeric, spaces, and international chars
    clean = re.sub(r'[\\/*?:"<>|\x00-\x1f]', '', title)
    clean = re.sub(r'[\r\n\t]+', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        clean = "media"
    return clean[:max_length]

def get_uid() -> str:
    return uuid.uuid4().hex

# FFmpeg detection
FFMPEG_PATH = shutil.which("ffmpeg")
if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_PATH = None

def _which_runtime(name: str, extra: list[Path] | None = None) -> str | None:
    for cand in extra or []:
        if cand.exists():
            return str(cand.resolve())
    found = shutil.which(name)
    return found


def get_js_runtimes() -> dict:
    runtimes = {}
    deno = _which_runtime("deno", [
        BIN_DIR / "deno.exe",
        BIN_DIR / "deno",
        Path("/usr/local/bin/deno"),
    ])
    node = _which_runtime("node", [
        BIN_DIR / "node.exe",
        BIN_DIR / "node",
    ])
    if deno:
        runtimes["deno"] = {"path": deno}
    if node:
        runtimes["node"] = {"path": node}
    return runtimes


def get_cookie_file() -> str | None:
    env_cookie_path = cookie_storage_path()
    for env_key in ("YOUTUBE_COOKIES_B64", "YOUTUBE_COOKIES"):
        raw = os.environ.get(env_key)
        if not raw:
            continue
        blob = raw if env_key == "YOUTUBE_COOKIES" else f"base64:{raw.strip()}"
        try:
            write_cookie_file(blob, env_cookie_path)
            return str(env_cookie_path.resolve())
        except Exception:
            continue

    candidates = [
        env_cookie_path,
        DOWNLOAD_DIR / "cookies.txt",
        Path(__file__).parent.parent / "cookies.txt",
        Path("cookies.txt"),
    ]
    for cand in candidates:
        if cand.exists() and cand.stat().st_size > 50:
            dest = env_cookie_path
            try:
                raw = cand.read_text(encoding="utf-8", errors="replace")
                if cand.resolve() != dest.resolve() or "\t" not in raw:
                    write_cookie_file(raw, dest)
                    return str(dest.resolve())
            except Exception:
                return str(cand.resolve())
            return str(cand.resolve())
    return None


def _youtube_extractor_args(player_clients: list[str]) -> dict:
    return {
        "youtube": {
            "player_client": player_clients,
        },
        "youtubetab": {
            "skip": ["authcheck"],
        },
    }


def _merge_extractor_args(base: dict, extra: dict | None) -> dict:
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in (base or {}).items()}
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def build_ydl_opts(
    custom_opts: dict | None = None,
    use_cookies: bool = True,
    player_clients: list[str] | None = None,
) -> dict:
    clients = player_clients or ["android_vr", "tv", "tv_simply", "web_safari"]
    opts = {
        "quiet": True,
        "noplaylist": True,
        "extract_flat": False,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "no_warnings": True,
        "socket_timeout": 30,
        "geo_bypass": True,
        "geo_bypass_country": "US",
        "retries": 5,
        "extractor_retries": 3,
        "fragment_retries": 8,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10485760,
        "buffersize": 1024 * 64,
        "sleep_interval_requests": 0.5,
        "extractor_args": _youtube_extractor_args(clients),
        "http_headers": {
            "Accept-Language": "en-US,en;q=0.9,az;q=0.8",
        },
    }

    try:
        opts["impersonate"] = ImpersonateTarget.from_str("chrome")
    except Exception:
        pass

    js_runtimes = get_js_runtimes()
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes
        opts["remote_components"] = ["ejs:github"]

    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH

    if use_cookies:
        cookie_path = get_cookie_file()
        if cookie_path and os.path.exists(cookie_path):
            opts["cookiefile"] = cookie_path

    custom = dict(custom_opts or {})
    extra_extractor_args = custom.pop("extractor_args", None)
    opts.update(custom)
    opts["extractor_args"] = _merge_extractor_args(opts.get("extractor_args") or {}, extra_extractor_args)
    return opts

_INFO_CACHE: dict = {}
CACHE_TTL = 300  # 5 minutes

YOUTUBE_ATTEMPTS = [
    {"use_cookies": False, "clients": ["android_vr", "tv", "tv_simply"]},
    {"use_cookies": True, "clients": ["android_vr", "tv", "tv_simply"]},
    {"use_cookies": True, "clients": ["tv", "web_safari"]},
    {"use_cookies": False, "clients": ["web_safari", "tv"]},
]


def _ydl_attempts(need_cookies_available: bool = True):
    cookie_file = get_cookie_file() if need_cookies_available else None
    seen = []
    for attempt in YOUTUBE_ATTEMPTS:
        if attempt["use_cookies"] and not cookie_file:
            continue
        seen.append(attempt)
    if not seen:
        seen = [{"use_cookies": False, "clients": ["android_vr", "tv", "tv_simply"]}]
    return seen


def _ydl_extract(opts: dict, url: str, download: bool):
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download)
    except Exception as exc:
        if opts.get("impersonate") and "impersonate" in str(exc).lower():
            opts = dict(opts)
            opts.pop("impersonate", None)
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)
        raise


def _extract_info_sync(url: str, skip_download: bool, extra_opts: dict | None = None):
    last_error = None
    for attempt in _ydl_attempts():
        try:
            opts = build_ydl_opts(
                {
                    **(extra_opts or {}),
                    "skip_download": skip_download,
                    "playlist_items": "1",
                },
                use_cookies=attempt["use_cookies"],
                player_clients=attempt["clients"],
            )
            return _ydl_extract(opts, url, download=not skip_download)
        except Exception as exc:
            last_error = exc
            continue
    raise last_error or ValueError("Video məlumatları alına bilmədi.")


async def fetch_info(url: str) -> dict:
    url = canonicalize_url(url)
    now = time.time()
    if url in _INFO_CACHE:
        ts, cached = _INFO_CACHE[url]
        if now - ts < CACHE_TTL:
            return cached

    loop = asyncio.get_running_loop()

    try:
        info = await loop.run_in_executor(None, _extract_info_sync, url, True, None)
    except yt_dlp.utils.DownloadError as e2:
        raise ValueError(_friendly_ydl_error(str(e2)))
    except Exception as e2:
        raise ValueError(_friendly_ydl_error(str(e2)))

    if not info:
        raise ValueError("Video məlumatları alına bilmədi.")

    if "entries" in info and info["entries"]:
        entries = [e for e in info["entries"] if e]
        if entries:
            info = entries[0]

    size_bytes = info.get("filesize") or info.get("filesize_approx")
    size_str = ""
    if size_bytes:
        mb = round(size_bytes / (1024 * 1024), 1)
        size_str = f"~{mb} MB" if mb >= 1.0 else f"~{round(size_bytes / 1024, 0)} KB"

    result = {
        "title":          info.get("title", "Bilinməyən"),
        "thumbnail":      _best_thumbnail(info),
        "duration":       info.get("duration") or 0,
        "platform":       detect_platform(url),
        "uploader":       info.get("uploader") or info.get("channel") or "",
        "view_count":     info.get("view_count") or 0,
        "estimated_size": size_str,
    }

    _INFO_CACHE[url] = (now, result)
    return result

def _best_thumbnail(info: dict) -> str:
    thumb = info.get("thumbnail", "")
    if thumb:
        return thumb
    thumbs = info.get("thumbnails", [])
    if thumbs:
        best = max(thumbs, key=lambda t: t.get("preference", 0) or t.get("width", 0) or 0)
        return best.get("url", "")
    return ""

def _friendly_ydl_error(msg: str) -> str:
    low = msg.lower()
    if "ffmpeg" in low:
        return "Video/audio birləşdirmək üçün FFmpeg tələb olunur."
    if "video unavailable" in low or "this video is unavailable" in low or "does not exist" in low:
        return "Bu video mövcud deyil və ya silinib."
    if "private" in low:
        return "Bu video gizlidir (şəxsidir) və yüklənə bilmir."
    if "members only" in low or "requires a subscription" in low:
        return "Bu video yalnız abunəçilər/üzvlər üçündür."
    if "bot" in low or "confirm you're not a bot" in low or "not a bot" in low:
        return (
            "YouTube bot yoxlaması verdi. Təzə cookie lazımdır: incognito pəncərədə YouTube-a daxil olun, "
            "https://www.youtube.com/robots.txt açın, cookies.txt ixrac edin və saytdan yükləyin. "
            "Eyni sessiyanı brauzerdə açıq saxlamayın."
        )
    if "reload" in low:
        return "YouTube səhifəni yenidən yükləmə tələb etdi. Bir az sonra yenidən cəhd edin."
    if "login" in low or "sign in" in low:
        return "YouTube giriş tələb edir. Təzə YouTube cookies.txt faylı yükləyin."
    if "robots.txt" in low or "authcheck" in low:
        return "YouTube playlist/tab yoxlaması uğursuz oldu. Video linkini (watch?v=) göndərin, playlist yox."
    if "age" in low or "18" in low:
        return "Bu video yaş məhdudiyyətinə görə qorunur."
    if "copyright" in low or "removed" in low:
        return "Bu video müəllif hüquqları səbəbiylə silinib."
    if "empty media response" in low:
        return "Instagram bu videoya baxmaq üçün giriş tələb edir və ya video gizlidir."
    if "blocked from accessing" in low:
        return "Bu videoya giriş məhdudlaşdırılıb və ya silinib."
    if "network" in low or "connection" in low or "timeout" in low or "unable to download" in low:
        return "İnternet bağlantısında problem var. Bir az sonra yenidən cəhd edin."
    if "format" in low and ("not available" in low or "unsupported" in low):
        return "Bu video formatı dəstəklənmir və ya mövcud deyil."
    return "Link emal edilə bilmədi və ya yükləmə xətası baş verdi. Yenidən cəhd edin."

async def download_media(
    url: str,
    format_type: str = "mp4",
    no_watermark: bool = True,
) -> AsyncGenerator[dict, None]:
    uid = get_uid()
    url = canonicalize_url(url)
    platform = detect_platform(url)
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    yield {
        "status": "progress",
        "percent": 5,
        "speed": "",
        "eta": "",
        "phase": "Əlaqə qurulur...",
        "size_info": ""
    }

    outtmpl = str(DOWNLOAD_DIR / f"{uid}.%(ext)s")

    # Real-time progress hook
    def _progress_hook(d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100) if total > 0 else 0
            
            speed = d.get("speed") or 0
            speed_str = ""
            if speed > 1024 * 1024:
                speed_str = f"{round(speed / (1024 * 1024), 1)} MB/s"
            elif speed > 0:
                speed_str = f"{round(speed / 1024, 0)} KB/s"
                
            eta = d.get("eta")
            eta_str = ""
            if eta is not None and eta >= 0:
                m = int(eta) // 60
                s = int(eta) % 60
                eta_str = f"{m}:{s:02d}"

            size_str = ""
            if total > 0:
                down_mb = round(downloaded / (1024 * 1024), 1)
                tot_mb = round(total / (1024 * 1024), 1)
                size_str = f"{down_mb} / {tot_mb} MB"
            elif downloaded > 0:
                size_str = f"{round(downloaded / (1024 * 1024), 1)} MB"

            # Progress from 10% to 95%
            scaled_percent = 10.0 + (percent * 0.85)

            loop.call_soon_threadsafe(queue.put_nowait, {
                "status": "progress",
                "percent": round(scaled_percent, 1),
                "speed": speed_str,
                "eta": eta_str,
                "phase": "Yüklənir",
                "size_info": size_str,
            })
        elif status == "finished":
            loop.call_soon_threadsafe(queue.put_nowait, {
                "status": "progress",
                "percent": 96,
                "speed": "",
                "eta": "",
                "phase": "Çevrilir",
                "size_info": "Tamamlanır...",
            })

    def _postprocessor_hook(d):
        if d.get("status") == "started":
            loop.call_soon_threadsafe(queue.put_nowait, {
                "status": "progress",
                "percent": 98,
                "speed": "",
                "eta": "",
                "phase": "Çevrilir",
                "size_info": "Birləşdirilir...",
            })

    if format_type == "mp3":
        fmt = "bestaudio/best"
        postprocessors = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        merge_output_format = None
    else:
        # High quality MP4 - downloads best streams and merges without transcoding
        fmt = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best[ext=mp4]/"
            "best"
        )
        postprocessors = []
        merge_output_format = "mp4"

    custom_opts = {
        "format": fmt,
        "outtmpl": outtmpl,
        "progress_hooks": [_progress_hook],
    }
    if postprocessors:
        custom_opts["postprocessors"] = postprocessors
        custom_opts["postprocessor_hooks"] = [_postprocessor_hook]
    if merge_output_format:
        custom_opts["merge_output_format"] = merge_output_format

    if platform == "tiktok" and no_watermark:
        custom_opts["extractor_args"] = {
            "tiktok": {
                "api_hostname": "api16-normal-c-useast1a.tiktokv.com"
            }
        }

    def _run_download():
        last_error = None
        for attempt in _ydl_attempts():
            try:
                ydl_opts = build_ydl_opts(
                    custom_opts,
                    use_cookies=attempt["use_cookies"],
                    player_clients=attempt["clients"],
                )
                info = _ydl_extract(ydl_opts, url, download=True)
                    title = info.get("title") if info else "media"
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "type": "worker_done",
                        "title": title
                    })
                    return
            except Exception as e:
                last_error = e
                continue

        error_msg = _friendly_ydl_error(str(last_error))
        loop.call_soon_threadsafe(queue.put_nowait, {
            "type": "worker_error",
            "message": error_msg
        })

    worker_fut = loop.run_in_executor(None, _run_download)

    download_title = None
    download_error = None

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.8)
            if event.get("type") == "worker_done":
                download_title = event.get("title")
                break
            elif event.get("type") == "worker_error":
                download_error = event.get("message")
                break
            else:
                yield event
        except asyncio.TimeoutError:
            if worker_fut.done():
                break

    await worker_fut

    if download_error:
        yield {"status": "error", "message": download_error}
        return

    found = _find_output_file(uid)
    if not found or not found.exists():
        yield {"status": "error", "message": "Fayl yadda saxlanıla bilmədi. Zəhmət olmasa yenidən cəhd edin."}
        return

    file_size_bytes = found.stat().st_size
    size_mb = round(file_size_bytes / (1024 * 1024), 2)
    size_formatted = f"{size_mb} MB" if size_mb >= 1.0 else f"{round(file_size_bytes / 1024, 1)} KB"
    display_title = download_title or "media"
    clean_name = sanitize_filename(display_title)
    display_name = f"{clean_name}{found.suffix}"

    from urllib.parse import quote
    yield {
        "status": "done",
        "filename": found.name,
        "display_name": display_name,
        "size_formatted": size_formatted,
        "size_bytes": file_size_bytes,
        "format": format_type.upper(),
        "download_url": f"/api/file/{found.name}?title={quote(display_name)}",
        "percent": 100,
    }

def _find_output_file(uid: str) -> Path | None:
    for f in DOWNLOAD_DIR.iterdir():
        if f.stem == uid and f.is_file():
            return f
    return None

async def cleanup_file(filename: str, delay: int = 300):
    if "cookies.txt" in filename.lower():
        return
    await asyncio.sleep(delay)
    target = DOWNLOAD_DIR / filename
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass

def cleanup_stale_downloads(max_age_seconds: int = 1800):
    """Clean up leftover temp files on startup."""
    now = time.time()
    try:
        for f in DOWNLOAD_DIR.iterdir():
            if f.is_file() and not f.name.endswith(".txt"):
                if now - f.stat().st_mtime > max_age_seconds:
                    try:
                        f.unlink()
                    except OSError:
                        pass
    except Exception:
        pass
