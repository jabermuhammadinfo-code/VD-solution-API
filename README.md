# VD-solution-API (VidoSwift Backend)

FastAPI ও yt-dlp ব্যবহার করে তৈরি VidoSwift ভিডিও ডাউনলোডার API।

## Project Files

- `app/main.py` — মূল API কোড ও ভিডিও প্রসেসিং।
- `main.py` — compatibility import।
- `requirements.txt` — Python dependencies।
- `Dockerfile` — Render-এ Docker দিয়ে চালানোর configuration।
- `render.yaml` — Render service configuration।
- `tests/test_api.py` — প্রাথমিক API tests।

## Deploy on Render

1. এই প্রজেক্টের সব ফাইল GitHub repository-তে আপলোড করো।
2. Render Dashboard-এ গিয়ে GitHub repository-এর সঙ্গে সংযুক্ত একটি Web Service তৈরি করো।
3. Runtime হিসেবে **Docker** নির্বাচন করো।
4. Health Check Path হিসেবে `/health` ব্যবহার করো।
5. Deploy শুরু করো এবং Build Logs ও Deploy Logs পরীক্ষা করো।

Dockerfile-এ API চালানোর command দেওয়া আছে। Render-এর পরিবেশ থেকে `PORT` স্বয়ংক্রিয়ভাবে নেওয়া হবে।

## API Endpoints

### 1. Health Check

`GET /health`

API সচল আছে কি না পরীক্ষা করে।

### 2. Video Information

`GET /api/resolve?url=VIDEO_URL`

ভিডিওর title, thumbnail, duration এবং অন্যান্য তথ্য ফেরত দেয়।

### 3. Available Formats

`GET /api/formats?url=VIDEO_URL`

ভিডিওর উপলভ্য format, resolution, audio ও video stream-এর তথ্য ফেরত দেয়।

### 4. Download Video

`GET /api/download?url=VIDEO_URL`

ভিডিও ডাউনলোডের response ফেরত দেয়।

নির্দিষ্ট format ব্যবহার করতে:

`GET /api/download?url=VIDEO_URL&format_id=FORMAT_ID`

`FORMAT_ID` অবশ্যই `/api/formats` থেকে পাওয়া একটি format ID হতে হবে।

## Environment Variables

- `MAX_DOWNLOAD_MB` — সর্বোচ্চ ডাউনলোড সাইজ; ডিফল্ট 500 MB।
- `YTDLP_SOCKET_TIMEOUT` — network timeout; ডিফল্ট 20 সেকেন্ড।
- `YTDLP_PROXY` — প্রয়োজন হলে বৈধ proxy URL।
- `CORS_ORIGINS` — অনুমোদিত origin-এর তালিকা; ডিফল্ট `*`।

## YouTube Extraction

বর্তমান yt-dlp সংস্করণে YouTube-এর কিছু extraction প্রক্রিয়ার জন্য JavaScript runtime ও EJS challenge scripts প্রয়োজন হতে পারে। এই প্রজেক্টে Deno runtime এবং `yt-dlp[default]` ব্যবহার করা হয়েছে।

তবুও YouTube-এর পরিবর্তন, rate limit, sign-in requirement বা ভিডিওর access restriction-এর কারণে কোনো কোনো URL ব্যর্থ হতে পারে।

## Important Limitations

- Render Free-এ CPU, RAM ও storage সীমাবদ্ধতা রয়েছে।
- Render-এর স্থানীয় ফাইল স্থায়ীভাবে সংরক্ষিত থাকে না।
- বড় বা দীর্ঘ ভিডিও ডাউনলোড ব্যর্থ হতে পারে।
- কিছু পৃথক audio/video format একত্র করতে FFmpeg প্রয়োজন হয়। এই Dockerfile-এ FFmpeg ইনস্টল করা নেই।
- Private, restricted বা DRM-protected কনটেন্টের access restriction এড়িয়ে যাওয়ার ব্যবস্থা এই API করে না।
- কেবল নিজের মালিকানাধীন অথবা ডাউনলোড করার অনুমতি রয়েছে—এমন কনটেন্ট ব্যবহার করো।

## Testing

Deploy-এর পরে প্রথমে পরীক্ষা করো:

`https://YOUR-RENDER-DOMAIN/health`

এরপর `/api/resolve` এবং `/api/formats` পরীক্ষা করো।

`YOUR-RENDER-DOMAIN`-এর জায়গায় তোমার প্রকৃত Render service domain বসাতে হবে।
