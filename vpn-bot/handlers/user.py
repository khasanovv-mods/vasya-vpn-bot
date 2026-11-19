"""Пользовательские хендлеры: /start, меню."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import texts
from db import Database
from keyboards import main_menu, profile_kb, sub_menu
from services import db, status_line

log = logging.getLogger(__name__)
router = Router(name="user")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext) -> None:
    if not message.from_user:
        return
    tg = message.from_user
    user = await db.get_or_create_user(
        tg.id, tg.username or "", (tg.first_name or "") + (" " + tg.last_name if tg.last_name else "")
    )
    await state.clear()

    # реферальный переход
    args = (command.args or "").strip()
    if args.startswith("ref") and args[3:].isdigit():
        referrer_id = int(args[3:])
        if referrer_id != tg.id and await db.get_user(referrer_id):
            fresh = user["referrer_id"] is None
            if fresh and await db.set_referrer(tg.id, referrer_id):
                try:
                    name = tg.first_name or "друг"
                    await message.bot.send_message(
                        referrer_id, texts.REF_JOINED.format(name=html.escape(name))
                    )
                except Exception:  # noqa: BLE001
                    pass
                # мгновенный бонус за регистрацию (если настроен)
                if config.REF_BONUS_IMMEDIATE_DAYS:
                    from services import _add_days_and_notify
                    await _add_days_and_notify(
                        message.bot, referrer_id, config.REF_BONUS_IMMEDIATE_DAYS,
                        texts.REF_BONUS_GRANTED_REFERRER,
                    )

    if user["banned"]:
        await message.answer("⛔️ Доступ к боту ограничен. Напишите в 🛟 Поддержку, если это ошибка.")
        return

    await message.answer(texts.welcome(config.BRAND_NAME), reply_markup=main_menu())


async def _guard(message: Message) -> bool:
    if not message.from_user:
        return False
    user = await db.get_user(message.from_user.id)
    if user and user["banned"]:
        return False
    return True


@router.message(F.text == "🚀 Подписка", F.from_user)
async def show_subscription(message: Message, state: FSMContext) -> None:
    if not await _guard(message):
        return
    await state.clear()
    tg_id = message.from_user.id
    user = await db.get_user(tg_id)
    trial_available = bool(config.TRIAL_DAYS) and user and not user["trial_used"] and \
        not await db.active_sub(tg_id)
    await message.answer(
        texts.subscription_menu(await status_line(tg_id)),
        reply_markup=sub_menu(bool(await db.active_sub(tg_id)), trial_available),
    )


@router.message(F.text == "👤 Профиль", F.from_user)
async def show_profile(message: Message, state: FSMContext) -> None:
    if not await _guard(message):
        return
    await state.clear()
    tg = message.from_user
    user = await db.get_user(tg.id)
    if not user:
        user = await db.get_or_create_user(tg.id, tg.username or "", tg.first_name or "")
    sub = await db.active_sub(tg.id)
    cur = await db.db.execute(
        "SELECT COUNT(*) c FROM users WHERE referrer_id=?", (tg.id,)
    )
    row = await cur.fetchone()
    refs_count = row["c"] if row else 0
    text = texts.PROFILE.format(
        tg_id=tg.id,
        name=html.escape(user["full_name"] or "—"),
        uname=("@" + user["username"]) if user["username"] else "—",
        sub_block=texts.profile_sub(bool(sub), texts.fmt_date(sub["expires_at"]) if sub else "",
                                    sub["plan_id"] if sub else ""),
        refs=refs_count,
    )
    await message.answer(text, reply_markup=profile_kb())


@router.message(F.text == "👥 Реферальная программа", F.from_user)
async def show_referral(message: Message, state: FSMContext) -> None:
    if not await _guard(message):
        return
    await state.clear()
    tg_id = message.from_user.id
    bot_username = (await message.bot.me()).username
    link = f"https://t.me/{bot_username}?start=ref{tg_id}"
    cur = await db.db.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (tg_id,))
    row = await cur.fetchone()
    count = row["c"] if row else 0
    user = await db.get_user(tg_id)
    pending = user["pending_ref_days"] if user else 0
    earned = count * config.REF_BONUS_REFERRER_DAYS  # максимум за всех приглашённых
    await message.answer(
        texts.REFERRAL.format(
            ref_days=config.REF_BONUS_REFERRER_DAYS,
            friend_days=config.REF_BONUS_REFEREE_DAYS,
            link=link,
            count=count,
            earned=earned,
            pending=texts.REF_PENDING.format(days=pending) if pending else "",
        )
    )


@router.message(F.text == "❓ Инструкция", F.from_user)
async def show_instruction(message: Message, state: FSMContext) -> None:
    if not await _guard(message):
        return
    await state.clear()
    await message.answer(texts.INSTRUCTION)


# ---------- колбэки ----------
@router.callback_query(F.data == "sub:key")
async def cb_my_key(cb: CallbackQuery) -> None:
    from services import send_key_now
    if not cb.from_user:
        return
    ok = await send_key_now(cb.bot, cb.from_user.id)
    if not ok:
        await cb.message.answer("У вас нет активной подписки. Оформите её в 🚀 «Подписка».")
    await cb.answer()


@router.callback_query(F.data == "sub:menu")
async def cb_sub_menu(cb: CallbackQuery) -> None:
    msg = cb.message
    if not msg or not cb.from_user:
        return
    tg_id = cb.from_user.id
    user = await db.get_user(tg_id)
    trial_available = bool(config.TRIAL_DAYS) and user and not user["trial_used"] and \
        not await db.active_sub(tg_id)
    has_active = bool(await db.active_sub(tg_id))
    try:
        await msg.edit_text(
            texts.subscription_menu(await status_line(tg_id)),
            reply_markup=sub_menu(has_active, trial_available),
        )
    except Exception:  # noqa: BLE001
        await msg.answer(texts.subscription_menu(await status_line(tg_id)),
                         reply_markup=sub_menu(has_active, trial_available))
    await cb.answer()
