"""Клавиатуры бота."""
from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import PLANS, TRIAL_DAYS


def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="🚀 Подписка"), KeyboardButton(text="👤 Профиль"))
    kb.row(KeyboardButton(text="👥 Реферальная программа"))
    kb.row(KeyboardButton(text="🛟 Поддержка"), KeyboardButton(text="❓ Инструкция"))
    return kb.as_markup(resize_keyboard=True)


def sub_menu(has_active: bool, trial_available: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if trial_available:
        kb.button(text=f"🎁 Пробный период ({TRIAL_DAYS} дня)", callback_data="sub:trial")
    for plan in PLANS:
        kb.button(text=f"{plan['title']} — {plan['price']} ₽", callback_data=f"sub:buy:{plan['id']}")
    if has_active:
        kb.button(text="🔑 Мой VPN-ключ", callback_data="sub:key")
    kb.button(text="🔄 Обновить", callback_data="sub:menu")
    kb.adjust(1)
    return kb.as_markup()


def payment_kb(pay_url: str, payment_db_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=pay_url)
    kb.button(text="✅ Я оплатил — проверить", callback_data=f"sub:check:{payment_db_id}")
    kb.button(text="❌ Отменить", callback_data="sub:cancel")
    kb.adjust(1)
    return kb.as_markup()


def keys_country_kb(links: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, country in enumerate(links.keys()):
        kb.button(text=f"🌐 {country} — ссылка и QR", callback_data=f"keyc:{i}")
    kb.button(text="🚀 Подписка", callback_data="sub:menu")
    kb.adjust(1)
    return kb.as_markup()


def my_key_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="sub:key")
    kb.button(text="🚀 Продлить подписку", callback_data="sub:menu")
    kb.adjust(1)
    return kb.as_markup()


def profile_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Мой VPN-ключ", callback_data="sub:key")
    kb.button(text="🚀 Подписка", callback_data="sub:menu")
    kb.adjust(1)
    return kb.as_markup()


def support_stop_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔚 Выйти из режима поддержки", callback_data="support:stop")
    return kb.as_markup()


def cancelled_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Подписка", callback_data="sub:menu")
    return kb.as_markup()
