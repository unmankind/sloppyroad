"""Notification routes: list, mark read, mark all read."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.auth.dependencies import get_current_user
from aiwebnovel.db.models import Notification
from aiwebnovel.db.schemas import NotificationRead
from aiwebnovel.db.session import get_db


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=list[NotificationRead])
async def list_notifications(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationRead]:
    """List unread notifications for current user."""
    stmt = (
        select(Notification)
        .where(
            Notification.user_id == user["user_id"],
            Notification.is_read.is_(False),
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    notifications = result.scalars().all()
    return [NotificationRead.model_validate(n) for n in notifications]


@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    """Mark a notification as read."""
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user["user_id"],
    )
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()

    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    notification.is_read = True
    notification.read_at = _utcnow()
    await db.flush()

    return NotificationRead.model_validate(notification)


@router.patch("/read-all")
async def mark_all_read(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark all notifications as read for current user."""
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user["user_id"],
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=_utcnow())
    )
    result = await db.execute(stmt)
    await db.flush()

    count = result.rowcount

    logger.info("notifications_marked_read", user_id=user["user_id"], count=count)

    return {"message": f"Marked {count} notifications as read", "count": count}
