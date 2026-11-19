"""Бизнес-логика: выдача/продление подписок на нодах H1/VLESS, активация платежей, ключи и QR."""
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot
from aiogram.types import BufferedInputFile

import config
import texts
from db import Database
from h1cloud import H1CloudClient, H1Cluster, H1CloudError
from rollypay import RollyPay

log = logging.getLogger(__name__)


def _build_cluster() -> H1Cluster:
    nodes = [
        H1CloudClient(
            name=n["name"], base_url=n["api_url"], token=n["token"],
            sub_url_template=n["sub_url"],
            verify_ssl=config.H1_VERIFY_SSL, timeout=config.H1_REQUEST_TIMEOUT,
        )
        for n in config.H1_NODES
    ]
    return H1Cluster(nodes)


# Объекты создаются при импорте модуля: все, кто делает `from services import db`,
# получают один и тот же экземпляр (пересоздание через init() ломало ссылки).
db: Database = Database(config.DB_PATH)
h1: H1Cluster = _build_cluster()
rollypay: RollyPay = RollyPay(config.RP_API_KEY, config.RP_SIGNING_SECRET,
                              config.RP_BASE_URL, config.RP_TEST_MODE)


async def init(db_: Optional[Database] = None, h1_: Optional[H1Cluster] = None,
               rollypay_: Optional[RollyPay] = None) -> None:
    """Подменяет объекты (для тестов) и инициализирует БД. В проде вызывается без аргументов."""
    global db, h1, rollypay
    if db_ is not None:
        db = db_
    if h1_ is not None:
        h1 = h1_
    if rollypay_ is not None:
        rollypay = rollypay_
    await db.init()


# ---------- вспомогательное ----------
def plan_title(plan_id: str) -> str:
    if plan_id == "trial":
        return f"Пробный период ({config.TRIAL_DAYS} дн.)"
    plan = config.get_plan(plan_id)
    return plan["title"] if plan else plan_id


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def vpn_name(tg_id: int) -> str:
    return f"tg{tg_id}"


def sub_links(sub: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """links_json -> {страна: ссылка}."""
    if not sub:
        return {}
    raw = sub.get("links_json") or "{}"
    try:
        data = json.loads(raw)
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except Exception:  # noqa: BLE001
        return {}


def make_qr_png(text: str) -> Optional[bytes]:
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
        qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=8, border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        log.warning("QR не сгенерирован: %s", e)
        return None


async def _refresh_links_from_nodes(tg_id: int, sub: Dict[str, Any]) -> Dict[str, str]:
    """Живые ссылки с нод; при недоступности нод — сохранённые."""
    try:
        live = await h1.refresh_links(vpn_name(tg_id))
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось обновить ссылки с нод: %s", e)
        live = {}
    if live:
        if live != sub_links(sub):
            await db.set_sub_links(sub["id"], live)
        return live
    return sub_links(sub)


# ---------- выдача подписки ----------
async def grant_plan(bot: Bot, tg_id: int, plan_id: str, days: int, traffic_gb: int,
                     devices: int = 0, notify: bool = True, reason: str = "") -> Optional[Dict[str, Any]]:
    """Начисляет подписку (новую или продление) и провижинит пользователя на всех нодах."""
    user = await db.get_user(tg_id)
    if not user:
        log.error("grant_plan: пользователь %s не найден", tg_id)
        return None

    now = datetime.now(timezone.utc)
    sub = await db.active_sub(tg_id)
    base = max(now, parse_iso(sub["expires_at"])) if sub else now
    expires = base + timedelta(days=days)
    pending_days = await db.take_pending_ref_days(tg_id)
    if pending_days:
        expires += timedelta(days=pending_days)
    expires_iso = expires.isoformat(timespec="seconds")

    links: Dict[str, str] = {}
    if h1.configured:
        name = vpn_name(tg_id)
        limit_gb = traffic_gb if traffic_gb else 0
        try:
            if sub:
                links = await h1.extend(name, days)
                if not links:
                    # клиента нет на нодах (например, БД пережила переезд) — создаём заново
                    links = await h1.provision(name, days, limit_gb, devices)
            else:
                links = await h1.provision(name, days, limit_gb, devices)
        except H1CloudError as e:
            log.error("H1: провижининг %s не удался: %s", tg_id, e)
        except Exception as e:  # noqa: BLE001
            log.exception("H1: непредвиденная ошибка провижининга %s: %s", tg_id, e)
    else:
        log.warning("Ноды H1 не настроены (H1_NODES) — подписка %s записана только в БД", tg_id)

    if sub:
        await db.extend_sub(sub["id"], plan_id, expires_iso)
        sub_id = sub["id"]
        is_new = False
    else:
        sub_id = await db.create_sub(tg_id, plan_id, expires_iso, vpn_name(tg_id), "{}")
        is_new = True
    if links:
        await db.set_sub_links(sub_id, links)

    if notify:
        head = texts.payment_activated_head(is_new)
        if links:
            await send_keys_message(bot, tg_id, title=plan_title(plan_id), expires=texts.fmt_date(expires_iso),
                                    links=links, head=head)
        else:
            await bot.send_message(
                tg_id,
                f"{head}\n\nТариф: <b>{plan_title(plan_id)}</b>\nДействует до: <b>{texts.fmt_date(expires_iso)}</b>\n\n"
                "⚠️ VPN-сервера временно недоступны — ключи пришлём автоматически, как только связь восстановится. "
                "Срок подписки уже зафиксирован.",
            )
            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚠️ Оплата оформлена, но ноды H1 недоступны. Проверьте H1_NODES "
                        f"(пользователь ID <code>{tg_id}</code>, {reason}).",
                    )
                except Exception:  # noqa: BLE001
                    pass
    return await db.active_sub(tg_id)


async def grant_trial(bot: Bot, tg_id: int) -> bool:
    user = await db.get_user(tg_id)
    if not user or user["trial_used"]:
        return False
    if await db.active_sub(tg_id):
        return False
    if not config.TRIAL_DAYS:
        return False
    await db.run("UPDATE users SET trial_used=1 WHERE telegram_id=?", (tg_id,))
    await grant_plan(bot, tg_id, "trial", config.TRIAL_DAYS, config.TRIAL_TRAFFIC_GB,
                     devices=config.TRIAL_DEVICES, notify=True, reason="trial")
    return True


# ---------- активация платежей ----------
async def activate_payment(bot: Bot, payment_db_id: int) -> bool:
    pay = await db.get_payment(payment_db_id)
    if not pay or pay["activated"] or pay["status"] != "paid":
        return False
    plan = config.get_plan(pay["plan_id"])
    if not plan:
        log.error("activate_payment: неизвестный план %s", pay["plan_id"])
        return False

    first_paid = await db.count_paid_by_user(pay["user_id"]) == 0
    await db.mark_payment_activated(payment_db_id)
    await grant_plan(bot, pay["user_id"], plan["id"], plan["days"],
                     plan["traffic_gb"], plan.get("devices", 0))

    if first_paid:
        await _grant_referral_bonus_for_payment(bot, pay["user_id"])

    log.info("Платёж #%s активирован (user=%s, план=%s)", payment_db_id, pay["user_id"], plan["id"])
    return True


async def _grant_referral_bonus_for_payment(bot: Bot, tg_id: int) -> None:
    user = await db.get_user(tg_id)
    if not user or not user["referrer_id"]:
        return
    referrer_id = user["referrer_id"]

    if config.REF_BONUS_REFEREE_DAYS:
        await _add_days_and_notify(bot, tg_id, config.REF_BONUS_REFEREE_DAYS, texts.REF_BONUS_REFEREE)

    days = config.REF_BONUS_REFERRER_DAYS
    if not days:
        return
    sub = await db.active_sub(referrer_id)
    if sub:
        expires = max(datetime.now(timezone.utc), parse_iso(sub["expires_at"])) + timedelta(days=days)
        await db.extend_sub(sub["id"], sub["plan_id"], expires.isoformat(timespec="seconds"))
        if h1.configured:
            try:
                await h1.extend(vpn_name(referrer_id), days)
            except Exception as e:  # noqa: BLE001
                log.error("H1: реферальный бонус не применён к %s: %s", referrer_id, e)
        try:
            await bot.send_message(
                referrer_id,
                texts.REF_BONUS_GRANTED_REFERRER.format(
                    days=days, expires=texts.fmt_date(expires.isoformat(timespec="seconds"))),
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        await db.add_pending_ref_days(referrer_id, days)
        try:
            await bot.send_message(referrer_id, texts.REF_BONUS_PENDING_REFERRER.format(days=days))
        except Exception:  # noqa: BLE001
            pass


async def _add_days_and_notify(bot: Bot, tg_id: int, days: int, template: str) -> None:
    sub = await db.active_sub(tg_id)
    if sub:
        expires = max(datetime.now(timezone.utc), parse_iso(sub["expires_at"])) + timedelta(days=days)
        await db.extend_sub(sub["id"], sub["plan_id"], expires.isoformat(timespec="seconds"))
        if h1.configured:
            try:
                await h1.extend(vpn_name(tg_id), days)
            except Exception as e:  # noqa: BLE001
                log.error("H1: бонусные дни не применены к %s: %s", tg_id, e)
    else:
        await db.add_pending_ref_days(tg_id, days)
        return
    try:
        await bot.send_message(tg_id, template.format(days=days))
    except Exception:  # noqa: BLE001
        pass


# ---------- сообщения с ключами ----------
async def send_keys_message(bot: Bot, chat_id: int, title: str, expires: str,
                            links: Dict[str, str], head: str) -> None:
    """Обзорный список стран + кнопки «страна → ссылка и QR»."""
    try:
        lines = [head, "", f"Тариф: <b>{title}</b>", f"Действует до: <b>{expires}</b>", "",
                 "🌐 <b>Доступные страны</b> — нажмите кнопку ниже, и бот пришлёт ссылку и QR:"]
        for i, (country, link) in enumerate(links.items(), start=1):
            lines.append(f"{i}. <b>{country}</b>: <code>{link}</code>")
        lines.append("")
        lines.append("Ссылки открываются в Happ, v2rayNG, Streisand, V2Box, Hiddify. "
                     "Инструкция — кнопка «❓ Инструкция» в меню.")
        from keyboards import keys_country_kb
        await bot.send_message(chat_id, "\n".join(lines), reply_markup=keys_country_kb(links))
    except Exception as e:  # noqa: BLE001
        log.error("Не удалось отправить ключи %s: %s", chat_id, e)


async def send_country_key(bot: Bot, chat_id: int, sub: Dict[str, Any], index: int) -> bool:
    """Ссылка и QR конкретной страны."""
    links = await _refresh_links_from_nodes(chat_id, sub)
    if not links:
        await bot.send_message(chat_id, "⚠️ Ключи пока недоступны — сервера подключаются. "
                                        "Попробуйте через пару минут или напишите в 🛟 Поддержку.")
        return True
    items = list(links.items())
    if not (0 <= index < len(items)):
        index = 0
    country, link = items[index]
    qr = make_qr_png(link)
    caption = (
        f"🌐 <b>{country}</b> — ваш VPN-ключ\n\n"
        f"Действует до: <b>{texts.fmt_date(sub['expires_at'])}</b>\n\n"
        f"Скопируйте ссылку подписки:\n<code>{link}</code>\n\n"
        "📷 Отсканируйте QR или вставьте ссылку в Happ / v2rayNG / Streisand."
    )
    if qr:
        await bot.send_photo(chat_id, BufferedInputFile(qr, f"{country}.png"), caption=caption)
    else:
        await bot.send_message(chat_id, caption)
    return True


async def send_key_now(bot: Bot, chat_id: int) -> bool:
    """Кнопка «Мой VPN-ключ»: обзор всех стран."""
    sub = await db.active_sub(chat_id)
    if not sub:
        return False
    links = await _refresh_links_from_nodes(chat_id, sub)
    if not links:
        await bot.send_message(chat_id, "⚠️ Ключи пока недоступны — сервера подключаются. "
                                        "Попробуйте через пару минут или напишите в 🛟 Поддержку.")
        return True
    await send_keys_message(
        bot, chat_id,
        title=plan_title(sub["plan_id"]),
        expires=texts.fmt_date(sub["expires_at"]),
        links=links,
        head="🔑 <b>Ваши VPN-ключи</b>",
    )
    return True


# ---------- статус для меню ----------
async def status_line(tg_id: int) -> str:
    sub = await db.active_sub(tg_id)
    if sub:
        return (
            "Статус: 🟢 <b>активна</b>\n"
            f"Тариф: <b>{plan_title(sub['plan_id'])}</b>\n"
            f"Действует до: <b>{texts.fmt_date(sub['expires_at'])}</b>\n"
            "Продление добавляет срок к текущей дате окончания."
        )
    if await db.any_sub_ever(tg_id):
        return "Статус: 🔴 <b>подписка истекла</b>"
    return "Статус: 🔴 <b>нет активной подписки</b>"


# ---------- админ ----------
async def ban_everywhere(tg_id: int) -> None:
    if h1.configured:
        try:
            await h1.ban(vpn_name(tg_id))
        except Exception as e:  # noqa: BLE001
            log.warning("H1 ban %s: %s", tg_id, e)


async def unban_everywhere(tg_id: int) -> None:
    if h1.configured:
        try:
            await h1.unban(vpn_name(tg_id))
        except Exception as e:  # noqa: BLE001
            log.warning("H1 unban %s: %s", tg_id, e)


async def nodes_health() -> List[Tuple[str, bool]]:
    out: List[Tuple[str, bool]] = []
    for node in h1.nodes:
        if not node.configured:
            out.append((node.name, False))
            continue
        try:
            await node.health()
            out.append((node.name, True))
        except Exception:  # noqa: BLE001
            out.append((node.name, False))
    return out
