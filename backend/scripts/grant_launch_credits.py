import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.launch import issue_public_launch_grant_if_needed
from app.models.user import User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grant launch credits to a verified user by email."
    )
    parser.add_argument("--email", required=True, help="Target user email")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    email = args.email.strip().lower()

    session = SessionLocal()
    try:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"user not found: {email}")
            return 1
        balance = issue_public_launch_grant_if_needed(db=session, user_id=user.id)
        print(f"launch credits ensured for {email}; current balance={balance}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
