
Telegram bot and dispatcher initialization.

Registers all routers and middlewares.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from handlers import balance, help, start, transactions, wallet
from middlewares.access_control import AccessControlMiddleware
from middlewares.error_handler import ErrorHandlerMiddleware


def create_bot(token: str) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # Outer middlewares (run first, before routers)
    dp.update.outer_middleware(ErrorHandlerMiddleware())
    dp.update.outer_middleware(AccessControlMiddleware())

    # Register routers in priority order
    dp.include_router(start.router)
    dp.include_router(help.router)
    dp.include_router(wallet.router)
    dp.include_router(balance.router)
    dp.include_router(transactions.router)

    return dp