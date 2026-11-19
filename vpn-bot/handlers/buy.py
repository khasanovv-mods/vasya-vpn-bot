"""Покупка подписки: выбор тарифа, создание счёта RollyPay, проверка оплаты."""
import logging
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import texts
from keyboards import cancelled_kb, payment_kb, sub_menu
from rollypay import RollyPayError
from services import activate_payment, db, rollypay, status_line

log = logging.getLogger(__name__)
router = Router(name="buy")


@router.callback_query(F.data == "sub:trial")
async def cb_trial(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        return
    from services import grant_trial
    ok = await grant_trial(cb.bot, cb.from_user.id)
    if not ok:
        await cb.message.answer(texts.TRIAL_UNAVAILABLE)
    await cb.answer()


@router.callback_query(F.data.startswith("sub:buy:"))
async def cb_buy(cb: CallbackQuery, state: FSMContext) -> None:
    msg = cb.message
    if not cb.from_user or not msg:
        return
    tg_id = cb.from_user.id
    plan_id = cb.data.split(":")[-1]
    plan = config.get_plan(plan_id)
    if not plan:
        await cb.answer("Тариф не найден", show_alert=True)
        return
    if not config.rollypay_configured():
        await cb.answer(
            "Оплата временно недоступна. Напишите в 🛟 Поддержку — оформим вручную.", show_alert=True,
        )
        return

    user = await db.get_user(tg_id)
    if not user:
        await cb.answer("Сначала /start", show_alert=True)
        return

    order_id = f"tg{tg_id}-{plan_id}-{int(time.time())}"
    try:
        pay = await rollypay.create_payment(
            amount=plan["price"],
            order_id=order_id,
            description=f"{config.BRAND_NAME}: подписка {plan['title']}",
            metadata={"user_id": tg_id, "plan_id": plan_id},
        )
    except RollyPayError as e:
        log.error("RollyPay: создание платежа не удалось: %s", e)
        await cb.answer("Не удалось создать счёт, попробуйте позже.", show_alert=True)
        return

    db_id = await db.create_payment(tg_id, plan_id, order_id, plan["price"])
    rolly_id = pay.get("payment_id")
    pay_url = pay.get("pay_url")
    if not pay_url:
        log.error("RollyPay: нет pay_url в ответе: %s", pay)
        await db.update_payment(db_id, "canceled")
        await cb.answer("Не удалось создать счёт, попробуйте позже.", show_alert=True)
        return
    await db.update_payment(db_id, "created", rolly_payment_id=rolly_id)

    await msg.answer(
        texts.payment_created(plan, pay_url, order_id, config.RP_TEST_MODE),
        reply_markup=payment_kb(pay_url, db_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("keyc:"))
async def cb_country_key(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        return
    try:
        index = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    from services import db as db_, send_country_key
    sub = await db_.active_sub(cb.from_user.id)
    if not sub:
        await cb.answer("Нет активной подписки", show_alert=True)
        return
    await send_country_key(cb.bot, cb.from_user.id, sub, index)
    await cb.answer()


@router.callback_query(F.data.startswith("sub:check:"))
async def cb_check(cb: CallbackQuery) -> None:
    if not cb.from_user or not cb.message:
        return
    tg_id = cb.from_user.id
    payment_db_id = int(cb.data.split(":")[-1])
    pay = await db.get_payment(payment_db_id)
    if not pay or pay["user_id"] != tg_id:
        await cb.answer("Счёт не найден", show_alert=True)
        return
    if pay["activated"]:
        await cb.answer("Оплата уже учтена ✅", show_alert=True)
        return

    if not (rollypay.configured and pay["rolly_payment_id"]):
        await cb.answer("Оплата ещё не поступила. Попробуйте через минуту.", show_alert=True)
        return

    try:
        data = await rollypay.get_payment(pay["rolly_payment_id"])
    except RollyPayError as e:
        log.error("RollyPay: проверка статуса не удалась: %s", e)
        await cb.answer("Сервис оплаты не отвечает, попробуйте позже.", show_alert=True)
        return

    status = (data or {}).get("status") or pay["status"]
    await db.update_payment(payment_db_id, status)

    if status == "paid":
        activated = await activate_payment(cb.bot, payment_db_id)
        if activated:
            await cb.answer("Оплата подтверждена ✅", show_alert=True)
            return
        await cb.answer("Оплата уже учтена ✅", show_alert=True)
        return

    human = {
        "created": "Оплата ещё не поступила",
        "processing": "Платёж в обработке — проверьте через минуту",
        "expired": "Счёт истёк. Создайте новый в 🚀 «Подписка»",
        "canceled": "Платёж отменён. Создайте новый в 🚀 «Подписка»",
    }.get(status, f"Статус: {status}")
    await cb.answer(human, show_alert=True)


@router.callback_query(F.data == "sub:cancel")
async def cb_cancel(cb: CallbackQuery) -> None:
    msg = cb.message
    if not msg:
        return
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Отменено")


@router.callback_query(F.data.startswith("sub:"))
async def cb_sub_fallback(cb: CallbackQuery) -> None:
    # страховка от неизвестных sub:* колбэков
    if cb.message:
        tg_id = cb.from_user.id
        user = await db.get_user(tg_id)
        trial_available = bool(config.TRIAL_DAYS) and user and not user["trial_used"] and \
            not await db.active_sub(tg_id)
        await cb.message.answer(
            texts.subscription_menu(await status_line(tg_id)),
            reply_markup=sub_menu(bool(await db.active_sub(tg_id)), trial_available),
        )
    await cb.answer()
