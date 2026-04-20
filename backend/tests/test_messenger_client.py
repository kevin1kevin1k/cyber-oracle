import json
from urllib.error import HTTPError, URLError

import pytest

from app.messenger.client import MessengerClientError, MetaGraphMessengerClient
from app.messenger.schemas import MessengerQuickReplyOption
from app.messenger.service import build_default_persistent_menu


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: str = '{"recipient_id":"1","message_id":"m_1"}',
    ) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_meta_graph_send_text_builds_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-type"]
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token", timeout_seconds=7.5)
    client.send_text(psid="psid-1", text="你好")

    assert captured["url"] == "https://graph.facebook.com/v24.0/me/messages"
    assert captured["timeout"] == 7.5
    assert captured["authorization"] == "Bearer page-token"
    assert captured["content_type"] == "application/json"
    assert captured["payload"] == {
        "recipient": {"id": "psid-1"},
        "messaging_type": "RESPONSE",
        "message": {"text": "你好"},
    }


def test_meta_graph_send_quick_replies_builds_expected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token")
    client.send_quick_replies(
        psid="psid-2",
        text="你也可以選擇以下延伸問題：",
        options=[
            MessengerQuickReplyOption(title="延伸 A", payload="FOLLOWUP:a"),
            MessengerQuickReplyOption(title="延伸 B", payload="FOLLOWUP:b"),
        ],
    )

    assert captured["timeout"] == 10.0
    assert captured["payload"] == {
        "recipient": {"id": "psid-2"},
        "messaging_type": "RESPONSE",
        "message": {
            "text": "你也可以選擇以下延伸問題：",
            "quick_replies": [
                {"content_type": "text", "title": "延伸 A", "payload": "FOLLOWUP:a"},
                {"content_type": "text", "title": "延伸 B", "payload": "FOLLOWUP:b"},
            ],
        },
    }


def test_meta_graph_send_button_template_builds_expected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token")
    client.send_button_template(
        psid="psid-3",
        text="請選擇操作",
        buttons=[
            {"type": "web_url", "title": "去購點", "url": "https://example.com/topup"},
        ],
    )

    assert captured["payload"] == {
        "recipient": {"id": "psid-3"},
        "messaging_type": "RESPONSE",
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "請選擇操作",
                    "buttons": [
                        {
                            "type": "web_url",
                            "title": "去購點",
                            "url": "https://example.com/topup",
                        }
                    ],
                },
            }
        },
    }


@pytest.mark.parametrize("sender_action", ["mark_seen", "typing_on", "typing_off"])
def test_meta_graph_send_sender_action_builds_expected_request(
    monkeypatch: pytest.MonkeyPatch,
    sender_action: str,
) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token")
    getattr(client, sender_action)(psid="psid-action-1")

    assert captured["timeout"] == 10.0
    assert captured["payload"] == {
        "recipient": {"id": "psid-action-1"},
        "sender_action": sender_action,
    }


def test_meta_graph_set_messenger_profile_builds_expected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(body='{"result":"success"}')

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token")
    client.set_messenger_profile(
        greeting_text="歡迎使用 ELIN。",
        get_started_payload="GET_STARTED",
        menu_items=[
            {"type": "postback", "title": "查看剩餘點數", "payload": "SHOW_BALANCE"},
            {"type": "web_url", "title": "前往購點", "url": "https://example.com/wallet"},
        ]
    )

    assert captured["url"] == "https://graph.facebook.com/v24.0/me/messenger_profile"
    assert captured["timeout"] == 10.0
    assert captured["payload"] == {
        "greeting": [
            {
                "locale": "default",
                "text": "歡迎使用 ELIN。",
            }
        ],
        "get_started": {"payload": "GET_STARTED"},
        "persistent_menu": [
            {
                "locale": "default",
                "composer_input_disabled": False,
                "call_to_actions": [
                    {
                        "type": "postback",
                        "title": "查看剩餘點數",
                        "payload": "SHOW_BALANCE",
                    },
                    {
                        "type": "web_url",
                        "title": "前往購點",
                        "url": "https://example.com/wallet",
                    },
                ],
            }
        ]
    }


def test_build_default_persistent_menu_uses_current_web_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.messenger.service.settings.messenger_web_base_url", "https://messenger.example.com")

    assert build_default_persistent_menu() == [
        {
            "type": "postback",
            "title": "查看剩餘點數",
            "payload": "SHOW_BALANCE",
        },
        {
            "type": "postback",
            "title": "回覆方式",
            "payload": "OPEN_REPLY_MODE",
        },
        {
            "type": "postback",
            "title": "前往設定",
            "payload": "OPEN_SETTINGS",
        },
    ]


def test_set_persistent_menu_delegates_to_default_get_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_profile_request(self, payload):  # noqa: ANN001
        captured["payload"] = payload

    monkeypatch.setattr(
        MetaGraphMessengerClient,
        "_send_profile_api_request",
        _fake_profile_request,
    )

    client = MetaGraphMessengerClient(page_access_token="page-token")
    client.set_persistent_menu(menu_items=[{"type": "postback", "title": "A", "payload": "B"}])

    assert captured["payload"] == {
        "greeting": [
            {
                "locale": "default",
                "text": "",
            }
        ],
        "get_started": {"payload": "GET_STARTED"},
        "persistent_menu": [
            {
                "locale": "default",
                "composer_input_disabled": False,
                "call_to_actions": [{"type": "postback", "title": "A", "payload": "B"}],
            }
        ],
    }


def test_meta_graph_send_http_error_raises_messenger_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request, timeout):  # noqa: ANN001
        raise HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=_FakeResponse(body='{"error":{"message":"Invalid token"}}'),
        )

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="bad-token")
    with pytest.raises(MessengerClientError, match="status=400") as exc_info:
        client.send_text(psid="psid-4", text="hello")

    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "META_GRAPH_HTTP_400"
    assert exc_info.value.response_body == '{"error":{"message":"Invalid token"}}'


def test_meta_graph_send_http_500_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request, timeout):  # noqa: ANN001
        raise HTTPError(
            url=request.full_url,
            code=500,
            msg="Internal Error",
            hdrs=None,
            fp=_FakeResponse(body='{"error":{"message":"Server error"}}'),
        )

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token")
    with pytest.raises(MessengerClientError) as exc_info:
        client.send_text(psid="psid-500", text="hello")

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "META_GRAPH_HTTP_500"


def test_meta_graph_send_url_error_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request, timeout):  # noqa: ANN001
        raise URLError("temporary failure")

    monkeypatch.setattr("app.messenger.client.urlopen", _fake_urlopen)

    client = MetaGraphMessengerClient(page_access_token="page-token")
    with pytest.raises(MessengerClientError) as exc_info:
        client.send_text(psid="psid-url", text="hello")

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code is None
    assert exc_info.value.error_code == "META_GRAPH_URL_ERROR"
    assert exc_info.value.reason == "temporary failure"
