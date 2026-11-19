"""E2E-тест диспетчера: фейковые апдейты прогоняются через реальные роутеры (без сети)."""
import asyncio
import os
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "123456:AAATestTokenForLocalRun")
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), f"vpn_disp_{os.getpid()}.db")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402
from aiogram.client.session.aiohttp import AiohttpSession  # noqa: E402

from handlers import admin, buy, support, user  # noqa: E402
import services  # noqa: E402


# Любой неучтённый сетевой вызов должен падать мгновенно и понятно:
def _blocked_make_request(self, bot, method, timeout=None):
    raise RuntimeError(f"BLOCKED NETWORK CALL: {method.method}")


AiohttpSession.make_request = _blocked_make_request

calls = []


async def fake_send_message(self, chat_id, text=None, **kwargs):
    calls.append(("send_message", chat_id, (text or "")[:50]))
    return Message(model_construct=True, message_id=1, date=datetime.now(timezone.utc),
                   chat=Chat(model_construct=True, id=chat_id, type="private"))


async def fake_me(self):
    return User(model_construct=True, id=9223700842, is_bot=True, first_name="Bot",
                username="test_bot")


async def fake_copy_message(self, chat_id, from_chat_id, message_id, **kwargs):
    calls.append(("copy_message", chat_id, ""))
    return Message(model_construct=True, message_id=2, date=datetime.now(timezone.utc),
                   chat=Chat(model_construct=True, id=chat_id, type="private"))


async def fake_answer_message(self, text=None, **kwargs):
    calls.append(("answer", self.chat.id, (text or "")[:50]))
    return None


async def fake_edit_text(self, text=None, **kwargs):
    calls.append(("edit_text", self.chat.id, (text or "")[:50]))
    return None


async def fake_delete(self, **kwargs):
    calls.append(("delete", self.chat.id, ""))
    return True


async def fake_edit_replymarkup(self, reply_markup=None, **kwargs):
    calls.append(("edit_reply_markup", self.chat.id, ""))
    return True


async def fake_cb_answer(self, text=None, show_alert=None, **kwargs):
    calls.append(("cb_answer", 0, text or ""))
    return True


Bot.send_message = fake_send_message
Bot.me = fake_me
Bot.copy_message = fake_copy_message
Message.answer = fake_answer_message
Message.edit_text = fake_edit_text
Message.delete = fake_delete
Message.edit_reply_markup = fake_edit_replymarkup
CallbackQuery.answer = fake_cb_answer


def make_msg(text, user_id=777):
    return Update(
        update_id=1,
        message=Message(
            model_construct=True,
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(model_construct=True, id=user_id, type="private"),
            from_user=User(model_construct=True, id=user_id, is_bot=False,
                           first_name="Tester", username="tester"),
            text=text,
        ),
    )


async def main():
    await services.init()
    bot = Bot(os.environ["BOT_TOKEN"])
    dp = Dispatcher()
    dp.include_routers(admin.router, support.router, user.router, buy.router)

    texts = ["/start", "🚀 Подписка", "👤 Профиль", "👥 Реферальная программа",
             "❓ Инструкция", "🛟 Поддержка", "привет"]

    # /start сперва, чтобы зарегистрировать пользователя
    await dp.feed_update(bot, make_msg("/start"))
    print("/start ->", len(calls), "ответов")

    for text in texts[1:]:
        calls.clear()
        try:
            await dp.feed_update(bot, make_msg(text))
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"!!! {text}: EXCEPTION:", repr(e))
            traceback.print_exc()
            continue
        if calls:
            print(f"{text} -> ответ: {calls[0][2]!r}")
        else:
            print(f"{text} -> БЕЗ ОТВЕТА (никакой хендлер не сработал)")

    # колбэк «Подписка» (sub:menu)
    from aiogram.types import CallbackQuery
    cb = Update(update_id=2, callback_query=CallbackQuery(
        model_construct=True, id="cb1", from_user=User(
            model_construct=True, id=777, is_bot=False, first_name="Tester"),
        chat_instance="x", data="sub:menu",
        message=Message(model_construct=True, message_id=5, date=datetime.now(timezone.utc),
                        chat=Chat(model_construct=True, id=777, type="private")),
    ))
    calls.clear()
    try:
        await dp.feed_update(bot, cb)
        print("callback sub:menu ->", len(calls), "ответов")
    except Exception as e:  # noqa: BLE001
        print("callback sub:menu EXCEPTION:", repr(e))


asyncio.run(main())
