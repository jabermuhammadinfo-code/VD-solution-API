# VD-solution-API

A deployable FastAPI backend for an Android video app. Uses `yt-dlp` to resolve metadata/formats and optionally download a media file through the API.

## Important limitations

- No API can guarantee every YouTube/video URL will always work. Platforms change their systems and may require login, age verification, or regional access.
- Use this only for content you own or have permission to download, and follow each platform's terms.
- Render Free services may sleep, have limited CPU/RAM, ephemeral storage, and request/runtime limits. Large downloads may fail; this is not a dedicated high-bandwidth download server.
- Direct `download_url` values are often temporary and may expire. They may point to separate video/audio streams depending on the source.
- `/api/download` downloads a single file to temporary server storage. The configured default limit is 500 MB.

## Endpoints

- `GET /` — service status
- `GET /health` — health check
- `GET /docs` — interactive API docs
- `GET /api/resolve?url=VIDEO_URL` — metadata and best available direct media URL
- `GET /api/formats?url=VIDEO_URL` — metadata and available formats
- `GET /api/download?url=VIDEO_URL` — downloads the selected media file through the API

### Example

```bash
curl "https://YOUR-SERVICE.onrender.com/api/resolve?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DVIDEO_ID"
```

If you set an `API_KEY` environment variable in Render, send it on API requests using the `X-API-Key` header. If no key is set, the API routes are public. Do not put a secret API key inside a public Android APK; APK keys can be extracted. For a public app, use server-side abuse controls and rotate exposed keys.

## Deploy on Render

1. Upload the contents of this ZIP to the root of your GitHub repository named `VD-solution-API` (do not upload the ZIP file itself).
2. In Render, create a Web Service from that repository.
3. Render should detect `render.yaml`. Confirm the service name `vd-solution-api`, runtime Python, build command `pip install -r requirements.txt`, and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Deploy. Once healthy, open `/health`, then `/docs`.
5. If the build fails, use Render's deploy logs; do not assume the service is live until `/health` returns `{"status":"ok",...}`.

## Android integration

Use the deployed base URL, for example `https://YOUR-SERVICE.onrender.com`. Call `/api/resolve` with the `url` query parameter URL-encoded. Check `success` and `download_url` before starting a download. Treat `detail.code` and `detail.message` as user-facing diagnostics. Use HTTPS.

## Local development

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests

```bash
pytest -q
```
