"""
Access control middleware.

- Private chats: all users allowed by default.
- Admin commands: restricted to ADMIN_USER_IDS.
- Group chats: blocked in Phase 1.

Authorization is always based on numeric Telegram user ID — never username.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


class AccessControlMiddleware(BaseMiddleware):
    """
    Outer update middleware.

    Attaches `telegram_user_id` and `is_admin` to the handler data dict.
    Rejects group/channel messages (Phase 1: private-chat only).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings = get_settings()

        user_id: int | None = None
        chat_type: str = "unknown"

        if isinstance(event, Update):
            if event.message and event.message.from_user:
                user_id = event.message.from_user.id
                chat_type = event.message.chat.type
            elif event.callback_query and event.callback_query.from_user:
                user_id = event.callback_query.from_user.id
                chat_type = "private"

        # Block group/channel usage in Phase 1
        if chat_type in ("group", "supergroup", "channel"):
            log.info("access_denied_group_chat", user_id=user_id)
            return None

        data["telegram_user_id"] = user_id
        data["is_admin"] = user_id is not None and settings.is_admin(user_id)

        return await handler(event, data)