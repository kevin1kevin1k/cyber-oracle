import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.config import settings
    from app.messenger.client import MetaGraphMessengerClient
    from app.messenger.service import (
        build_default_get_started_payload,
        build_default_persistent_menu,
    )

    if not settings.meta_page_access_token:
        raise SystemExit("META_PAGE_ACCESS_TOKEN is required")

    client = MetaGraphMessengerClient(page_access_token=settings.meta_page_access_token)
    menu_items = build_default_persistent_menu()
    client.set_messenger_profile(
        get_started_payload=build_default_get_started_payload(),
        menu_items=menu_items,
    )
    print("Messenger profile synced (get started + persistent menu).")


if __name__ == "__main__":
    main()
