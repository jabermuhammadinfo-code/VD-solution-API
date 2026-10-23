"""
VD-solution-API
FastAPI + yt-dlp backend for VidoSwift.

Important:
- Only download content you own or have permission to download.
- YouTube extraction can still be affected by upstream changes, rate limits, or access restrictions.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

APP_NAME = "VD-solution-API"
APP_VERSION = "2.0.0"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(APP_NAME)

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Video metadata, formats, and download API for VidoSwift.",
)

# For a public API, set CORS_ORIGINS to a comma-separated allow-list in Render.
# "*" is convenient for a prototype, but restrict it for production.
cors_origins = [
    item.strip()
    for item in os.getenv("CORS_ORIGINS", "*").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

MAX_URL_LENGTH = 4096
DEFAULT_TIMEOUT = int(os.getenv("YTDLP_SOCKET_TIMEOUT", "20"))
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "500"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise HTTPException(status_code=400, detail="A valid video URL is required.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://.")
    # Prevent localhost/private-network URLs being used as a generic URL fetch proxy.
    host = (parsed.hostname or "").lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="This host is not allowed.")
    return url


def _ydl_base_options() -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": DEFAULT_TIMEOUT,
        "retries": 2,
        "fragment_retries": 2,
        "http_headers": {"User-Agent": USER_AGENT},
        # yt-dlp's Python package needs its matching EJS dependency.
        # Runtime is supplied by the Render Docker image (Deno).
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:npm"],
    }
    proxy = os.getenv("YTDLP_PROXY", "").strip()
    if proxy:
        options["proxy"] = proxy
    return options


def _extract_info(url: str, *, download: bool = False, extra: dict | None = None) -> dict:
    options = _ydl_base_options()
    options["skip_download"] = not download
    if extra:
        options.update(extra)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=download)
            if not isinstance(info, dict):
                raise RuntimeError("Extractor did not return video information.")
            return info
    except HTTPException:
        raise
    except Exception as exc:
        message = str(exc)
        logger.warning("yt-dlp extraction failed: %s", message[:500])
        low = message.lower()
        if any(term in low for term in ("private video", "video unavailable", "not available", "members-only")):
            detail = "এই ভিডিওটি পাওয়া যাচ্ছে না, ব্যক্তিগত, অথবা অ্যাক্সেস সীমাবদ্ধ।"
        elif any(term in low for term in ("sign in", "login", "age-restricted", "confirm you’re not a bot", "bot")):
            detail = "প্ল্যাটফর্মটি এই ভিডিওর জন্য সাইন-ইন বা অতিরিক্ত যাচাই চাইছে।"
        elif "failed to extract any player response" in low or "player response" in low:
            detail = (
                "YouTube-এর player response বের করা যায়নি। yt-dlp/EJS/Deno আপডেট আছে কি না "
                "Render Build Logs দেখুন; YouTube-এর পরিবর্তন বা সাময়িক সীমাবদ্ধতাও কারণ হতে পারে।"
            )
        elif any(term in low for term in ("timed out", "timeout", "temporary failure", "connection")):
            detail = "ভিডিও সার্ভারে সংযোগ করা যায়নি। কিছুক্ষণ পর আবার চেষ্টা করুন।"
        else:
            detail = "ভিডিও প্রসেস করা যায়নি। URL যাচাই করে আবার চেষ্টা করুন।"
        raise HTTPException(status_code=422, detail=detail) from exc


def _format_bytes(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _format_row(fmt: dict) -> dict:
    return {
        "format_id": str(fmt.get("format_id", "")),
        "ext": fmt.get("ext"),
        "format_note": fmt.get("format_note"),
        "resolution": fmt.get("resolution") or (
            f"{fmt.get('height')}p" if fmt.get("height") else "audio only" if fmt.get("vcodec") == "none" else None
        ),
        "width": fmt.get("width"),
        "height": fmt.get("height"),
        "fps": fmt.get("fps"),
        "filesize": _format_bytes(fmt.get("filesize") or fmt.get("filesize_approx")),
        "vcodec": fmt.get("vcodec"),
        "acodec": fmt.get("acodec"),
        "has_video": fmt.get("vcodec") not in (None, "none"),
        "has_audio": fmt.get("acodec") not in (None, "none"),
        "is_audio_only": fmt.get("vcodec") == "none",
    }


def _public_info(info: dict) -> dict:
    formats = [_format_row(f) for f in info.get("formats", []) if isinstance(f, dict)]
    return {
        "success": True,
        "id": info.get("id"),
        "title": info.get("title") or "Untitled video",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "webpage_url": info.get("webpage_url"),
        "extractor": info.get("extractor"),
        "ext": info.get("ext"),
        "filesize": _format_bytes(info.get("filesize") or info.get("filesize_approx")),
        "formats": formats,
    }


def _clean_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name[:140] or "video")


@app.get("/")
async def root():
    return {
        "success": True,
        "name": APP_NAME,
        "version": APP_VERSION,
        "message": "VidoSwift API is running.",
        "endpoints": ["/health", "/api/resolve", "/api/formats", "/api/download"],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": APP_NAME, "version": APP_VERSION}


@app.get("/api/resolve")
async def resolve(
    url: str | None = Query(default=None),
    video_url: str | None = Query(default=None),
    videoUrl: str | None = Query(default=None),
):
    target = _validate_url(url or video_url or videoUrl or "")
    info = await run_in_threadpool(_extract_info, target)
    return _public_info(info)


@app.get("/api/formats")
async def formats(
    url: str | None = Query(default=None),
    video_url: str | None = Query(default=None),
    videoUrl: str | None = Query(default=None),
):
    target = _validate_url(url or video_url or videoUrl or "")
    info = await run_in_threadpool(_extract_info, target)
    data = _public_info(info)
    return {
        "success": True,
        "id": data["id"],
        "title": data["title"],
        "thumbnail": data["thumbnail"],
        "formats": data["formats"],
    }


def _download_to_temp(url: str, format_id: str | None) -> tuple[str, str, str]:
    temp_dir = tempfile.mkdtemp(prefix="vdsolution_")
    output_template = str(Path(temp_dir) / "%(title).140B-%(id)s.%(ext)s")
    opts = _ydl_base_options()
    opts.update({
        "outtmpl": output_template,
        "noplaylist": True,
        "overwrites": True,
        "continuedl": False,
        "max_filesize": MAX_DOWNLOAD_MB * 1024 * 1024,
        # Prefer a single file with both streams: Render may not have ffmpeg.
        "format": format_id or "best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best",
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            requested = Path(ydl.prepare_filename(info))
        # If yt-dlp merged formats, it may have changed the extension to mp4/mkv/webm.
        candidates = list(Path(temp_dir).glob("*"))
        candidates = [p for p in candidates if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise RuntimeError("Download completed but no output file was found.")
        file_path = max(candidates, key=lambda p: p.stat().st_size)
        if file_path.stat().st_size == 0:
            raise RuntimeError("Downloaded file is empty.")
        filename = _clean_filename(info.get("title") or file_path.stem) + file_path.suffix
        return str(file_path), filename, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


@app.get("/api/download")
async def download(
    url: str | None = Query(default=None),
    video_url: str | None = Query(default=None),
    videoUrl: str | None = Query(default=None),
    format_id: str | None = Query(default=None),
    formatId: str | None = Query(default=None),
    format: str | None = Query(default=None),
):
    target = _validate_url(url or video_url or videoUrl or "")
    selected_format = format_id or formatId or format
    if selected_format and not re.fullmatch(r"[A-Za-z0-9._+-]{1,80}", selected_format):
        raise HTTPException(status_code=400, detail="Invalid format_id.")
    try:
        file_path, filename, temp_dir = await run_in_threadpool(
            _download_to_temp, target, selected_format
        )
    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        logger.warning("Download failed: %s", str(exc)[:500])
        if "max-filesize" in msg or "larger than" in msg:
            raise HTTPException(
                status_code=413,
                detail=f"ভিডিওটি সার্ভারের {MAX_DOWNLOAD_MB} MB সীমার চেয়ে বড়।",
            ) from exc
        if "ffmpeg" in msg and selected_format:
            raise HTTPException(
                status_code=422,
                detail="এই ফরম্যাটে ভিডিও ও অডিও একত্র করতে FFmpeg দরকার। Best MP4 ফরম্যাট বেছে চেষ্টা করুন।",
            ) from exc
        raise HTTPException(status_code=422, detail="ডাউনলোড সম্পন্ন করা যায়নি। অন্য ফরম্যাট বেছে আবার চেষ্টা করুন।") from exc

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
        background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request, exc: HTTPException):
    # Keep a consistent JSON envelope for mobile clients.
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "detail": exc.detail},
        headers=exc.headers,
    )
