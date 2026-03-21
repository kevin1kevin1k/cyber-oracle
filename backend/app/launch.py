import logging
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.credit_transaction import CreditTransaction
from app.models.credit_wallet import CreditWallet

logger = logging.getLogger(__name__)

PUBLIC_LAUNCH_GRANT_REASON_CODE = "MESSENGER_LINK_BETA_GRANT"


def _get_or_create_wallet_for_update(db: Session, user_id: UUID) -> CreditWallet:
    db.execute(
        pg_insert(CreditWallet)
        .values(user_id=user_id, balance=0)
        .on_conflict_do_nothing(index_elements=[CreditWallet.user_id])
    )
    wallet = db.scalar(
        select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
    )
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "WALLET_NOT_AVAILABLE", "message": "Wallet is not available"},
        )
    return wallet


def issue_public_launch_grant_if_needed(*, db: Session, user_id: UUID) -> int:
    grant_idempotency_key = f"launch-grant:{user_id}"
    existing_grant = db.scalar(
        select(CreditTransaction.id).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.action == "grant",
            CreditTransaction.idempotency_key == grant_idempotency_key,
        )
    )
    wallet = _get_or_create_wallet_for_update(db=db, user_id=user_id)
    if existing_grant is not None or settings.launch_credit_grant_amount == 0:
        return wallet.balance

    wallet.balance += settings.launch_credit_grant_amount
    request_id = str(uuid4())
    db.add(wallet)
    db.add(
        CreditTransaction(
            user_id=user_id,
            action="grant",
            amount=settings.launch_credit_grant_amount,
            reason_code=PUBLIC_LAUNCH_GRANT_REASON_CODE,
            idempotency_key=grant_idempotency_key,
            request_id=request_id,
        )
    )
    db.commit()
    db.refresh(wallet)
    logger.info(
        "Issued public launch credits: user_id=%s amount=%s request_id=%s",
        user_id,
        settings.launch_credit_grant_amount,
        request_id,
    )
    return wallet.balance
