import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from jwt import InvalidTokenError

from app.messenger.constants import WEBHOOK_MODE_SUBSCRIBE
from app.messenger.schemas import MessengerVerifyResult

MESSENGER_LINK_TOKEN_PURPOSE = "messenger_link"
MESSENGER_LINK_TOKEN_EXP_MINUTES = 30


@dataclass
class MessengerLinkClaims:
    psid: str
    page_id: str
    purpose: str


def create_messenger_link_token(
    *,
    psid: str,
    page_id: str,
    secret_key: str,
    algorithm: str,
    expires_minutes: int = MESSENGER_LINK_TOKEN_EXP_MINUTES,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "purpose": MESSENGER_LINK_TOKEN_PURPOSE,
        "psid": psid,
        "page_id": page_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_messenger_link_token(
    *,
    token: str,
    secret_key: str,
    algorithm: str,
) -> MessengerLinkClaims | None:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except InvalidTokenError:
        return None
    if not isinstance(payload, dict):
        return None
    purpose = payload.get("purpose")
    psid = payload.get("psid")
    page_id = payload.get("page_id")
    if purpose != MESSENGER_LINK_TOKEN_PURPOSE:
        return None
    if not isinstance(psid, str) or not psid.strip():
        return None
    if not isinstance(page_id, str):
        return None
    return MessengerLinkClaims(psid=psid.strip(), page_id=page_id.strip(), purpose=purpose)


def verify_webhook_challenge(
    *,
    mode: str,
    verify_token: str,
    challenge: str,
    expected_verify_token: str | None,
) -> MessengerVerifyResult:
    if mode != WEBHOOK_MODE_SUBSCRIBE:
        return MessengerVerifyResult(ok=False)
    if not expected_verify_token:
        return MessengerVerifyResult(ok=False)
    if not hmac.compare_digest(verify_token, expected_verify_token):
        return MessengerVerifyResult(ok=False)
    return MessengerVerifyResult(ok=True, challenge=challenge)


def verify_app_secret_signature(
    *,
    body: bytes,
    signature_header: str | None,
    app_secret: str | None,
) -> bool:
    """Validate Meta webhook signature.

    Skeleton note:
    - This utility computes sha256 signature when inputs are available.
    - Production hardening should add strict replay protection and richer logging policy.
    """
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False

    received_signature = signature_header.removeprefix("sha256=")
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_signature, digest)
