"""Фоновые задачи: напоминания об окончании подписки и проверка платежей."""
import asyncio
import logging

from aiogram import Bot

import config
import texts
from services import activate_payment, db, rollypay

log = logging.getLogger(__name__)


async def _notify_loop(bot: Bot) -> None:
    """Уведомления: за 3 дня, за 1 день, при истечении."""
    while True:
        try:
            await _run_notifications(bot)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле уведомлений")
        await asyncio.sleep(config.NOTIFY_CHECK_MINUTES * 60)


async def _run_notifications(bot: Bot) -> None:
    from datetime import datetime, timedelta, timezone
    from services import parse_iso, plan_title

    subs = await db.all_active_subs()
    now = datetime.now(timezone.utc)
    for sub in subs:
        try:
            expires = parse_iso(sub["expires_at"])
        except Exception:  # noqa: BLE001
            continue
        left = expires - now
        user = await db.get_user(sub["user_id"])
        if not user or user["banned"]:
            continue
        title = plan_title(sub["plan_id"])
        expires_txt = texts.fmt_date(sub["expires_at"])

        if left <= timedelta(0):
            await db.deactivate_sub(sub["id"])
            await bot.send_message(sub["user_id"], texts.expired_notice(title, expires_txt))
            log.info("Подписка %s истекла — деактивирована", sub["id"])
            continue

        days_left = left.days
        if days_left <= 3 and not sub["notified_3d"]:
            await bot.send_message(sub["user_id"], texts.expiring_notice(title, expires_txt, days_left))
            await db.mark_notified(sub["id"], "notified_3d")
        if days_left <= 1 and not sub["notified_1d"]:
            await bot.send_message(sub["user_id"], texts.expiring_notice(title, expires_txt, days_left))
            await db.mark_notified(sub["id"], "notified_1d")


async def _payment_loop(bot: Bot) -> None:
    """Резервная проверка платежей (если вебхук не доходит)."""
    while True:
        try:
            pending = await db.pending_payments(max_age_hours=24)
            for pay in pending:
                if not (rollypay.configured and pay["rolly_payment_id"]):
                    continue
                try:
                    data = await rollypay.get_payment(pay["rolly_payment_id"])
                except Exception:  # noqa: BLE001
                    continue
                status = (data or {}).get("status")
                if status and status != pay["status"]:
                    await db.update_payment(pay["id"], status)
                if status == "paid":
                    await activate_payment(bot, pay["id"])
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле проверки платежей")
        await asyncio.sleep(config.PAYMENT_CHECK_MINUTES * 60)


async def start_loops(bot: Bot) -> None:
    await asyncio.gather(_notify_loop(bot), _payment_loop(bot))
