import base64
import binascii
import os
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import face
from .verify import BadImage, VerifyResult, verify

API_KEY = os.getenv("VERIFY_API_KEY")  # if set, callers must send X-API-Key
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "*").split(",") if o]

@asynccontextmanager
async def lifespan(_: FastAPI):
    face.ensure_models()  # downloads the ONNX models on first run
    yield


app = FastAPI(title="ID Verification API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key")


async def _run(**kwargs) -> VerifyResult:
    try:
        return await run_in_threadpool(verify, **kwargs)
    except BadImage as e:
        raise HTTPException(400, str(e))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/verify", response_model=VerifyResult, dependencies=[Depends(require_key)])
async def verify_multipart(
    id_front: UploadFile = File(..., description="Front of the ID (photo side)"),
    id_back: UploadFile = File(..., description="Back of the ID (PDF417 barcode)"),
    selfie: UploadFile = File(..., description="Selfie captured by the app"),
    min_age: int = Form(18),
    expected_name: str | None = Form(None),
    expected_dob: date | None = Form(None),
):
    return await _run(
        id_front=await id_front.read(),
        id_back=await id_back.read(),
        selfie=await selfie.read(),
        min_age=min_age,
        expected_name=expected_name,
        expected_dob=expected_dob,
    )


class VerifyJSON(BaseModel):
    id_front: str  # base64 (plain or data: URL)
    id_back: str
    selfie: str
    min_age: int = 18
    expected_name: str | None = None
    expected_dob: date | None = None


def _b64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, f"{field} is not valid base64")


@app.post("/verify/json", response_model=VerifyResult, dependencies=[Depends(require_key)])
async def verify_json(body: VerifyJSON):
    return await _run(
        id_front=_b64(body.id_front, "id_front"),
        id_back=_b64(body.id_back, "id_back"),
        selfie=_b64(body.selfie, "selfie"),
        min_age=body.min_age,
        expected_name=body.expected_name,
        expected_dob=body.expected_dob,
    )
