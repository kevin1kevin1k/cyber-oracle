import json
import logging
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.messenger.schemas import MessengerOutgoingMessage, MessengerQuickReplyOption

logger = logging.getLogger(__name__)


class MessengerClientError(Exception):
    pass


class MessengerClientProtocol(Protocol):
    def send_text(self, *, psid: str, text: str) -> None: ...

    def send_quick_replies(
        self,
        *,
        psid: str,
        text: str,
        options: list[MessengerQuickReplyOption],
    ) -> None: ...

    def send_button_template(
        self,
        *,
        psid: str,
        text: str,
        buttons: list[dict[str, str]],
    ) -> None: ...


class NoopMessengerClient:
    """Local/dev stub client.

    Intentionally no-op so webhook handling remains testable without external Meta calls.
    """

    def send_text(self, *, psid: str, text: str) -> None:
        _ = (psid, text)

    def send_quick_replies(
        self,
        *,
        psid: str,
        text: str,
        options: list[MessengerQuickReplyOption],
    ) -> None:
        _ = (psid, text, options)

    def send_button_template(self, *, psid: str, text: str, buttons: list[dict[str, str]]) -> None:
        _ = (psid, text, buttons)


class MetaGraphMessengerClient:
    """Minimal Messenger Send API client backed by Meta Graph API."""

    graph_api_url = "https://graph.facebook.com/v24.0/me/messages"

    def __init__(self, *, page_access_token: str, timeout_seconds: float = 10.0) -> None:
        self.page_access_token = page_access_token
        self.timeout_seconds = timeout_seconds

    def send_text(self, *, psid: str, text: str) -> None:
        self._send_api_request(
            {
                "recipient": {"id": psid},
                "messaging_type": "RESPONSE",
                "message": {"text": text},
            }
        )

    def send_quick_replies(
        self,
        *,
        psid: str,
        text: str,
        options: list[MessengerQuickReplyOption],
    ) -> None:
        self._send_api_request(
            {
                "recipient": {"id": psid},
                "messaging_type": "RESPONSE",
                "message": {
                    "text": text,
                    "quick_replies": [
                        {
                            "content_type": "text",
                            "title": option.title,
                            "payload": option.payload,
                        }
                        for option in options
                    ],
                },
            }
        )

    def send_button_template(self, *, psid: str, text: str, buttons: list[dict[str, str]]) -> None:
        self._send_api_request(
            {
                "recipient": {"id": psid},
                "messaging_type": "RESPONSE",
                "message": {
                    "attachment": {
                        "type": "template",
                        "payload": {
                            "template_type": "button",
                            "text": text,
                            "buttons": buttons,
                        },
                    }
                },
            }
        )

    def _send_api_request(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.graph_api_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.page_access_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                logger.debug(
                    "Meta Graph send success: status=%s body=%s",
                    response.status,
                    response_body,
                )
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise MessengerClientError(
                f"Meta Graph send failed: status={exc.code} body={response_body}"
            ) from exc
        except URLError as exc:
            raise MessengerClientError(f"Meta Graph send failed: {exc.reason}") from exc
        except OSError as exc:
            raise MessengerClientError(f"Meta Graph send failed: {exc}") from exc


def dispatch_outgoing_message(
    *,
    client: MessengerClientProtocol,
    psid: str,
    outgoing: MessengerOutgoingMessage,
) -> None:
    if outgoing.kind == "text":
        client.send_text(psid=psid, text=outgoing.text)
        return
    if outgoing.kind == "quick_replies":
        client.send_quick_replies(psid=psid, text=outgoing.text, options=outgoing.quick_replies)
        return
    client.send_button_template(psid=psid, text=outgoing.text, buttons=outgoing.buttons)
