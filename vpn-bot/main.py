"""Точка входа: запуск бота (long polling) + HTTP-сервер вебхуков + фоновые задачи."""
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from handlers import admin, buy, support, user
from scheduler import start_loops
from webhooks import run_webhook_server
import services

log = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    if not config.BOT_TOKEN:
        sys.exit("BOT_TOKEN не задан — заполните .env (см. .env.example)")

    await services.init()

    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # порядок важен: админ → FSM поддержки → меню → покупка
    dp.include_routers(admin.router, support.router, user.router, buy.router)

    @dp.errors
    async def on_error(update, exception):  # noqa: ANN001
        logging.getLogger("errors").exception("Ошибка обработки апдейта: %s", exception)
        return True

    # фоновые задачи
    asyncio.create_task(run_webhook_server(bot, config.WEBHOOK_PORT))
    asyncio.create_task(start_loops(bot))

    log.info("Бот @%s запускается (long polling)…", (await bot.me()).username)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await services.h1.close()
        await services.rollypay.close()
        await services.db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
