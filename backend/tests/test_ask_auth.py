import base64
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_dev_jwt(email_verified: bool) -> str:
    header = {"alg": "none", "typ": "JWT"}
    payload = {"email_verified": email_verified}

    def encode(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    return f"{encode(header)}.{encode(payload)}."


def test_ask_unauthorized_returns_401() -> None:
    response = client.post(
        "/api/v1/ask",
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_ask_unverified_email_returns_403() -> None:
    token = make_dev_jwt(email_verified=False)
    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"


def test_ask_verified_email_returns_200() -> None:
    token = make_dev_jwt(email_verified=True)
    response = client.post(
        "/api/v1/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "測試問題", "lang": "zh", "mode": "analysis"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "mock"
    assert len(payload["layer_percentages"]) == 3
