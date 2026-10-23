from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

APP_NAME = "VD-solution-API"
APP_VERSION = "1.0.0"
API_KEY = os.getenv("API_KEY", "").strip()
REQUEST_TIMEOUT = int(os.getenv("YT_DLP_SOCKET_TIMEOUT", "20"))
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "500"))
MAX_CONCURRENT_EXTRACTIONS = max(1, int(os.getenv("MAX_CONCURRENT_EXTRACTIONS", "2")))
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]

_extract_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
_rate_state: dict[str, list[float]] = {}
RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE", "20")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _rate_state.clear()


app = FastAPI(
    title=APP_NAME,
    description="Android-friendly video metadata, format resolution, and download API.",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """If API_KEY is configured, require X-API-Key on API routes."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail={
            "code": "invalid_api_key",
            "message": "A valid X-API-Key header is required."
        })


def check_rate_limit(request: Request) -> None:
    """Small per-process guardrail; not a substitute for a distributed rate limiter."""
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [stamp for stamp in _rate_state.get(client, []) if now - stamp < 60]
    if len(recent) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail={
            "code": "rate_limit_exceeded",
            "message": "Too many requests. Wait a minute and try again."
        })
    recent.append(now)
    _rate_state[client] = recent


def validate_video_url(raw_url: str) -> str:
    value = raw_url.strip()
    if len(value) > 4096:
        raise HTTPException(status_code=400, detail={"code": "url_too_long", "message": "URL is too long."})
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_url",
            "message": "Provide a valid public http:// or https:// video URL."
        })
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost") or host.endswith(".local"):
        raise HTTPException(status_code=400, detail={"code": "private_host_not_allowed", "message": "Local URLs are not allowed."})
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if not ip.is_global:
            raise HTTPException(status_code=400, detail={"code": "private_host_not_allowed", "message": "Private or reserved IP addresses are not allowed."})
    except ValueError:
        # Resolve DNS to reject obvious private-network targets. DNS can change after this check;
        # the service should still be deployed behind platform-level egress controls if available.
        try:
            addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            for address in addresses:
                ip = ipaddress.ip_address(address[4][0])
                if not ip.is_global:
                    raise HTTPException(status_code=400, detail={"code": "private_host_not_allowed", "message": "URLs resolving to private or reserved IP addresses are not allowed."})
        except socket.gaierror:
            # Some supported media hosts may not resolve momentarily; yt-dlp will return a useful error.
            pass
    return value


def _base_ydl_options() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": REQUEST_TIMEOUT,
        "retries": 2,
        "fragment_retries": 2,
        "skip_unavailable_fragments": True,
        "format": "best[ext=mp4]/best",
        "cachedir": False,
    }


def _extract(url: str, *, download: bool = False, outtmpl: str | None = None) -> dict[str, Any]:
    options = _base_ydl_options()
    options["noplaylist"] = True
    options["ignoreerrors"] = False
    options["download"] = download
    if outtmpl:
        options["outtmpl"] = outtmpl
        options["max_filesize"] = MAX_DOWNLOAD_MB * 1024 * 1024
        options["overwrites"] = True
    with yt_dlp.YoutubeDL(options) as ydl:
        result = ydl.extract_info(url, download=download)
        if not isinstance(result, dict):
            raise RuntimeError("The extractor did not return video information.")
        return result


def _format_summary(fmt: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_id": fmt.get("format_id"),
        "ext": fmt.get("ext"),
        "format": fmt.get("format"),
        "resolution": fmt.get("resolution") or (
            f'{fmt.get("width")}x{fmt.get("height")}' if fmt.get("width") and fmt.get("height") else None
        ),
        "width": fmt.get("width"),
        "height": fmt.get("height"),
        "fps": fmt.get("fps"),
        "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
        "vcodec": fmt.get("vcodec"),
        "acodec": fmt.get("acodec"),
        "has_audio": fmt.get("acodec") not in (None, "none"),
        "has_video": fmt.get("vcodec") not in (None, "none"),
        "download_url": fmt.get("url"),
    }


def _metadata(info: dict[str, Any], include_formats: bool = False) -> dict[str, Any]:
    formats = info.get("formats") or []
    # Prefer a combined MP4 stream so Android can download/play without a merge step.
    candidates = [
        f for f in formats
        if f.get("url") and f.get("ext") == "mp4"
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    if not candidates:
        candidates = [f for f in formats if f.get("url") and f.get("vcodec") not in (None, "none")]
    best = max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), default={})
    payload = {
        "success": True,
        "title": info.get("title") or "Video",
        "id": info.get("id"),
        "webpage_url": info.get("webpage_url"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader") or info.get("channel"),
        "ext": best.get("ext") or info.get("ext"),
        "filesize": best.get("filesize") or best.get("filesize_approx"),
        "resolution": best.get("resolution") or (
            f'{best.get("width")}x{best.get("height")}' if best.get("width") and best.get("height") else None
        ),
        "download_url": best.get("url") or info.get("url"),
        "note": "Direct media URLs may expire and some formats require separate audio/video streams.",
    }
    if include_formats:
        payload["formats"] = [_format_summary(f) for f in formats if f.get("url")]
    return payload


def _public_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()
    if "private video" in message or "sign in" in message or "login" in message or "authentication" in message:
        code, text = "authentication_required", "This video requires sign-in or is private. This API does not bypass access controls."
    elif "unsupported url" in message or "no suitable extractor" in message:
        code, text = "unsupported_url", "This URL or platform is not supported by the installed yt-dlp version."
    elif "429" in message or "too many requests" in message or "rate limit" in message:
        code, text = "upstream_rate_limited", "The video platform is rate-limiting requests. Try again later."
    elif "geo" in message and ("restrict" in message or "blocked" in message):
        code, text = "geo_restricted", "This video is not available from the server's region."
    elif "age" in message and ("restrict" in message or "confirm" in message):
        code, text = "age_restricted", "This video requires age verification."
    elif "max-filesize" in message or "file is larger" in message:
        code, text = "file_too_large", f"Video exceeds the configured {MAX_DOWNLOAD_MB} MB download limit."
    else:
        code, text = "extraction_failed", "Could not process this video. It may be unavailable, restricted, or the platform may have changed."
    return HTTPException(status_code=422, detail={"code": code, "message": text})


@app.get("/")
async def home():
    return {"status": "online", "service": APP_NAME, "version": APP_VERSION, "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": APP_NAME, "version": APP_VERSION}


@app.get("/api/resolve", dependencies=[Depends(require_api_key), Depends(check_rate_limit)])
async def resolve_media(url: str = Query(..., min_length=8, max_length=4096, description="Public video page URL")):
    safe_url = validate_video_url(url)
    try:
        async with _extract_semaphore:
            info = await run_in_threadpool(_extract, safe_url)
        return _metadata(info)
    except HTTPException:
        raise
    except Exception as exc:
        raise _public_error(exc) from None


@app.get("/api/formats", dependencies=[Depends(require_api_key), Depends(check_rate_limit)])
async def list_formats(url: str = Query(..., min_length=8, max_length=4096, description="Public video page URL")):
    safe_url = validate_video_url(url)
    try:
        async with _extract_semaphore:
            info = await run_in_threadpool(_extract, safe_url)
        return _metadata(info, include_formats=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise _public_error(exc) from None


@app.get("/api/download", dependencies=[Depends(require_api_key), Depends(check_rate_limit)])
async def download_video(
    url: str = Query(..., min_length=8, max_length=4096, description="Public video page URL"),
    request: Request = None,
):
    """Download a single media file through the API; server storage is temporary."""
    safe_url = validate_video_url(url)
    tmpdir = tempfile.mkdtemp(prefix="vd_solution_")
    outtmpl = str(Path(tmpdir) / "%(title).150B-%(id)s.%(ext)s")
    try:
        async with _extract_semaphore:
            info = await run_in_threadpool(_extract, safe_url, download=True, outtmpl=outtmpl)
        files = [p for p in Path(tmpdir).glob("*") if p.is_file() and p.name != ".DS_Store"]
        if not files:
            raise RuntimeError("Download finished without producing a file.")
        file_path = max(files, key=lambda p: p.stat().st_size)
        if file_path.stat().st_size > MAX_DOWNLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail={"code": "file_too_large", "message": f"Download exceeds {MAX_DOWNLOAD_MB} MB."})

        def cleanup() -> None:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

        return FileResponse(
            path=file_path,
            media_type="application/octet-stream",
            filename=file_path.name,
            background=BackgroundTask(cleanup),
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as exc:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise _public_error(exc) from None
