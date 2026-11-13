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
    # "server" = we decoded the barcode image ourselves; "client" = we trusted the text the phone
    # decoded (lenient mode: a tampered client could fake it). Tighten later by requiring "server".
    barcode_source: str | None = None
    liveness: bool | None = None  # only set by the session flow (head-turn frames)
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


def read_document(back: np.ndarray, client_text: str | None = None) -> tuple[Extracted, list[str], str | None]:
    """Read the barcode on the back of the ID. Returns extracted fields, issues, and where the
    barcode text came from: "server" (we decoded the image) or "client" (we couldn't, so we
    fell back to the text the phone's scanner decoded; LENIENT MODE, see barcode_source)."""
    text, source = aamva.read_barcode(back), "server"
    if not text and client_text:
        text, source = client_text, "client"
    if not text:
        return Extracted(), ["no PDF417 barcode found on id_back"], None
    info = aamva.parse_aamva(text)
    ext = Extracted(**{k: v for k, v in info.items() if k in Extracted.model_fields})
    # Lenient: only DOB + expiration are required (they drive the age and expiry checks).
    if not (ext.date_of_birth and ext.expiration):
        return ext, ["barcode found but date_of_birth/expiration missing"], source
    return ext, [], source


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _norm(name: str) -> set[str]:
    return set(re.sub(r"[^a-z ]", "", name.lower()).split())


def build_result(
    ext: Extracted,
    id_face: face.Face | None,
    selfie_face: face.Face | None,
    min_age: int = 18,
    expected_name: str | None = None,
    expected_dob: date | None = None,
    liveness_issues: list[str] | None = None,
    barcode_source: str | None = None,
) -> VerifyResult:
    """Turn already-analyzed pieces into the final result. liveness_issues=None means not checked."""
    ext = ext.model_copy()
    today = date.today()
    issues: list[str] = []
    readable = bool(ext.date_of_birth and ext.expiration)
    if not readable:
        issues.append("document not readable")

    not_expired = ext.expiration >= today if ext.expiration else None
    if not_expired is False:
        issues.append(f"document expired on {ext.expiration}")

    age_ok = None
    if ext.date_of_birth:
        ext.age = _age(ext.date_of_birth, today)
        age_ok = ext.age >= min_age
        if not age_ok:
            issues.append(f"age {ext.age} is under minimum {min_age}")

    name_match = dob_match = None
    if expected_name is not None:
        name_match = bool(ext.name) and _norm(expected_name) <= _norm(ext.name)
        if not name_match:
            issues.append("expected_name does not match the ID")
    if expected_dob is not None:
        dob_match = ext.date_of_birth == expected_dob
        if not dob_match:
            issues.append("expected_dob does not match the ID")

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

    liveness = None
    if liveness_issues is not None:
        liveness = not liveness_issues
        issues += liveness_issues

    checks = Checks(
        document_readable=readable,
        not_expired=not_expired,
        age_ok=age_ok,
        face_on_id=id_face is not None,
        face_in_selfie=selfie_face is not None,
        face_match=match,
        face_similarity=sim,
        barcode_source=barcode_source,
        liveness=liveness,
        name_match=name_match,
        dob_match=dob_match,
    )
    required = [readable, not_expired, age_ok, match]
    required += [c for c in (liveness, name_match, dob_match) if c is not None]
    return VerifyResult(verified=all(c is True for c in required), checks=checks, extracted=ext, issues=issues)


def verify(
    id_front: bytes,
    id_back: bytes,
    selfie: bytes,
    min_age: int = 18,
    expected_name: str | None = None,
    expected_dob: date | None = None,
) -> VerifyResult:
    """One-shot check (no liveness): all three images at once."""
    front = decode_image(id_front, "id_front")
    back = decode_image(id_back, "id_back")
    selfie_img = decode_image(selfie, "selfie")
    ext, _, source = read_document(back)
    return build_result(
        ext, face.analyze(front), face.analyze(selfie_img), min_age, expected_name, expected_dob,
        barcode_source=source,
    )
