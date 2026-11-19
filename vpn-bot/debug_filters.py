"""Отладка фильтров текстовых хендлеров."""
import asyncio
import os
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "123456:AAATestTokenForLocalRun")
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), f"vpn_dbg_{os.getpid()}.db")

from aiogram.types import Chat, Message, User  # noqa: E402
from aiogram import F  # noqa: E402

from handlers import admin, support, user  # noqa: E402

m = Message(
    model_construct=True,
    message_id=1,
    date=datetime.now(timezone.utc),
    chat=Chat(model_construct=True, id=777, type="private"),
    from_user=User(model_construct=True, id=777, is_bot=False, first_name="T"),
    text="🚀 Подписка",
)

print("F.text resolve:", (F.text == "🚀 Подписка").resolve(m))
print("exists resolve:", F.from_user.exists().resolve(m))
print("combined:", (F.text == "🚀 Подписка").resolve(m) and F.from_user.exists().resolve(m))

# что зарегистрировано в роутере user
for name, router in (("admin", admin.router), ("support", support.router), ("user", user.router)):
    obs = router.observers.get("message")
    print(f"\n[{name}] message handlers: {len(obs.handlers) if obs else 0}")
    if obs:
        for h in obs.handlers:
            print("  callback:", h.callback.__name__ if hasattr(h.callback, '__name__') else h.callback,
                  "| filters:", [getattr(f, 'filter', f) for f in h.filters])
    print("  router-level filter:", obs._handler.filters if obs else None)
