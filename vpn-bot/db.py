"""SQLite (aiosqlite) — пользователи, подписки, платежи, тикеты поддержки."""
import json
from typing import Any, Dict, List, Optional

import aiosqlite

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    telegram_id      INTEGER PRIMARY KEY,
    username         TEXT,
    full_name        TEXT,
    created_at       TEXT NOT NULL,
    referrer_id      INTEGER,
    banned           INTEGER DEFAULT 0,
    trial_used       INTEGER DEFAULT 0,
    pending_ref_days REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subs(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    plan_id     TEXT,
    starts_at   TEXT,
    expires_at  TEXT,
    active      INTEGER DEFAULT 1,
    notified_3d INTEGER DEFAULT 0,
    notified_1d INTEGER DEFAULT 0,
    vpn_name    TEXT,
    links_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_subs_user ON subs(user_id, active);
CREATE TABLE IF NOT EXISTS payments(
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    plan_id           TEXT NOT NULL,
    order_id          TEXT UNIQUE NOT NULL,
    rolly_payment_id  TEXT,
    amount            REAL,
    currency          TEXT,
    status            TEXT,
    created_at        TEXT,
    paid_at           TEXT,
    activated         INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pay_status ON payments(status);
CREATE TABLE IF NOT EXISTS tickets(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    status     TEXT DEFAULT 'open',
    created_at TEXT,
    closed_at  TEXT
);
CREATE TABLE IF NOT EXISTS ticket_messages(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL,
    from_admin INTEGER DEFAULT 0,
    text       TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS admin_forwards(
    admin_msg_id INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    ticket_id    INTEGER
);
"""


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path
        self.db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(SCHEMA)
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    async def _one(self, sql: str, args: tuple = ()) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute(sql, args)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _all(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        cur = await self.db.execute(sql, args)
        return [dict(r) for r in await cur.fetchall()]

    async def run(self, sql: str, args: tuple = ()) -> int:
        cur = await self.db.execute(sql, args)
        await self.db.commit()
        return cur.lastrowid or 0

    # ---------- Пользователи ----------
    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        return await self._one("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))

    async def get_or_create_user(self, telegram_id: int, username: str, full_name: str) -> Dict[str, Any]:
        user = await self.get_user(telegram_id)
        if user:
            if username != user["username"] or full_name != user["full_name"]:
                await self.run("UPDATE users SET username=?, full_name=? WHERE telegram_id=?",
                               (username, full_name, telegram_id))
                user = await self.get_user(telegram_id)
            return user
        await self.run(
            "INSERT INTO users(telegram_id, username, full_name, created_at) VALUES (?,?,?,?)",
            (telegram_id, username, full_name, now_iso()),
        )
        return await self.get_user(telegram_id)

    async def set_referrer(self, telegram_id: int, referrer_id: int) -> bool:
        user = await self.get_user(telegram_id)
        if not user or user["referrer_id"] or referrer_id == telegram_id:
            return False
        await self.run("UPDATE users SET referrer_id=? WHERE telegram_id=?", (referrer_id, telegram_id))
        return True

    async def list_users(self) -> List[Dict[str, Any]]:
        return await self._all("SELECT * FROM users")

    async def set_banned(self, telegram_id: int, banned: bool) -> bool:
        if not await self.get_user(telegram_id):
            return False
        await self.run("UPDATE users SET banned=? WHERE telegram_id=?", (1 if banned else 0, telegram_id))
        return True

    async def add_pending_ref_days(self, telegram_id: int, days: float) -> None:
        await self.run("UPDATE users SET pending_ref_days=pending_ref_days+? WHERE telegram_id=?",
                       (days, telegram_id))

    async def take_pending_ref_days(self, telegram_id: int) -> float:
        user = await self.get_user(telegram_id)
        if not user or not user["pending_ref_days"]:
            return 0.0
        await self.run("UPDATE users SET pending_ref_days=0 WHERE telegram_id=?", (telegram_id,))
        return float(user["pending_ref_days"])

    # ---------- Статистика ----------
    async def count_users(self) -> int:
        row = await self._one("SELECT COUNT(*) c FROM users")
        return row["c"] if row else 0

    async def count_new_users(self, days: int) -> int:
        row = await self._one(
            "SELECT COUNT(*) c FROM users WHERE created_at >= datetime('now', ?)",
            (f"-{days} days",),
        )
        return row["c"] if row else 0

    async def count_active_subs(self) -> int:
        row = await self._one("SELECT COUNT(*) c FROM subs WHERE active=1")
        return row["c"] if row else 0

    async def count_paid_payments(self) -> int:
        row = await self._one("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM payments WHERE status='paid'")
        return row["c"] if row else 0

    async def revenue(self) -> float:
        row = await self._one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE status='paid'")
        return float(row["s"]) if row else 0.0

    # ---------- Подписки ----------
    async def active_sub(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self._one(
            "SELECT * FROM subs WHERE user_id=? AND active=1 ORDER BY expires_at DESC LIMIT 1",
            (user_id,),
        )

    async def any_sub_ever(self, user_id: int) -> bool:
        row = await self._one("SELECT 1 x FROM subs WHERE user_id=? LIMIT 1", (user_id,))
        return bool(row)

    async def create_sub(self, user_id: int, plan_id: str, expires_at: str,
                         vpn_name: str = "", links_json: str = "{}") -> int:
        return await self.run(
            "INSERT INTO subs(user_id, plan_id, starts_at, expires_at, active, vpn_name, links_json)"
            " VALUES (?,?,?,?,1,?,?)",
            (user_id, plan_id, now_iso(), expires_at, vpn_name, links_json),
        )

    async def extend_sub(self, sub_id: int, plan_id: str, expires_at: str) -> None:
        await self.run(
            "UPDATE subs SET plan_id=?, expires_at=?, notified_3d=0, notified_1d=0 WHERE id=?",
            (plan_id, expires_at, sub_id),
        )

    async def set_sub_links(self, sub_id: int, links: Dict[str, str]) -> None:
        await self.run("UPDATE subs SET links_json=? WHERE id=?", (json.dumps(links, ensure_ascii=False), sub_id))

    async def deactivate_sub(self, sub_id: int) -> None:
        await self.run("UPDATE subs SET active=0 WHERE id=?", (sub_id,))

    async def mark_notified(self, sub_id: int, field: str) -> None:
        await self.run(f"UPDATE subs SET {field}=1 WHERE id=?", (sub_id,))

    async def subs_active(self) -> List[Dict[str, Any]]:
        return await self._all("SELECT * FROM subs WHERE active=1")

    async def all_active_subs(self) -> List[Dict[str, Any]]:
        return await self._all(
            "SELECT * FROM subs WHERE active=1 AND expires_at >= datetime('now') ORDER BY expires_at"
        )

    # ---------- Платежи ----------
    async def create_payment(self, user_id: int, plan_id: str, order_id: str,
                             amount: float, currency: str = "RUB") -> int:
        return await self.run(
            "INSERT INTO payments(user_id, plan_id, order_id, amount, currency, status, created_at)"
            " VALUES (?,?,?,?,?, 'created', ?)",
            (user_id, plan_id, order_id, amount, currency, now_iso()),
        )

    async def get_payment(self, payment_id: int) -> Optional[Dict[str, Any]]:
        return await self._one("SELECT * FROM payments WHERE id=?", (payment_id,))

    async def get_payment_by_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        return await self._one("SELECT * FROM payments WHERE order_id=?", (order_id,))

    async def get_payment_by_rolly_id(self, rolly_payment_id: str) -> Optional[Dict[str, Any]]:
        return await self._one("SELECT * FROM payments WHERE rolly_payment_id=?", (rolly_payment_id,))

    async def update_payment(self, payment_id: int, status: str,
                             rolly_payment_id: Optional[str] = None) -> None:
        if rolly_payment_id:
            await self.run("UPDATE payments SET rolly_payment_id=? WHERE id=?", (rolly_payment_id, payment_id))
        if status == "paid":
            await self.run("UPDATE payments SET status=?, paid_at=? WHERE id=?",
                           (status, now_iso(), payment_id))
        else:
            await self.run("UPDATE payments SET status=? WHERE id=?", (status, payment_id))

    async def mark_payment_activated(self, payment_id: int) -> None:
        await self.run("UPDATE payments SET activated=1 WHERE id=?", (payment_id,))

    async def pending_payments(self, max_age_hours: int = 24) -> List[Dict[str, Any]]:
        return await self._all(
            "SELECT * FROM payments WHERE status IN ('created','processing')"
            " AND created_at >= datetime('now', ?)",
            (f"-{max_age_hours} hours",),
        )

    async def count_paid_by_user(self, user_id: int) -> int:
        row = await self._one("SELECT COUNT(*) c FROM payments WHERE user_id=? AND status='paid'", (user_id,))
        return row["c"] if row else 0

    # ---------- Поддержка ----------
    async def create_ticket(self, user_id: int) -> int:
        return await self.run("INSERT INTO tickets(user_id, created_at) VALUES (?,?)", (user_id, now_iso()))

    async def last_open_ticket(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self._one(
            "SELECT * FROM tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (user_id,)
        )

    async def close_ticket(self, ticket_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE tickets SET status='closed', closed_at=? WHERE id=? AND status='open'",
            (now_iso(), ticket_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def add_ticket_message(self, ticket_id: int, from_admin: bool, text: str) -> None:
        await self.run("INSERT INTO ticket_messages(ticket_id, from_admin, text, created_at) VALUES (?,?,?,?)",
                       (ticket_id, 1 if from_admin else 0, text, now_iso()))

    async def save_admin_forward(self, admin_msg_id: int, user_id: int, ticket_id: int) -> None:
        await self.run("INSERT OR REPLACE INTO admin_forwards(admin_msg_id, user_id, ticket_id) VALUES (?,?,?)",
                       (admin_msg_id, user_id, ticket_id))

    async def get_admin_forward(self, admin_msg_id: int) -> Optional[Dict[str, Any]]:
        return await self._one("SELECT * FROM admin_forwards WHERE admin_msg_id=?", (admin_msg_id,))
