"""Session flow tests. Face analysis is faked so we can control yaw (head turn) values."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import face, liveness
from app.main import app
from tests.test_api import SAMPLE, _barcode_png, _blank_png


def fake_face(yaw: float) -> face.Face:
    return face.Face(np.zeros((1, 128), np.float32), yaw)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(face, "similarity", lambda a, b: 0.9)
    with TestClient(app) as c:
        yield c


def _queue_faces(monkeypatch, faces):
    it = iter(faces)
    monkeypatch.setattr(face, "analyze", lambda img: next(it))


def _start(client):
    r = client.post("/sessions", json={"min_age": 21, "expected_name": "Jane Sample"})
    assert r.status_code == 200
    s = r.json()
    return s["session_id"], {"Authorization": f"Bearer {s['client_token']}"}


def _frames():
    return [("frames", (f"f{i}.png", _blank_png(), "image/png")) for i in range(3)]


def test_full_flow_verified(client, monkeypatch):
    sid, auth = _start(client)
    _queue_faces(monkeypatch, [fake_face(0.0), fake_face(0.0), fake_face(-0.35), fake_face(0.4)])

    assert client.post(f"/sessions/{sid}/id-front", files={"image": _blank_png()}, headers=auth).json()["ok"]
    assert client.post(f"/sessions/{sid}/id-back", files={"image": _barcode_png(SAMPLE)}, headers=auth).json()["ok"]
    r = client.post(f"/sessions/{sid}/selfie", files=_frames(), headers=auth).json()
    assert r == {"ok": True, "issues": []}

    status = client.get(f"/sessions/{sid}").json()
    assert status["complete"] is True
    assert status["result"]["verified"] is True
    assert status["result"]["checks"]["liveness"] is True
    assert status["result"]["extracted"]["last_name"] == "SAMPLE"


def test_flat_photo_fails_liveness(client, monkeypatch):
    sid, auth = _start(client)
    # a tilted printed photo: yaw barely moves
    _queue_faces(monkeypatch, [fake_face(0.25), fake_face(0.23), fake_face(0.27)])
    r = client.post(f"/sessions/{sid}/selfie", files=_frames(), headers=auth).json()
    assert r["ok"] is False
    assert "head turn not detected" in r["issues"][0]


def test_turning_same_direction_twice_fails():
    assert liveness.check([fake_face(0.0), fake_face(0.3), fake_face(0.4)])


def test_retake_after_bad_barcode(client):
    sid, auth = _start(client)
    bad = client.post(f"/sessions/{sid}/id-back", files={"image": _blank_png()}, headers=auth).json()
    assert bad["ok"] is False and "retake" in bad["issues"][0]
    good = client.post(f"/sessions/{sid}/id-back", files={"image": _barcode_png(SAMPLE)}, headers=auth).json()
    assert good["ok"] is True


def test_lenient_falls_back_to_phone_decoded_text(client, monkeypatch):
    sid, auth = _start(client)
    # server can't read the image, but the phone sent the text it decoded
    r = client.post(f"/sessions/{sid}/id-back", files={"image": _blank_png()}, data={"barcode_text": SAMPLE},
                    headers=auth).json()
    assert r["ok"] is True
    status = client.get(f"/sessions/{sid}").json()
    assert status["result"]["checks"]["barcode_source"] == "client"
    assert status["result"]["extracted"]["last_name"] == "SAMPLE"


def test_server_decode_preferred_over_phone_text(client):
    sid, auth = _start(client)
    client.post(f"/sessions/{sid}/id-back", files={"image": _barcode_png(SAMPLE)}, data={"barcode_text": "junk"},
                headers=auth)
    assert client.get(f"/sessions/{sid}").json()["result"]["checks"]["barcode_source"] == "server"


def test_client_token_required(client):
    sid, _ = _start(client)
    r = client.post(f"/sessions/{sid}/id-back", files={"image": _blank_png()}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_incomplete_session_not_verified(client):
    sid, _ = _start(client)
    status = client.get(f"/sessions/{sid}").json()
    assert status["complete"] is False
    assert status["result"]["verified"] is False
