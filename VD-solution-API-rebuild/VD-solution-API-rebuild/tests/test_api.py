from fastapi.testclient import TestClient
from app.main import app, _validate_url

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_rejects_invalid_url():
    response = client.get("/api/resolve", params={"url": "not-a-url"})
    assert response.status_code == 400

def test_rejects_localhost():
    response = client.get("/api/resolve", params={"url": "http://localhost:8000/private"})
    assert response.status_code == 400
