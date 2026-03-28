import logging

from app.config import settings
from app.messenger.client import MessengerClientError, MetaGraphMessengerClient
from app.messenger.service import (
    build_default_get_started_payload,
    build_default_persistent_menu,
)

logger = logging.getLogger(__name__)


def sync_messenger_profile() -> None:
    if not settings.meta_page_access_token:
        raise ValueError("META_PAGE_ACCESS_TOKEN is required")

    client = MetaGraphMessengerClient(page_access_token=settings.meta_page_access_token)
    client.set_messenger_profile(
        get_started_payload=build_default_get_started_payload(),
        menu_items=build_default_persistent_menu(),
    )


def maybe_sync_messenger_profile_on_startup() -> bool:
    if not settings.messenger_profile_sync_on_startup:
        logger.info("Skipping Messenger profile sync on startup because feature flag is disabled.")
        return False

    if not settings.messenger_enabled:
        logger.info("Skipping Messenger profile sync on startup because Messenger is disabled.")
        return False

    if settings.messenger_outbound_mode != "meta_graph":
        logger.info(
            "Skipping Messenger profile sync on startup because outbound mode is %s.",
            settings.messenger_outbound_mode,
        )
        return False

    try:
        sync_messenger_profile()
    except (ValueError, MessengerClientError, OSError) as exc:
        logger.warning("Messenger profile sync on startup failed: %s", exc)
        return False

    logger.info("Messenger profile synced on startup.")
    return True
