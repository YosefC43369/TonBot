"""
Global error handling middleware.

Catches unhandled exceptions, logs them with context,
and returns a safe message to the user without stack traces.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, Update

from app.logging_config import get_logger
from security.redaction import safe_error_message

log = get_logger(__name__)

_USER_ERROR_MSG = (
    "Something went wrong while processing your request. "
    "Please try again in a moment."
)


class ErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            log.exception(
                "unhandled_handler_error",
                error_type=type(exc).__name__,
                error_safe=safe_error_message(exc),
            )
            # Reply to the user with a safe message — no stack trace
            if isinstance(event, Update) and event.message:
                try:
                    await event.message.answer(_USER_ERROR_MSG)
                except Exception:
                    pass  # best-effort; don't re-raise on send failure
            return None