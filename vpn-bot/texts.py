"""Все тексты бота (HTML)."""
from typing import Optional

from zoneinfo import ZoneInfo

from config import BRAND_NAME, TRIAL_DAYS, TRIAL_TRAFFIC_GB, REF_BONUS_REFERRER_DAYS, REF_BONUS_REFEREE_DAYS

MSK = ZoneInfo("Europe/Moscow")


def fmt_date(iso: Optional[str]) -> str:
    """ISO-дата (UTC) -> '20 февраля 2027, 14:30 МСК'."""
    if not iso:
        return "—"
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(MSK)
        months = ["января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        return f"{local.day} {months[local.month - 1]} {local.year}, {local:%H:%M} МСК"
    except Exception:
        return iso


def fmt_gb(bytes_value: Optional[int]) -> str:
    if bytes_value is None or bytes_value == 0:
        return "безлимит"
    gb = bytes_value / (1024 ** 3)
    return f"{gb:.1f} ГБ" if gb < 10 else f"{gb:.0f} ГБ"


def welcome(brand: str = BRAND_NAME) -> str:
    return (
        f"👋 <b>Добро пожаловать в {brand}!</b>\n\n"
        "🚀 Быстрый и стабильный VPN на протоколе VLESS — работает в России, "
        "на iPhone, Android, Windows и Mac.\n\n"
        "⬇️ <b>Главное меню:</b>\n"
        "🚀 Подписка — тарифы и подключение\n"
        "👤 Профиль — срок и статус вашей подписки\n"
        "👥 Реферальная программа — бесплатный VPN за приглашения\n"
        "🛟 Поддержка — поможем с любым вопросом\n"
        "❓ Инструкция — как установить и подключиться\n\n"
        f"🎁 <b>Пробный период:</b> {TRIAL_DAYS} дня{'й' if TRIAL_DAYS % 10 >= 5 or TRIAL_DAYS % 100 in (11,12,13,14) else ''} "
        f"({TRIAL_TRAFFIC_GB} ГБ) — есть кнопка в разделе «Подписка»."
    )


def subscription_menu(
    status_line: str,
) -> str:
    return f"🚀 <b>Подписка</b>\n\n{status_line}\n\nВыберите тариф:"


def plan_line(plan: dict) -> str:
    days = plan["days"]
    if days % 365 == 0:
        term = f"{days // 365} год" if days // 365 == 1 else f"{days // 365} года"
    elif days % 30 == 0:
        m = days // 30
        term = f"{m} месяц" if m == 1 else (f"{m} месяца" if m in (2, 3, 4) else f"{m} месяцев")
    else:
        term = f"{days} дней"
    traffic = "безлимитный трафик" if plan["traffic_gb"] == 0 else f"{plan['traffic_gb']} ГБ трафика"
    return f"• <b>{plan['title']}</b> — {plan['price']} ₽ ({term}, {traffic})"


def payment_created(plan: dict, pay_url: str, order_id: str, test: bool) -> str:
    lines = [
        "🧾 <b>Счёт создан</b>\n\n",
        f"Тариф: <b>{plan['title']}</b>\n",
        f"Сумма: <b>{plan['price']} ₽</b>\n",
        f"Номер заказа: <code>{order_id}</code>\n\n",
        "1️⃣ Нажмите кнопку ниже и оплатите (СБП, карта или крипта — на странице оплаты)\n",
        "2️⃣ Вернитесь в бота и нажмите «✅ Я оплатил — проверить»\n\n",
        "Оплата засчитывается автоматически — ключ придёт в бота.",
    ]
    if test:
        lines.append("\n⚠️ <i>Тестовый режим RollyPay — деньги не списываются.</i>")
    return "".join(lines)


def payment_activated_head(is_new: bool) -> str:
    return ("🎉 <b>Оплата получена — VPN активирован!</b>"
            if is_new else "🎉 <b>Оплата получена — подписка продлена!</b>")


def payment_activated(plan: dict, expires: str, is_new: bool) -> str:
    head = "🎉 <b>Оплата получена — VPN активирован!</b>" if is_new else \
           "🎉 <b>Оплата получена — подписка продлена!</b>"
    return (
        f"{head}\n\n"
        f"Тариф: <b>{plan['title']}</b>\n"
        f"Действует до: <b>{expires}</b>\n\n"
        "🔗 Ваш ключ подключению ниже ⬇️ (кнопка «Мой VPN-ключ» в профиле)\n"
        "Если кнопка не пришла — откройте 👤 <b>Профиль</b> → «🔑 Мой VPN-ключ»."
    )


def key_message(link: str, expires: str, traffic_used: str, traffic_total: str) -> str:
    return (
        "🔑 <b>Ваш VPN-ключ</b>\n\n"
        f"Действует до: <b>{expires}</b>\n"
        f"Трафик: <b>{traffic_used}</b> из {traffic_total}\n\n"
        "Скопируйте ссылку ниже и вставьте в приложение (Happ, v2rayNG, Streisand, V2Box, Hiddify):\n"
        f"<code>{link}</code>\n\n"
        "📷 Или отсканируйте QR-код со скриншота ниже.\n"
        "Подробная инструкция — кнопка «❓ Инструкция» в меню."
    )


PROFILE = (
    "👤 <b>Ваш профиль</b>\n\n"
    "ID: <code>{tg_id}</code>\n"
    "Имя: {name}\n"
    "Username: {uname}\n\n"
    "{sub_block}\n"
    "Приглашено друзей: <b>{refs}</b>\n"
)


def profile_sub(active: bool, expires: str, plan_title: str) -> str:
    if active:
        return f"Статус: 🟢 <b>активна</b>\nТариф: <b>{plan_title}</b>\nДействует до: <b>{expires}</b>\n"
    return "Статус: 🔴 <b>нет активной подписки</b>\n"


REFERRAL = (
    "👥 <b>Реферальная программа</b>\n\n"
    "Приглашайте друзей и получайте <b>{ref_days} дней</b> бесплатного VPN за первый оплаченный заказ "
    "каждого приглашённого! Приглашённый друг тоже получит <b>{friend_days} дней</b> в подарок.\n\n"
    "Ваша ссылка (перешлите другу):\n<code>{link}</code>\n\n"
    "📊 Ваша статистика:\n"
    "• Приглашено: <b>{count}</b>\n"
    "• Заработано дней: <b>{earned}</b>{pending}\n"
)

REF_PENDING = "\n• Ожидает активации: <b>{days}</b> (начислим после оплаты)\n"

REF_NO_BONUS = (
    "👥 <b>Реферальная программа</b> пока не настроена администратором."
)

REF_JOINED = "🎁 Друг <b>{name}</b> присоединился по вашей ссылке!"

REF_BONUS_GRANTED_REFERRER = (
    "🎉 <b>Реферальный бонус!</b>\n\n"
    "По вашему приглашению оформлена подписка — вам начислено <b>+{days} дней</b>.\n"
    "Новый срок: <b>{expires}</b>"
)

REF_BONUS_PENDING_REFERRER = (
    "🎉 <b>Реферальный бонус!</b>\n\n"
    "По вашему приглашению оформлена подписка — вам начислено <b>+{days} дней</b>.\n"
    "У вас пока нет активной подписки — дни применятся к следующей покупке."
)

REF_BONUS_REFEREE = (
    "🎁 <b>Бонус за приглашение!</b>\n\n"
    "Вам начислено <b>+{days} дней</b> по реф-ссылке — они добавлены к подписке."
)

TRIAL_OK = (
    "🎁 <b>Пробный период активирован!</b>\n\n"
    f"Срок: <b>{TRIAL_DAYS} дня</b>\n"
    f"Лимит трафика: <b>{TRIAL_TRAFFIC_GB} ГБ</b>\n\n"
    "Ваш ключ ниже ⬇️"
)

TRIAL_UNAVAILABLE = (
    "⚠️ Пробный период уже был использован или у вас есть подписка.\n"
    "Оформите тариф в разделе 🚀 «Подписка»."
)


def expired_notice(title: str, expires: str) -> str:
    return (
        "⏰ <b>Подписка истекла</b>\n\n"
        f"Тариф: <b>{title}</b> (до {expires})\n\n"
        "Продлите в разделе 🚀 «Подписка», чтобы VPN снова заработал."
    )


def expiring_notice(title: str, expires: str, days_left: int) -> str:
    return (
        f"🔔 <b>Подписка скоро истечёт</b> (осталось {days_left} дн.)\n\n"
        f"Тариф: <b>{title}</b>, действует до <b>{expires}</b>.\n\n"
        "Продлите заранее в разделе 🚀 «Подписка» — VPN не прервётся."
    )


INSTRUCTION = (
    "📖 <b>Как подключить VPN</b>\n\n"
    "<b>1. Установите приложение:</b>\n"
    "🤖 Android — <b>Happ</b> или <b>v2rayNG</b>\n"
    "🍎 iPhone/iPad — <b>Happ</b> или <b>Streisand</b>\n"
    "💻 Windows — <b>Happ</b> или <b>Hiddify</b>\n"
    "🖥 macOS — <b>Streisand</b> или <b>Hiddify</b>\n\n"
    "<b>2. Получите ключ</b>\n"
    "Откройте 👤 Профиль → «🔑 Мой VPN-ключ» и скопируйте ссылку подписки (или отсканируйте QR).\n\n"
    "<b>3. Добавьте ключ в приложение:</b>\n"
    "• Happ: «+» → вставить ссылку подписки → «Импорт»\n"
    "• v2rayNG: «+» → «Импорт из буфера обмена»\n"
    "• Streisand: «+» → «Использовать подписку»\n"
    "• Hiddify: «+» → «Импорт из буфера»\n\n"
    "<b>4. Нажмите кнопку подключения</b> в приложении — готово, всё расшифровано через VLESS.\n\n"
    "❗️ Выберите ближайшую по пингу страну в приложении, если доступно несколько локаций.\n"
    "Если что-то не работает — напишите в 🛟 «Поддержка», поможем за пару минут."
)

SUPPORT_ASK = (
    "🛟 <b>Поддержка</b>\n\n"
    "Опишите вашу проблему одним сообщением — оно уйдёт админам, "
    "и вам ответят здесь же в боте.\n\n"
    "Для отмены: /cancel"
)

SUPPORT_SENT = (
    "✅ Сообщение отправлено! Тикет <b>№{ticket}</b> создан.\n"
    "Ответ придёт сюда в этот чат. Для нового сообщения просто напишите ещё раз (режим поддержки активен), /cancel — выйти."
)

SUPPORT_NEW_FROM_USER = (
    "🎫 <b>Новое обращение</b>\n\n"
    "От: <a href=\"tg://user?id={uid}\">{name}</a> (ID <code>{uid}</code>)\n"
    "Тикет: <b>№{ticket}</b>\n\n"
    "{text}\n\n"
    "<i>Ответить: ответьте (reply) на это сообщение, либо /reply {ticket} текст</i>"
)

SUPPORT_REPLY_TO_USER = (
    "🛟 <b>Ответ поддержки</b> (тикет №{ticket}):\n\n{text}"
)

SUPPORT_NO_ADMINS = (
    "🛟 Поддержка временно недоступна. Напишите нам напрямую: ссылка настроится позже."
)

SUPPORT_USER_FOLLOWUP = (
    "🎫 Сообщение добавлено в тикет <b>№{ticket}</b>."
)

# ---------- админ ----------
ADMIN_MENU = (
    "🛠 <b>Панель администратора</b>\n\n"
    "/stats — статистика\n"
    "/nodes — состояние VPN-нод\n"
    "/sync &lt;id&gt; — доздать ключи по активной подписке\n"
    "/find &lt;id&gt; — информация о пользователе\n"
    "/grant &lt;id&gt; &lt;дней&gt; [гб] — выдать подписку\n"
    "/ban &lt;id&gt; / /unban &lt;id&gt; — блокировка\n"
    "/broadcast &lt;текст&gt; — рассылка всем\n"
    "/reply &lt;тикет&gt; &lt;текст&gt; — ответ в тикет\n"
    "/close &lt;тикет&gt; — закрыть тикет\n\n"
    "Ответ на пересланное сообщение пользователя = ответ ему."
)


def stats(total: int, new7: int, active_subs: int, paid: int, revenue: float, pending: int) -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: <b>{total}</b> (новых за 7 дней: <b>{new7}</b>)\n"
        f"Активных подписок: <b>{active_subs}</b>\n"
        f"Оплат: <b>{paid}</b> на сумму <b>{revenue:.0f} ₽</b>\n"
        f"Ожидают оплаты: <b>{pending}</b>"
    )


def find_user(u: dict, sub: Optional[dict], paid: int) -> str:
    sub_txt = (
        f"Подписка: 🟢 активна, до {fmt_date(sub['expires_at'])} (тариф {sub['plan_id']})"
        if sub else "Подписка: 🔴 нет активной"
    )
    return (
        f"👤 <a href=\"tg://user?id={u['telegram_id']}\">{u['full_name'] or ''}</a>\n"
        f"ID: <code>{u['telegram_id']}</code>\n"
        f"Username: @{u['username'] or '—'}\n"
        f"Регистрация: {fmt_date(u['created_at'])}\n"
        f"Реферер: <code>{u['referrer_id'] or '—'}</code>\n"
        f"Бан: {'да' if u['banned'] else 'нет'}\n"
        f"Пробник использован: {'да' if u['trial_used'] else 'нет'}\n"
        f"Оплат: {paid}\n{sub_txt}"
    )

BROADCAST_START = "📣 Отправьте сообщение для рассылки (или /cancel)."
BROADCAST_PROGRESS = "📣 Рассылка: отправлено {ok}, ошибок {fail}…"
BROADCAST_DONE = "📣 Рассылка завершена: отправлено {ok}, ошибок {fail}."


def broadcast_sent_to_user(brand: str = BRAND_NAME) -> str:
    return f"📣 <b>{brand}</b>"
