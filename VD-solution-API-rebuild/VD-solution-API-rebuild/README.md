# VD-solution-API (VidoSwift backend)

## Files
- `app/main.py`: FastAPI routes and yt-dlp integration
- `requirements.txt`: Python dependencies including yt-dlp's default extra (EJS scripts)
- `Dockerfile`: installs Deno and starts the API
- `render.yaml`: optional Render Blueprint configuration

## Deploy on Render
This version uses Docker so that Deno is available to yt-dlp. If you create a new Render service:
1. Push these files to your GitHub repository.
2. In Render, create a Web Service connected to the repository.
3. Choose **Docker** runtime (not Python native runtime).
4. Keep health check path `/health`.
5. Deploy. The service command is provided by the Dockerfile.

If replacing the existing Render service, change its runtime to Docker only if Render allows it for that service; otherwise create a new Docker web service from this repository, test it, and then update the app's API base URL.

## Endpoints
- `GET /health`
- `GET /api/resolve?url=https://...`
- `GET /api/formats?url=https://...`
- `GET /api/download?url=https://...`
- `GET /api/download?url=https://...&format_id=FORMAT_ID`

`video_url` and `videoUrl` are also accepted as URL parameter aliases. `formatId` and `format` are accepted aliases for `format_id`.

## Environment variables
- `MAX_DOWNLOAD_MB` (default 500): download-size limit
- `YTDLP_SOCKET_TIMEOUT` (default 20): network timeout in seconds
- `YTDLP_PROXY` (optional): proxy URL, only if you legitimately operate one
- `CORS_ORIGINS` (default `*`): comma-separated origins

## Important limitations
- YouTube can change its player and challenge system; no third-party extractor can guarantee every video works at all times.
- Current yt-dlp YouTube support uses a JavaScript runtime and EJS challenge scripts. This project uses Deno and installs `yt-dlp[default]`.
- Render Free has limited CPU/RAM and ephemeral storage. Large/long downloads may fail or exceed service limits.
- This API does not bypass sign-in, age checks, private videos, DRM, or other access controls. Use it only for content you are allowed to download.
- The `format_id` value must be a format id returned by `/api/formats`. Some separate audio/video formats require FFmpeg to merge; this Docker image does not install FFmpeg, so prefer progressive formats that already contain audio and video.
