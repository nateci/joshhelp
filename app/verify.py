"""Run every check and build the response. Each check is reported separately so the
calling app can decide what to do with edge cases (e.g. good face match on an expired ID)."""
import re
from datetime import date

import cv2
import numpy as np
from pydantic import BaseModel

from . import aamva, face


class BadImage(ValueError):
    pass


class Checks(BaseModel):
    document_readable: bool
    not_expired: bool | None
    age_ok: bool | None
    face_on_id: bool
    face_in_selfie: bool
    face_match: bool | None
    face_similarity: float | None
    name_match: bool | None = None  # only set when expected_name is sent
    dob_match: bool | None = None  # only set when expected_dob is sent


class Extracted(BaseModel):
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    expiration: date | None = None
    document_number: str | None = None
    state: str | None = None
    country: str | None = None
    sex: str | None = None
    age: int | None = None


class VerifyResult(BaseModel):
    verified: bool
    checks: Checks
    extracted: Extracted
    issues: list[str]


def decode_image(data: bytes, field: str) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    if img is None:
        raise BadImage(f"{field} is not a readable image")
    return img


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _norm(name: str) -> set[str]:
    return set(re.sub(r"[^a-z ]", "", name.lower()).split())


def verify(
    id_front: bytes,
    id_back: bytes,
    selfie: bytes,
    min_age: int = 18,
    expected_name: str | None = None,
    expected_dob: date | None = None,
) -> VerifyResult:
    front = decode_image(id_front, "id_front")
    back = decode_image(id_back, "id_back")
    selfie_img = decode_image(selfie, "selfie")
    today = date.today()
    issues: list[str] = []

    # --- Document (barcode on the back) ---
    text = aamva.read_barcode(back)
    info = aamva.parse_aamva(text) if text else {}
    if not text:
        issues.append("no PDF417 barcode found on id_back")
    ext = Extracted(**{k: v for k, v in info.items() if k in Extracted.model_fields})
    readable = bool(ext.name and ext.date_of_birth and ext.expiration)
    if text and not readable:
        issues.append("barcode found but name/date_of_birth/expiration missing")

    not_expired = ext.expiration >= today if ext.expiration else None
    if not_expired is False:
        issues.append(f"document expired on {ext.expiration}")

    age_ok = None
    if ext.date_of_birth:
        ext.age = _age(ext.date_of_birth, today)
        age_ok = ext.age >= min_age
        if not age_ok:
            issues.append(f"age {ext.age} is under minimum {min_age}")

    # --- Optional cross-checks against what the user typed into the app ---
    name_match = dob_match = None
    if expected_name is not None:
        name_match = bool(ext.name) and _norm(expected_name) <= _norm(ext.name)
        if not name_match:
            issues.append("expected_name does not match the ID")
    if expected_dob is not None:
        dob_match = ext.date_of_birth == expected_dob
        if not dob_match:
            issues.append("expected_dob does not match the ID")

    # --- Face match (ID photo vs selfie) ---
    id_face = face.embed_largest_face(front)
    selfie_face = face.embed_largest_face(selfie_img)
    if id_face is None:
        issues.append("no face found on id_front")
    if selfie_face is None:
        issues.append("no face found in selfie")
    sim = match = None
    if id_face is not None and selfie_face is not None:
        sim = round(face.similarity(id_face, selfie_face), 3)
        match = sim >= face.MATCH_THRESHOLD
        if not match:
            issues.append("selfie does not match the ID photo")

    checks = Checks(
        document_readable=readable,
        not_expired=not_expired,
        age_ok=age_ok,
        face_on_id=id_face is not None,
        face_in_selfie=selfie_face is not None,
        face_match=match,
        face_similarity=sim,
        name_match=name_match,
        dob_match=dob_match,
    )
    required = [readable, not_expired, age_ok, match]
    required += [c for c in (name_match, dob_match) if c is not None]
    return VerifyResult(verified=all(c is True for c in required), checks=checks, extracted=ext, issues=issues)
