from fastapi.testclient import TestClient
from app.main import app, validate_video_url

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home_and_docs():
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 200


def test_reject_invalid_scheme():
    try:
        validate_video_url("file:///etc/passwd")
        assert False, "Expected URL validation to reject file scheme"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400


def test_reject_localhost():
    try:
        validate_video_url("http://localhost:8000/private")
        assert False, "Expected URL validation to reject localhost"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
