"""Админ-панель: статистика, поиск, выдача подписки, бан, рассылка, ответы в тикеты."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import config
import texts
from services import ban_everywhere, db, grant_plan, unban_everywhere

log = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))


def _parse_ids(arg: str):
    arg = arg.strip().lstrip("#")
    try:
        return int(arg)
    except ValueError:
        return None


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(texts.ADMIN_MENU)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    pending = await db._all("SELECT COUNT(*) c FROM payments WHERE status IN ('created','processing')")
    await message.answer(texts.stats(
        total=await db.count_users(),
        new7=await db.count_new_users(7),
        active_subs=await db.count_active_subs(),
        paid=(await db.count_paid_payments()),
        revenue=await db.revenue(),
        pending=pending[0]["c"] if pending else 0,
    ))


@router.message(Command("nodes"))
async def cmd_nodes(message: Message) -> None:
    """Проверка доступности всех купленных стран-нод."""
    from services import nodes_health
    results = await nodes_health()
    if not results:
        await message.answer("Ноды не настроены (H1_NODES в .env)")
        return
    lines = ["🌐 <b>Состояние нод H1/VLESS</b>\n"]
    for name, ok in results:
        lines.append(f"• {name}: {'🟢 доступна' if ok else '🔴 недоступна'}")
    await message.answer("\n".join(lines))


@router.message(Command("sync"))
async def cmd_sync(message: Message) -> None:
    """Доздаёт VPN-клиента на нодах для активной подписки (если ключей не было)."""
    from datetime import datetime, timezone
    from services import vpn_name, parse_iso
    from h1cloud import H1CloudError

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /sync &lt;telegram_id&gt; — доздать ключи по активной подписке")
        return
    tg_id = _parse_ids(parts[1])
    if tg_id is None:
        await message.answer("ID должен быть числом")
        return
    sub = await db.active_sub(tg_id)
    if not sub:
        await message.answer("У пользователя нет активной подписки — используйте /grant")
        return
    left = parse_iso(sub["expires_at"]) - datetime.now(timezone.utc)
    days = max(1, left.days)
    if not h1.configured:
        await message.answer("Ноды не настроены (H1_NODES в .env)")
        return
    try:
        links = await h1.provision(vpn_name(tg_id), days, 0, 0)
    except H1CloudError as e:
        await message.answer(f"❌ Не удалось: {e}")
        return
    if not links:
        await message.answer("❌ Ноды недоступны, попробуйте позже")
        return
    await db.set_sub_links(sub["id"], links)
    lines = [f"✅ Ключи дозданы для <code>{tg_id}</code> (осталось {days} дн.):\n"]
    for country, link in links.items():
        lines.append(f"• <b>{country}</b>: <code>{link}</code>")
    await message.answer("\n".join(lines))


@router.message(Command("find"))
async def cmd_find(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /find &lt;telegram_id&gt;")
        return
    tg_id = _parse_ids(parts[1])
    if tg_id is None:
        await message.answer("ID должен быть числом")
        return
    user = await db.get_user(tg_id)
    if not user:
        await message.answer("Пользователь не найден")
        return
    sub = await db.active_sub(tg_id)
    paid = await db.count_paid_by_user(tg_id)
    await message.answer(texts.find_user(user, sub, paid))


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
    # /grant <id> <дней> [гб_трафика]
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Использование: /grant &lt;id&gt; &lt;дней&gt; [гб]")
        return
    tg_id = _parse_ids(parts[1])
    try:
        days = float(parts[2])
    except ValueError:
        await message.answer("Дни должны быть числом")
        return
    gb = 0
    if len(parts) >= 4:
        try:
            gb = int(parts[3])
        except ValueError:
            pass
    if tg_id is None:
        await message.answer("ID должен быть числом")
        return
    if not await db.get_user(tg_id):
        await message.answer("Пользователь не найден (пусть нажмёт /start)")
        return
    sub = await grant_plan(message.bot, tg_id, "admin", days, gb, notify=True,
                           reason=f"выдача админом {message.from_user.id}")
    if sub:
        await message.answer(f"✅ Выдано <b>{days:.0f} дн.</b> ({gb or 'без'} ГБ) пользователю <code>{tg_id}</code>")
    else:
        await message.answer("Не удалось выдать подписку, смотрите логи")


@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /ban &lt;id&gt;")
        return
    tg_id = _parse_ids(parts[1])
    if tg_id is None:
        await message.answer("ID должен быть числом")
        return
    ok = await db.set_banned(tg_id, True)
    if ok:
        await ban_everywhere(tg_id)
    await message.answer("🚫 Заблокирован" if ok else "Пользователь не найден")


@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /unban &lt;id&gt;")
        return
    tg_id = _parse_ids(parts[1])
    ok = await db.set_banned(tg_id, False)
    if ok:
        await unban_everywhere(tg_id)
    await message.answer("✅ Разблокирован" if ok else "Пользователь не найден")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state=None) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast &lt;текст&gt; — отправит всем пользователям")
        return
    text = parts[1].strip()
    users = await db.list_users()
    ok = fail = 0
    status_msg = await message.answer(texts.BROADCAST_PROGRESS.format(ok=0, fail=0))
    for user in users:
        try:
            await message.bot.send_message(user["telegram_id"], text)
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
        if (ok + fail) % 25 == 0:
            try:
                await status_msg.edit_text(texts.BROADCAST_PROGRESS.format(ok=ok, fail=fail))
            except Exception:  # noqa: BLE001
                pass
    try:
        await status_msg.edit_text(texts.BROADCAST_DONE.format(ok=ok, fail=fail))
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("reply"))
async def cmd_reply(message: Message) -> None:
    # /reply <тикет> <текст>
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].lstrip("#").isdigit():
        await message.answer("Использование: /reply &lt;номер_тикета&gt; &lt;текст&gt;")
        return
    ticket_id = int(parts[1].lstrip("#"))
    text = parts[2].strip()
    ticket = await db._one("SELECT * FROM tickets WHERE id=?", (ticket_id,))
    if not ticket:
        await message.answer("Тикет не найден")
        return
    try:
        await message.bot.send_message(
            ticket["user_id"], texts.SUPPORT_REPLY_TO_USER.format(ticket=ticket_id, text=html.escape(text))
        )
    except Exception as e:  # noqa: BLE001
        await message.answer(f"Не удалось доставить: {e}")
        return
    await db.add_ticket_message(ticket_id, True, text)
    await message.answer("✅ Ответ отправлен")


@router.message(Command("close"))
async def cmd_close(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("#").isdigit():
        await message.answer("Использование: /close &lt;номер_тикета&gt;")
        return
    ok = await db.close_ticket(int(parts[1].lstrip("#")))
    await message.answer("✅ Тикет закрыт" if ok else "Тикет не найден или уже закрыт")


@router.message(F.reply_to_message)
async def reply_to_forward(message: Message) -> None:
    """Админ отвечает на пересланное сообщение пользователя — отправляем ответ ему."""
    if not message.reply_to_message:
        return
    fwd = await db.get_admin_forward(message.reply_to_message.message_id)
    if not fwd:
        return
    if not (message.text or message.caption):
        return
    try:
        if message.photo or message.document:
            await message.bot.copy_message(fwd["user_id"], message.chat.id, message.message_id,
                                           caption=f"🛟 Ответ поддержки: {message.caption or ''}")
        else:
            await message.bot.send_message(
                fwd["user_id"], texts.SUPPORT_REPLY_TO_USER.format(ticket=fwd["ticket_id"],
                                                                  text=html.escape(message.text or ""))
            )
        await db.add_ticket_message(fwd["ticket_id"], True, message.text or "[медиа]")
        await message.answer("✅ Ответ отправлен")
    except Exception as e:  # noqa: BLE001
        await message.answer(f"Не удалось доставить: {e}")
