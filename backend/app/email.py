import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class EmailMessage:
    to_email: str
    subject: str
    text_body: str
    html_body: str
    tag: str = "transactional"


class NoopEmailSender:
    def send(self, *, message: EmailMessage) -> None:
        logger.info(
            "email.noop_send to=%s tag=%s subject=%s",
            message.to_email,
            message.tag,
            message.subject,
        )


class PostmarkEmailSender:
    api_url = "https://api.postmarkapp.com/email"

    def __init__(
        self,
        *,
        server_token: str,
        from_email: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.server_token = server_token
        self.from_email = from_email
        self.timeout_seconds = timeout_seconds

    def send(self, *, message: EmailMessage) -> None:
        payload = {
            "From": self.from_email,
            "To": message.to_email,
            "Subject": message.subject,
            "TextBody": message.text_body,
            "HtmlBody": message.html_body,
            "MessageStream": "outbound",
            "Tag": message.tag,
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.api_url,
            data=data,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": self.server_token,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response.read()
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise EmailDeliveryError(
                f"Postmark email delivery failed: status={exc.code} body={response_body}"
            ) from exc
        except URLError as exc:
            raise EmailDeliveryError(f"Postmark email delivery failed: {exc.reason}") from exc
        except OSError as exc:
            raise EmailDeliveryError(f"Postmark email delivery failed: {exc}") from exc


def build_email_sender() -> NoopEmailSender | PostmarkEmailSender:
    if settings.email_provider == "postmark":
        return PostmarkEmailSender(
            server_token=(settings.postmark_server_token or "").strip(),
            from_email=(settings.email_from or "").strip(),
        )
    return NoopEmailSender()


def _app_base_url() -> str:
    return settings.app_web_base_url.rstrip("/")


def _build_verification_message(*, to_email: str, token: str) -> EmailMessage:
    verify_url = f"{_app_base_url()}/verify-email?{urlencode({'token': token})}"
    return EmailMessage(
        to_email=to_email,
        subject="請完成 ELIN Email 驗證",
        text_body=(
            "請點擊以下連結完成 Email 驗證：\n"
            f"{verify_url}\n\n"
            "如果這不是你本人操作，請直接忽略此信。"
        ),
        html_body=(
            "<p>請點擊以下連結完成 Email 驗證：</p>"
            f'<p><a href="{verify_url}">{verify_url}</a></p>'
            "<p>如果這不是你本人操作，請直接忽略此信。</p>"
        ),
        tag="verify-email",
    )


def _build_password_reset_message(*, to_email: str, token: str) -> EmailMessage:
    reset_url = f"{_app_base_url()}/reset-password?{urlencode({'token': token})}"
    return EmailMessage(
        to_email=to_email,
        subject="ELIN 重設密碼連結",
        text_body=(
            "請點擊以下連結重設密碼：\n"
            f"{reset_url}\n\n"
            "如果這不是你本人操作，請直接忽略此信。"
        ),
        html_body=(
            "<p>請點擊以下連結重設密碼：</p>"
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
            "<p>如果這不是你本人操作，請直接忽略此信。</p>"
        ),
        tag="reset-password",
    )


def send_verification_email(*, to_email: str, token: str) -> None:
    message = _build_verification_message(to_email=to_email, token=token)
    build_email_sender().send(message=message)
    logger.info("email.sent to=%s tag=%s", to_email, message.tag)


def send_password_reset_email(*, to_email: str, token: str) -> None:
    message = _build_password_reset_message(to_email=to_email, token=token)
    build_email_sender().send(message=message)
    logger.info("email.sent to=%s tag=%s", to_email, message.tag)


NoopEmailClient = NoopEmailSender
PostmarkEmailClient = PostmarkEmailSender
