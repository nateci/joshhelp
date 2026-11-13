"""Stripe-Identity-style session flow.

1. Your backend:  POST /sessions               (API key)       -> session_id + client_token
2. Phone/browser: POST /sessions/{id}/id-front (client token)  -> instant ok / retake
3. Phone/browser: POST /sessions/{id}/id-back  (client token)  -> instant ok / retake
4. Phone/browser: POST /sessions/{id}/selfie   (client token)  -> 3 head-turn frames, instant ok / retake
5. Your backend:  GET  /sessions/{id}          (API key)       -> final result

The phone never sees the verdict or the extracted ID data; only your backend does, so a
modified client can't fake "verified". Images aren't stored, only face embeddings and the
parsed barcode, and sessions expire after SESSION_TTL seconds.

Sessions live in memory, so run a single server process (fine for a small app)."""
import secrets
import time
from dataclasses import dataclass, field
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from . import face, liveness
from .verify import BadImage, Extracted, VerifyResult, build_result, decode_image, read_document

SESSION_TTL = 30 * 60


@dataclass
class Session:
    id: str
    client_token: str
    min_age: int
    expected_name: str | None
    expected_dob: date | None
    created: float = field(default_factory=time.time)
    doc: Extracted | None = None
    doc_source: str | None = None
    id_face: face.Face | None = None
    selfie_face: face.Face | None = None
    liveness_issues: list[str] | None = None
    steps: dict[str, bool] = field(default_factory=lambda: {"id_front": False, "id_back": False, "selfie": False})


SESSIONS: dict[str, Session] = {}


class CreateSession(BaseModel):
    min_age: int = 18
    expected_name: str | None = None
    expected_dob: date | None = None


class SessionCreated(BaseModel):
    session_id: str
    client_token: str
    expires_at: int


class StepResult(BaseModel):
    ok: bool
    issues: list[str]


class SessionStatus(BaseModel):
    session_id: str
    complete: bool
    steps: dict[str, bool]
    result: VerifyResult | None


def make_router(require_key) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])

    def _get(session_id: str) -> Session:
        now = time.time()
        for sid in [k for k, s in SESSIONS.items() if now - s.created > SESSION_TTL]:
            del SESSIONS[sid]
        s = SESSIONS.get(session_id)
        if not s:
            raise HTTPException(404, "session not found or expired")
        return s

    def _client_session(session_id: str, authorization: str | None = Header(default=None)) -> Session:
        s = _get(session_id)
        if not authorization or not secrets.compare_digest(authorization, f"Bearer {s.client_token}"):
            raise HTTPException(401, "invalid client token")
        return s

    async def _image(upload: UploadFile, name: str):
        try:
            return decode_image(await upload.read(), name)
        except BadImage as e:
            raise HTTPException(400, str(e))

    @router.post("", response_model=SessionCreated, dependencies=[Depends(require_key)])
    def create_session(body: CreateSession):
        s = Session(secrets.token_urlsafe(12), secrets.token_urlsafe(24), **body.model_dump())
        SESSIONS[s.id] = s
        return SessionCreated(session_id=s.id, client_token=s.client_token, expires_at=int(s.created + SESSION_TTL))

    @router.post("/{session_id}/id-front", response_model=StepResult)
    async def id_front(image: UploadFile = File(...), s: Session = Depends(_client_session)):
        f = await run_in_threadpool(face.analyze, await _image(image, "image"))
        s.id_face, s.steps["id_front"] = f, f is not None
        return StepResult(ok=f is not None, issues=[] if f else ["no face found on the front of the ID; retake"])

    @router.post("/{session_id}/id-back", response_model=StepResult)
    async def id_back(
        image: UploadFile = File(...),
        barcode_text: str | None = Form(None, description="Raw PDF417 text decoded on the phone (fallback)"),
        s: Session = Depends(_client_session),
    ):
        doc, issues, source = await run_in_threadpool(read_document, await _image(image, "image"), barcode_text)
        s.doc, s.doc_source, s.steps["id_back"] = doc, source, not issues
        return StepResult(ok=not issues, issues=[i + "; retake" for i in issues])

    @router.post("/{session_id}/selfie", response_model=StepResult)
    async def selfie(frames: list[UploadFile] = File(..., description="straight, turn one way, turn the other"),
                     s: Session = Depends(_client_session)):
        imgs = [await _image(f, f"frame {i}") for i, f in enumerate(frames)]
        faces = await run_in_threadpool(lambda: [face.analyze(i) for i in imgs])
        issues = await run_in_threadpool(liveness.check, faces)
        s.selfie_face, s.liveness_issues = (faces[0] if faces else None), issues
        s.steps["selfie"] = not issues
        return StepResult(ok=not issues, issues=issues)

    @router.get("/{session_id}", response_model=SessionStatus, dependencies=[Depends(require_key)])
    def get_session(session_id: str):
        s = _get(session_id)
        complete = all(s.steps.values())
        result = build_result(
            s.doc or Extracted(), s.id_face, s.selfie_face, s.min_age, s.expected_name, s.expected_dob,
            s.liveness_issues if s.liveness_issues is not None else ["selfie step not completed"],
            s.doc_source,
        )
        return SessionStatus(session_id=s.id, complete=complete, steps=s.steps, result=result)

    return router
