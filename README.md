# ID Verification API

A small FastAPI service that checks a government ID against a selfie, similar to Stripe Identity's document + selfie check. Your app owns the camera and face-scan UI, then sends three images. The API reports each check separately, so your app can decide how to handle edge cases, such as a good face match on an expired ID.

**How it works**
- **Document data** comes from the **PDF417 barcode on the back** of US and Canadian IDs (AAMVA standard). This is more reliable than OCR on the front.
- **Face match** uses OpenCV's YuNet (detection) and SFace (recognition) models. The service compares the photo on the front of the ID with the selfie by cosine similarity, and counts a score of 0.363 or higher as a match.
- Images are processed in memory and never stored.

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

On first start, the service downloads the face models (~39 MB) into `models/`. Interactive docs are at http://localhost:8000/docs.

Optional environment variables:
| Variable | Purpose |
|---|---|
| `VERIFY_API_KEY` | If set, every request must send the header `X-API-Key: <value>` |
| `CORS_ORIGINS` | Comma-separated allowed origins (default `*`) |

## API

### `POST /verify` (multipart/form-data)
| Field | Required | Notes |
|---|---|---|
| `id_front` | yes | Photo side of the ID |
| `id_back` | yes | Barcode side |
| `selfie` | yes | Captured by your app |
| `min_age` | no | Default `18` |
| `expected_name` | no | What the user typed; adds the `name_match` check |
| `expected_dob` | no | `YYYY-MM-DD`; adds the `dob_match` check |

### `POST /verify/json`
The same fields as JSON. Send the images as base64 strings; plain base64 and `data:` URLs both work.

### Response
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
    "name_match": null,
    "dob_match": null
  },
  "extracted": {
    "name": "JANE Q SAMPLE",
    "first_name": "JANE",
    "last_name": "SAMPLE",
    "date_of_birth": "1990-01-07",
    "expiration": "2029-01-07",
    "document_number": "T64235789",
    "state": "VA",
    "country": "USA",
    "sex": "F",
    "age": 35
  },
  "issues": []
}
```
`verified` is `true` only when the document is readable, not expired, the age passes, the faces match, and any `expected_*` fields you sent also match. A check is `null` when the service couldn't evaluate it. For example, `face_match` is `null` when no face was found. `issues` lists the reasons in plain English.

Bad or unreadable images return `400`.

## Calling it from the app

The app renders its own face-scan screen, captures a frame, and posts it with the ID photos. See [examples/client.html](examples/client.html) for a minimal browser version. The core of it:

```js
const fd = new FormData();
fd.append("id_front", frontFile);
fd.append("id_back", backFile);
fd.append("selfie", selfieBlob, "selfie.jpg");
const result = await fetch(`${API}/verify`, { method: "POST", body: fd }).then(r => r.json());
if (result.verified) { /* ... */ }
```

## Limitations
- **No liveness detection.** Someone could hold up a photo of a face. Real anti-spoofing would be the next step, for example a blink or head-turn challenge across several frames.
- Only IDs with an AAMVA barcode are supported (US and Canadian driver's licenses and state IDs). Passports would need MRZ parsing.
- The service doesn't detect tampered or forged documents.

## Tests
```bash
pytest
```
