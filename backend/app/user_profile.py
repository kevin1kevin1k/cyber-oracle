from fastapi import HTTPException, status

from app.models.user import User

PROFILE_INCOMPLETE_CODE = "PROFILE_INCOMPLETE"
PROFILE_INCOMPLETE_MESSAGE = "請先完成個人設定後再提問。"


def normalize_profile_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def is_profile_complete(user: User | None) -> bool:
    if user is None:
        return False
    return bool(
        normalize_profile_value(user.full_name) and normalize_profile_value(user.mother_name)
    )


def ensure_profile_complete(user: User | None) -> None:
    if is_profile_complete(user):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": PROFILE_INCOMPLETE_CODE,
            "message": PROFILE_INCOMPLETE_MESSAGE,
        },
    )


def build_augmented_question(*, user: User, question_text: str) -> str:
    full_name = normalize_profile_value(user.full_name)
    mother_name = normalize_profile_value(user.mother_name)
    if not full_name or not mother_name:
        raise ValueError("user profile is incomplete")
    return (
        "以下是提問者固定資料，請納入理解後再回答。\n"
        f"我的姓名：{full_name}\n"
        f"我母親的姓名：{mother_name}\n\n"
        f"本次問題：{question_text.strip()}"
    )
