import base64
from datetime import date

import cv2
import numpy as np
import zxingcpp
from fastapi.testclient import TestClient

from app import aamva
from app.main import app

# Synthetic AAMVA payload (fake person) in the real on-card layout.
SAMPLE = (
    "@\n\x1e\rANSI 636000090002DL00410278ZV03190008"
    "DLDAQT64235789\nDCSSAMPLE\nDACJANE\nDADQ\nDBD06062019\nDBB01071990\n"
    "DBA01072099\nDBC2\nDAJVA\nDCGUSA\r\nZVZVA01\r"
)


def _barcode_png(text: str) -> bytes:
    img = np.array(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.PDF417), scale=3))
    img = cv2.copyMakeBorder(img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", img)[1].tobytes()


def _blank_png() -> bytes:
    return cv2.imencode(".png", np.full((200, 300, 3), 255, np.uint8))[1].tobytes()


def test_parse_aamva():
    out = aamva.parse_aamva(SAMPLE)
    assert out["name"] == "JANE Q SAMPLE"
    assert out["date_of_birth"] == date(1990, 1, 7)
    assert out["expiration"] == date(2099, 1, 7)
    assert out["document_number"] == "T64235789"
    assert out["sex"] == "F"


def test_parse_canadian_dates():
    out = aamva.parse_aamva("ANSI 636012DL00410278DLDCGCAN\nDBB19900107\nDBA20990107\n")
    assert out["date_of_birth"] == date(1990, 1, 7)


def test_parse_version1_full_name():
    out = aamva.parse_aamva("@\n\x1e\rANSI 6360000101DL00290190DLDAAMOSS,JOHN,Q\nDBB19850315\nDBA20990315\n")
    assert (out["first_name"], out["last_name"], out["name"]) == ("JOHN", "MOSS", "JOHN Q MOSS")
    assert out["date_of_birth"].year == 1985


def test_barcode_found_in_large_photo():
    # barcode small inside a 12MP-ish photo, like a phone shot of the whole card
    code = cv2.imdecode(np.frombuffer(_barcode_png(SAMPLE), np.uint8), cv2.IMREAD_COLOR)
    photo = np.full((3000, 4000, 3), 180, np.uint8)
    photo[1200:1200 + code.shape[0], 1500:1500 + code.shape[1]] = code
    assert aamva.read_barcode(photo) is not None


def test_barcode_roundtrip():
    img = cv2.imdecode(np.frombuffer(_barcode_png(SAMPLE), np.uint8), cv2.IMREAD_COLOR)
    assert aamva.parse_aamva(aamva.read_barcode(img))["last_name"] == "SAMPLE"


def test_verify_without_faces_reports_each_check():
    with TestClient(app) as client:
        r = client.post(
            "/verify",
            files={"id_front": _blank_png(), "id_back": _barcode_png(SAMPLE), "selfie": _blank_png()},
            data={"min_age": "21", "expected_name": "jane sample"},
        )
    body = r.json()
    assert r.status_code == 200
    assert body["verified"] is False
    assert body["checks"]["document_readable"] is True
    assert body["checks"]["not_expired"] is True
    assert body["checks"]["age_ok"] is True
    assert body["checks"]["name_match"] is True
    assert body["checks"]["face_match"] is None
    assert "no face found in selfie" in body["issues"]


def test_json_endpoint_rejects_bad_image():
    with TestClient(app) as client:
        junk = base64.b64encode(b"not an image").decode()
        r = client.post("/verify/json", json={"id_front": junk, "id_back": junk, "selfie": junk})
    assert r.status_code == 400
