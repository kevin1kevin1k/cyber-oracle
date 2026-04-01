import json
import logging
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.messenger.schemas import MessengerOutgoingMessage, MessengerQuickReplyOption

logger = logging.getLogger(__name__)


class MessengerClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        error_code: str | None = None,
        response_body: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.error_code = error_code
        self.response_body = response_body
        self.reason = reason


class MessengerClientProtocol(Protocol):
    def mark_seen(self, *, psid: str) -> None: ...

    def typing_on(self, *, psid: str) -> None: ...

    def typing_off(self, *, psid: str) -> None: ...

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

    def set_persistent_menu(self, *, menu_items: list[dict[str, Any]]) -> None: ...


class NoopMessengerClient:
    """Local/dev stub client.

    Intentionally no-op so webhook handling remains testable without external Meta calls.
    """

    def mark_seen(self, *, psid: str) -> None:
        _ = psid

    def typing_on(self, *, psid: str) -> None:
        _ = psid

    def typing_off(self, *, psid: str) -> None:
        _ = psid

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

    def set_messenger_profile(
        self,
        *,
        greeting_text: str,
        get_started_payload: str,
        menu_items: list[dict[str, Any]],
    ) -> None: ...

    def set_persistent_menu(self, *, menu_items: list[dict[str, Any]]) -> None:
        self.set_messenger_profile(
            greeting_text="",
            get_started_payload="GET_STARTED",
            menu_items=menu_items,
        )


class MetaGraphMessengerClient:
    """Minimal Messenger Send API client backed by Meta Graph API."""

    graph_api_url = "https://graph.facebook.com/v24.0/me/messages"
    messenger_profile_api_url = "https://graph.facebook.com/v24.0/me/messenger_profile"

    def __init__(self, *, page_access_token: str, timeout_seconds: float = 10.0) -> None:
        self.page_access_token = page_access_token
        self.timeout_seconds = timeout_seconds

    def mark_seen(self, *, psid: str) -> None:
        self._send_sender_action(psid=psid, sender_action="mark_seen")

    def typing_on(self, *, psid: str) -> None:
        self._send_sender_action(psid=psid, sender_action="typing_on")

    def typing_off(self, *, psid: str) -> None:
        self._send_sender_action(psid=psid, sender_action="typing_off")

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

    def set_messenger_profile(
        self,
        *,
        greeting_text: str,
        get_started_payload: str,
        menu_items: list[dict[str, Any]],
    ) -> None:
        self._send_profile_api_request(
            {
                "greeting": [
                    {
                        "locale": "default",
                        "text": greeting_text,
                    }
                ],
                "get_started": {"payload": get_started_payload},
                "persistent_menu": [
                    {
                        "locale": "default",
                        "composer_input_disabled": False,
                        "call_to_actions": menu_items,
                    }
                ]
            }
        )

    def set_persistent_menu(self, *, menu_items: list[dict[str, Any]]) -> None:
        self.set_messenger_profile(
            greeting_text="",
            get_started_payload="GET_STARTED",
            menu_items=menu_items,
        )

    def _send_api_request(self, payload: dict[str, Any]) -> None:
        self._post_json(self.graph_api_url, payload)

    def _send_sender_action(self, *, psid: str, sender_action: str) -> None:
        self._send_api_request(
            {
                "recipient": {"id": psid},
                "sender_action": sender_action,
            }
        )

    def _send_profile_api_request(self, payload: dict[str, Any]) -> None:
        self._post_json(self.messenger_profile_api_url, payload)

    def _post_json(self, url: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
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
            retryable = exc.code == 429 or 500 <= exc.code < 600
            raise MessengerClientError(
                f"Meta Graph send failed: status={exc.code} body={response_body}",
                retryable=retryable,
                status_code=exc.code,
                error_code=f"META_GRAPH_HTTP_{exc.code}",
                response_body=response_body,
            ) from exc
        except URLError as exc:
            reason = str(exc.reason)
            raise MessengerClientError(
                f"Meta Graph send failed: {reason}",
                retryable=True,
                error_code="META_GRAPH_URL_ERROR",
                reason=reason,
            ) from exc
        except OSError as exc:
            error_code = (
                "META_GRAPH_TIMEOUT"
                if isinstance(exc, (TimeoutError, socket.timeout))
                else "META_GRAPH_OS_ERROR"
            )
            raise MessengerClientError(
                f"Meta Graph send failed: {exc}",
                retryable=True,
                error_code=error_code,
                reason=str(exc),
            ) from exc


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
