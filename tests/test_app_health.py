from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_telegram_webhook_rejects_missing_secret():
    resp = client.post("/telegram/webhook", json={"update_id": 1})
    assert resp.status_code == 403
