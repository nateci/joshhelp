# ID Verification API

A free, self-hosted ID + selfie verification service modeled on Stripe Identity. The user photographs the front and back of their driver's license, then takes a short head-turn selfie. Your backend gets back a result with each check reported separately.

**How it works**
- **Document data** comes from the **PDF417 barcode on the back** of US and Canadian IDs (the AAMVA standard). This is more reliable than OCR on the front.
- **Face match** compares the photo on the front of the ID with the selfie, using OpenCV's YuNet and SFace models. Cosine similarity of 0.363 or higher counts as a match.
- **Liveness** works through a head-turn challenge. The user looks straight, turns one way, then turns the other. A real head changes where the nose sits relative to the eyes. A printed photo or a phone screen held up and tilted barely changes it, so it fails.
- Images are processed in memory and never stored.

## How it fits into your app

This works like Stripe Identity. The browser uploads photos directly to this service. **Only your backend ever sees the verdict**, so a tampered client can't fake "verified".

```
 Browser (Next.js page)          Your backend (Next.js API routes)       This service
 ──────────────────────          ─────────────────────────────────       ────────────
 click "Verify" ───────────────▶ POST /api/verify/start
                                    └─ POST /sessions  (X-API-Key) ────▶ creates session
                ◀── sessionId + clientToken ───────────────────────────┘
 Step 1: front of ID ──── POST /sessions/{id}/id-front (Bearer token) ─▶ face found?  → ok / retake
 Step 2: back of ID  ──── POST /sessions/{id}/id-back  (Bearer token) ─▶ barcode read? → ok / retake
 Step 3: 3 selfie frames ─ POST /sessions/{id}/selfie   (Bearer token) ─▶ liveness?     → ok / retake
 done ─────────────────────────▶ POST /api/verify/result
                                    └─ GET /sessions/{id} (X-API-Key) ──▶ full result
                                    └─ save verified=true on the user
```

You can copy the Next.js side straight from [examples/nextjs/](examples/nextjs/):
- [app/api/verify/start/route.ts](examples/nextjs/app/api/verify/start/route.ts) creates the session on the server.
- [app/api/verify/result/route.ts](examples/nextjs/app/api/verify/result/route.ts) fetches the verdict and saves it.
- [components/IdVerification.tsx](examples/nextjs/components/IdVerification.tsx) is the 3-step UI with the camera and head-turn prompts. Usage: `<IdVerification onDone={(ok) => ...} />`.
- [components/BarcodeScanner.tsx](examples/nextjs/components/BarcodeScanner.tsx) scans the barcode on the back of the ID **live on the phone** with `zxing-wasm` (`npm i zxing-wasm`). It only captures once the barcode decodes, which is how Stripe avoids blurry uploads. The server still decodes the image itself, so the client is never trusted. If scanning takes over 20 seconds, it offers a plain photo upload instead.

Set these environment variables in the Next.js app (on Vercel): `VERIFY_API_URL` and `VERIFY_API_KEY`.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload
```
The face models (~39 MB) download into `models/` on first start. Interactive docs are at http://localhost:8000/docs.

| Env var | Purpose |
|---|---|
| `VERIFY_API_KEY` | Secret that server-to-server calls send as the `X-API-Key` header. **Set this in production.** |
| `CORS_ORIGINS` | Comma-separated origins allowed to upload from the browser, e.g. `https://dibs-black-seven.vercel.app`. Defaults to `*`. |

## Deploy for free

Vercel's serverless functions aren't a good fit for OpenCV. Deploy the included `Dockerfile` to a free container host instead:
- **Render** (free web service): create a new Web Service from the repo, choose the Docker runtime, and set the env vars. Free instances sleep when idle, so the first request after a sleep takes about 30–60 seconds.
- **Fly.io**, **Railway**, and **Hugging Face Spaces** (Docker) also work.

Sessions are kept in memory. Run one instance, and expect in-progress sessions to be lost on restart (they expire after 30 minutes anyway).

## API reference

### Session flow (recommended)
| Call | Auth | Body | Returns |
|---|---|---|---|
| `POST /sessions` | `X-API-Key` | JSON `{min_age?, expected_name?, expected_dob?}` | `{session_id, client_token, expires_at}` |
| `POST /sessions/{id}/id-front` | `Authorization: Bearer <client_token>` | multipart `image` | `{ok, issues}` |
| `POST /sessions/{id}/id-back` | Bearer | multipart `image` | `{ok, issues}` |
| `POST /sessions/{id}/selfie` | Bearer | multipart `frames` ×3: straight, turned one way, turned the other | `{ok, issues}` |
| `GET /sessions/{id}` | `X-API-Key` | | `{complete, steps, result}` |

You can call a step again to retake it; the new upload replaces the old one. Step responses never include the verdict or the extracted ID data.

### One-shot (server-to-server, no liveness)
`POST /verify` (multipart `id_front`, `id_back`, `selfie`) or `POST /verify/json` (the same fields as base64). Both accept `min_age`, `expected_name` and `expected_dob`.

### Result
```json
{
  "verified": true,
  "checks": {
    "document_readable": true,
    "not_expired": true,
    "age_ok": true,
    "face_on_id": true,
    "face_in_selfie": true,
    "face_match": true,
    "face_similarity": 0.82,
    "liveness": true,
    "name_match": null,
    "dob_match": null
  },
  "extracted": {
    "name": "JANE Q SAMPLE", "first_name": "JANE", "last_name": "SAMPLE",
    "date_of_birth": "1990-01-07", "expiration": "2029-01-07",
    "document_number": "T64235789", "state": "VA", "country": "USA", "sex": "F", "age": 35
  },
  "issues": []
}
```
`verified` is `true` only when every check that applies passes. A check is `null` when it wasn't evaluated (for example, `name_match` when you didn't send `expected_name`). `issues` explains any failure in plain English.

## Limitations (compared with Stripe)
- The liveness check stops printed photos and photos on a screen. It does **not** stop a replayed video of the person turning their head, masks, or deepfakes. Stripe uses certified commercial liveness for those.
- Only IDs with an AAMVA barcode are supported (US and Canadian licenses and state IDs). Passports would need MRZ parsing.
- The service doesn't detect forged or tampered documents.
- The thresholds (`MATCH_THRESHOLD` in `app/face.py`, `MIN_TURN` in `app/liveness.py`) haven't been tuned on real phone photos yet. Test with a few real IDs and adjust.

## Tests
```bash
pytest
```
