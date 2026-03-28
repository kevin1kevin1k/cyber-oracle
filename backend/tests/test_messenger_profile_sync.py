import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.messenger.client import MessengerClientError
from app.messenger.profile_sync import (
    maybe_sync_messenger_profile_on_startup,
    sync_messenger_profile,
)


def test_sync_messenger_profile_pushes_get_started_and_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *, page_access_token: str) -> None:
            captured["page_access_token"] = page_access_token

        def set_messenger_profile(
            self,
            *,
            greeting_text: str,
            get_started_payload: str,
            menu_items: list[dict[str, str]],
        ) -> None:
            captured["greeting_text"] = greeting_text
            captured["get_started_payload"] = get_started_payload
            captured["menu_items"] = menu_items

    monkeypatch.setattr(
        "app.messenger.profile_sync.MetaGraphMessengerClient",
        _FakeClient,
    )
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.meta_page_access_token",
        "page-token",
    )

    sync_messenger_profile()

    assert captured["page_access_token"] == "page-token"
    assert (
        captured["greeting_text"]
        == "歡迎使用 ELIN 神域引擎。先點擊下方的 Get Started，再前往 WebView "
        "完成綁定與固定資料設定，就能直接在 Messenger 提問。"
    )
    assert captured["get_started_payload"] == "GET_STARTED"
    assert captured["menu_items"] == [
        {
            "type": "postback",
            "title": "查看剩餘點數",
            "payload": "SHOW_BALANCE",
        },
        {
            "type": "postback",
            "title": "前往購點",
            "payload": "OPEN_WALLET",
        },
        {
            "type": "postback",
            "title": "查看歷史",
            "payload": "OPEN_HISTORY",
        },
    ]


def test_maybe_sync_messenger_profile_on_startup_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.messenger_profile_sync_on_startup",
        False,
    )
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.messenger_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.messenger_outbound_mode",
        "meta_graph",
    )

    called = {"value": False}

    def _fake_sync() -> None:
        called["value"] = True

    monkeypatch.setattr("app.messenger.profile_sync.sync_messenger_profile", _fake_sync)

    assert maybe_sync_messenger_profile_on_startup() is False
    assert called["value"] is False


def test_maybe_sync_messenger_profile_on_startup_warns_but_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.messenger_profile_sync_on_startup",
        True,
    )
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.messenger_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.messenger.profile_sync.settings.messenger_outbound_mode",
        "meta_graph",
    )

    def _fake_sync() -> None:
        raise MessengerClientError("boom")

    monkeypatch.setattr("app.messenger.profile_sync.sync_messenger_profile", _fake_sync)

    with caplog.at_level("WARNING"):
        assert maybe_sync_messenger_profile_on_startup() is False

    assert "Messenger profile sync on startup failed: boom" in caplog.text


def test_app_startup_triggers_messenger_profile_sync_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _fake_startup_sync() -> bool:
        calls["count"] += 1
        return True

    monkeypatch.setattr(
        "app.main.maybe_sync_messenger_profile_on_startup",
        _fake_startup_sync,
    )

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/health")

    assert response.status_code == 200
    assert calls["count"] == 1
