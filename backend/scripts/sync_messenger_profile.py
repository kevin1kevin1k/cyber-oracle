import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.messenger.profile_sync import sync_messenger_profile

    sync_messenger_profile()
    print("Messenger profile synced (get started + persistent menu).")


if __name__ == "__main__":
    main()
