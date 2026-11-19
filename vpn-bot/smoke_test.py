"""Смоук-тест логики без сети: БД, выдача подписки (ноды — заглушки), QR, подписи RollyPay."""
import asyncio
import hashlib
import hmac as hmac_mod
import json
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "0:TEST")
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), f"vpn_test_{os.getpid()}.db")

import db as dbmod  # noqa: E402
import services  # noqa: E402
from db import Database  # noqa: E402
from h1cloud import H1CloudError, H1CloudClient, H1Cluster  # noqa: E402
from rollypay import RollyPay  # noqa: E402


class FakeNode(H1CloudClient):
    """Заглушка ноды с тем же интерфейсом."""

    def __init__(self, name: str):
        super().__init__(name, "https://fake", "tok", "")
        self.clients = {}

    async def provision(self, name, days, traffic_limit_gb=0, device_limit=0):
        self.clients[name] = {"days": days}
        return f"https://node/{self.name}/sub/{name}"

    async def extend(self, name, add_days):
        self.clients[name]["days"] += add_days
        return f"https://node/{self.name}/sub/{name}"

    async def get_client(self, name):
        return {"uuid": name} if name in self.clients else None

    async def refresh_links(self, name):
        return {"sub": f"https://node/{self.name}/sub/{name}"} if name in self.clients else {}

    async def ban_client(self, name, reason=""):
        self.clients.setdefault(name, {})["banned"] = True


class FakeBot:
    def __init__(self):
        self.msgs = []

    async def send_message(self, chat_id, text, **kw):
        self.msgs.append(("msg", chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.msgs.append(("photo", chat_id, caption))


async def main():
    database = Database(os.environ["DB_PATH"])
    await database.init()
    cluster = H1Cluster([FakeNode("Германия"), FakeNode("Турция")])
    await services.init(database, cluster, RollyPay("k", "secret"))

    user = await database.get_or_create_user(1, "test", "Test")
    assert user["telegram_id"] == 1
    ok = await database.set_referrer(1, 1)
    assert not ok, "нельзя самому себе быть реферером"
    await database.run("INSERT OR IGNORE INTO users(telegram_id, created_at) VALUES (2, '2026-01-01T00:00:00+00:00')")
    assert await database.set_referrer(1, 2)
    print("ok: users + referrer")

    pay_id = await database.create_payment(1, "m1", "ord1", 199)
    await database.update_payment(pay_id, "paid", rolly_payment_id="pay_1")
    got = await database.get_payment_by_rolly_id("pay_1")
    assert got["status"] == "paid" and got["paid_at"]
    print("ok: payment flow")

    # выдача подписки на 2 нодах
    sub = await services.grant_plan(FakeBot(), 1, "m1", 30, 0, devices=3, notify=False)
    assert sub is not None
    links = services.sub_links(sub)
    assert set(links) == {"Германия", "Турция"}, links
    print("ok: grant_plan создал клиента на обеих нодах:", links)

    # продление
    sub2 = await services.grant_plan(FakeBot(), 1, "m3", 90, 0, devices=3, notify=False)
    assert sub2["id"] == sub["id"] and sub2["expires_at"] > sub["expires_at"]
    print("ok: extend суммирует срок")

    # пробник
    await database.run("DELETE FROM subs WHERE user_id=3")
    await database.get_or_create_user(3, "u3", "User 3")
    ok = await services.grant_trial(FakeBot(), 3)
    assert ok
    assert not await services.grant_trial(FakeBot(), 3)
    print("ok: trial одноразовый")

    # ключи по странам
    bot = FakeBot()
    ok = await services.send_key_now(bot, 1)
    assert ok and any(m[0] == "msg" for m in bot.msgs)
    assert any("Германия" in m[2] for m in bot.msgs)
    print("ok: send_key_now показывает все страны")

    # реферальный бонус за первую оплату
    await services._grant_referral_bonus_for_payment(FakeBot(), 1)
    u2 = await database.get_user(2)
    days = __import__("config").REF_BONUS_REFERRER_DAYS
    assert abs(u2["pending_ref_days"] - days) < 0.01
    print(f"ok: рефереру начислено {days} дн. в копилку (нет активной подписки)")

    # ban
    await database.set_banned(1, True)
    await services.ban_everywhere(1)
    print("ok: ban на нодах")

    # QR
    qr = services.make_qr_png("https://example.com/sub/abc")
    assert qr and len(qr) > 100
    print("ok: qr")

    # подпись вебхуков RollyPay
    rp = RollyPay("k", "secret")
    body = b'{"a":1}'
    ts = "1700000000"
    sig = hmac_mod.new(b"secret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert rp.verify_signature(body, ts, sig)
    assert not rp.verify_signature(body, ts, "bad")
    print("ok: rollypay webhook signature")

    # sanitize_name
    from h1cloud import sanitize_name
    assert sanitize_name("tg 12345!") == "tg_12345"
    print("ok: sanitize_name")

    await database.close()


asyncio.run(main())
print("ALL SMOKE TESTS PASSED")
