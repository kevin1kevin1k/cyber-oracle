from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.security import create_access_token

client = TestClient(app)


def make_dev_jwt(email_verified: bool) -> str:
    return create_access_token(
        subject="dev-user",
        email="dev@example.com",
        email_verified=email_verified,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )


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
