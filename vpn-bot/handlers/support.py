"""Поддержка: тикеты через FSM, пересылка админам, ответы."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import texts
from keyboards import cancelled_kb, support_stop_kb
from services import db

log = logging.getLogger(__name__)
router = Router(name="support")


class SupportFSM(StatesGroup):
    waiting_message = State()


MENU_TEXTS = {"🚀 Подписка", "👤 Профиль", "👥 Реферальная программа", "🛟 Поддержка", "❓ Инструкция"}


@router.message(F.text == "🛟 Поддержка", F.from_user)
async def enter_support(message: Message, state: FSMContext) -> None:
    await state.set_state(SupportFSM.waiting_message)
    kb = support_stop_kb() if config.ADMIN_IDS else None
    await message.answer(texts.SUPPORT_ASK, reply_markup=kb)


@router.callback_query(F.data == "support:stop")
async def stop_support(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if cb.message:
        await cb.message.answer("Режим поддержки выключен. Вернуться: кнопки меню.", reply_markup=cancelled_kb())
    await cb.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Готово. Главное меню — кнопками.", reply_markup=cancelled_kb())


@router.message(StateFilter(SupportFSM.waiting_message), F.from_user,
                (F.text | F.photo | F.document) & ~F.text.in_(MENU_TEXTS))
async def support_message(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    tg_id = message.from_user.id
    user = await db.get_user(tg_id)
    if user and user["banned"]:
        await state.clear()
        return

    ticket = await db.last_open_ticket(tg_id)
    if not ticket:
        ticket_id = await db.create_ticket(tg_id)
    else:
        ticket_id = ticket["id"]

    name = html.escape(message.from_user.first_name or "—")
    caption = texts.SUPPORT_NEW_FROM_USER.format(
        uid=tg_id, name=name, ticket=ticket_id,
        text=html.escape(message.text or "[вложение]"),
    )
    await db.add_ticket_message(ticket_id, False, message.text or "[вложение]")

    delivered = False
    for admin_id in config.ADMIN_IDS:
        try:
            if message.text:
                sent = await message.bot.send_message(admin_id, caption)
            else:
                sent = await message.bot.copy_message(admin_id, tg_id, message.message_id,
                                                      caption=f"🎫 Тикет №{ticket_id} от ID {tg_id}")
            await db.save_admin_forward(sent.message_id, tg_id, ticket_id)
            delivered = True
        except Exception as e:  # noqa: BLE001
            log.warning("Не доставили тикет админу %s: %s", admin_id, e)

    if delivered:
        await message.answer(texts.SUPPORT_SENT.format(ticket=ticket_id))
    else:
        await message.answer(
            "⚠️ Поддержка не настроена. Напишите нам напрямую: "
            + (config.SUPPORT_URL or "ссылка появится позже")
        )
        await state.clear()
        return
