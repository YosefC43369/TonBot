"""
Sombra TON Guardian — entry point.

Run with:
    python -m app.main

Or via Docker:
    docker compose up
"""

from __future__ import annotations

import asyncio
import sys

from app.app import create_bot, create_dispatcher
from app.config import get_settings
from app.lifecycle import shutdown, startup
from app.logging_config import get_logger

log = get_logger(__name__)


async def main() -> None:
    try:
        await startup()
    except Exception as exc:
        # startup() already logs the cause without printing secrets
        print(f"Startup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    bot = create_bot(settings.bot_token)
    dp = create_dispatcher()

    dp.startup.register(lambda: log.info("dispatcher_started"))
    dp.shutdown.register(shutdown)

    log.info("polling_started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())