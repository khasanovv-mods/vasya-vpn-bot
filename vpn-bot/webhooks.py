"""HTTP-сервер (aiohttp) для приёма вебхуков RollyPay.

Если PUBLIC_URL не задан и вебхуки не доходят — бот всё равно подтвердит оплату
через кнопку «✅ Я оплатил — проверить» и фоновую проверку.
"""
import json
import logging

from aiohttp import web
from aiogram import Bot

import config
from services import activate_payment, db, rollypay

log = logging.getLogger(__name__)


def create_app() -> web.Application:
    app = web.Application(client_max_size=1024 * 256)

    async def healthz(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def rollypay_callback(request: web.Request) -> web.Response:
        raw = await request.read()
        ts = request.headers.get("X-Timestamp", "")
        sig = request.headers.get("X-Signature", "")
        if not rollypay.verify_signature(raw, ts, sig):
            log.warning("RollyPay webhook: неверная подпись")
            return web.Response(status=403, text="invalid signature")
        try:
            event = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return web.Response(status=400, text="bad json")

        status = event.get("status")
        payment_id = event.get("payment_id")
        order_id = event.get("order_id")
        log.info("RollyPay webhook: %s %s order=%s", event.get("event_type"), status, order_id)

        pay = None
        if payment_id:
            pay = await db.get_payment_by_rolly_id(payment_id)
        if not pay and order_id:
            pay = await db.get_payment_by_order(order_id)
        if not pay:
            log.warning("RollyPay webhook: платёж не найден в БД (%s/%s)", payment_id, order_id)
            return web.Response(text="OK")

        if status and status != pay["status"]:
            await db.update_payment(pay["id"], status, rolly_payment_id=payment_id)
        if status == "paid":
            bot: Bot = request.app["bot"]
            try:
                await activate_payment(bot, pay["id"])
            except Exception:  # noqa: BLE001
                log.exception("Не удалось активировать платёж %s", pay["id"])
                # 200 всё равно вернём — статус в БД уже обновлён, ретраи не нужны
        return web.Response(text="OK")

    app.router.add_get("/healthz", healthz)
    app.router.add_post("/rollypay/callback", rollypay_callback)
    return app


async def run_webhook_server(bot: Bot, port: int) -> None:
    app = create_app()
    app["bot"] = bot
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("HTTP-сервер вебхуков запущен на порту %s (POST /rollypay/callback)", port)
