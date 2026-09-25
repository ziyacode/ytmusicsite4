import asyncio
import json
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from downloader import (
    DOWNLOAD_DIR,
    cleanup_file,
    cleanup_stale_downloads,
    download_media,
    fetch_info,
    sanitize_filename,
    _friendly_ydl_error,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_stale_downloads()
    yield

app = FastAPI(
    title="Media Downloader API",
    description="YouTube, TikTok, Instagram və digər platformalardan media yükləmə API-si",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"
    no_watermark: bool = True

def normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        return f"https://{u}"
    return u

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "Server işləyir ✓"}

@app.post("/api/info")
async def get_info(body: InfoRequest):
    url = normalize_url(body.url)
    if not url:
        raise HTTPException(status_code=400, detail="URL boş ola bilməz.")
    try:
        info = await fetch_info(url)
        return info
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_friendly_ydl_error(str(e)))

@app.post("/api/download")
async def start_download(body: DownloadRequest):
    url = normalize_url(body.url)
    if not url:
        raise HTTPException(status_code=400, detail="URL boş ola bilməz.")

    if body.format not in ("mp4", "mp3"):
        raise HTTPException(status_code=400, detail="Format yalnız 'mp4' və ya 'mp3' ola bilər.")

    async def event_generator():
        try:
            async for event in download_media(
                url=url,
                format_type=body.format,
                no_watermark=body.no_watermark,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["status"] == "done":
                    asyncio.create_task(cleanup_file(event["filename"]))
                    break
                elif event["status"] == "error":
                    break
        except Exception as e:
            error_msg = _friendly_ydl_error(str(e))
            yield f"data: {json.dumps({'status': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

@app.get("/api/file/{filename}")
async def serve_file(filename: str, title: str | None = None):
    import re
    if not re.match(r"^[a-f0-9]+\.(mp4|mp3|webm|m4a|mkv|ogg|wav)$", filename.lower()):
        raise HTTPException(status_code=400, detail="Yanlış fayl adı.")

    file_path = DOWNLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fayl tapılmadı və ya artıq silinib.")

    ext = file_path.suffix.lower()
    if title:
        clean_name = sanitize_filename(title)
        if not clean_name.lower().endswith(ext):
            display_name = f"{clean_name}{ext}"
        else:
            display_name = clean_name
    else:
        display_name = filename

    media_type = "audio/mpeg" if ext == ".mp3" else "video/mp4"
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=display_name,
    )

@app.get("/")
async def root():
    return RedirectResponse(url="/app/index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False if os.environ.get("PORT") else True,
        log_level="info",
    )
