import hashlib
import hmac

from app.messenger.constants import WEBHOOK_MODE_SUBSCRIBE
from app.messenger.schemas import MessengerVerifyResult


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
