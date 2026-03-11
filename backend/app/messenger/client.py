from typing import Protocol

from app.messenger.schemas import MessengerOutgoingMessage, MessengerQuickReplyOption


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
    """Placeholder for future Graph API implementation."""

    def __init__(self, *, page_access_token: str) -> None:
        self.page_access_token = page_access_token

    def send_text(self, *, psid: str, text: str) -> None:
        raise MessengerClientError("Meta Graph send_text is not implemented yet")

    def send_quick_replies(
        self,
        *,
        psid: str,
        text: str,
        options: list[MessengerQuickReplyOption],
    ) -> None:
        raise MessengerClientError("Meta Graph send_quick_replies is not implemented yet")

    def send_button_template(self, *, psid: str, text: str, buttons: list[dict[str, str]]) -> None:
        raise MessengerClientError("Meta Graph send_button_template is not implemented yet")


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
