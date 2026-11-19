"""Конфигурация бота: всё читается из .env, тарифы — прямо здесь."""
import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# .env ищем строго рядом с этим файлом: bothost может запускать бота из другой папки,
# и load_dotenv() без пути искал бы .env в текущей рабочей директории и не находил.
BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / ".env"
load_dotenv(DOTENV_PATH)


def dotenv_status() -> dict:
    """Для диагностики в логе: найден ли .env и какие ключи в нём есть (только имена)."""
    if not DOTENV_PATH.exists():
        return {"path": str(DOTENV_PATH), "exists": False, "keys": []}
    keys = []
    for line in DOTENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.append(line.split("=", 1)[0].strip())
    return {"path": str(DOTENV_PATH), "exists": True, "keys": keys}


def _ids(raw: str) -> List[int]:
    out = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


def _bool(raw: str) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "да")


# ---------- Telegram ----------
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
# ADMIN_IDS или ADMIN_ID (алиас, вдруг так удобнее вписать)
ADMIN_IDS: List[int] = _ids(os.getenv("ADMIN_IDS", "")) or _ids(os.getenv("ADMIN_ID", ""))
BRAND_NAME: str = os.getenv("BRAND_NAME", "Vasya VPN").strip() or "Vasya VPN"
SUPPORT_URL: str = os.getenv("SUPPORT_URL", "").strip()

# ---------- База данных ----------
DB_PATH: str = os.getenv("DB_PATH", "vpn_bot.db").strip() or "vpn_bot.db"

# ---------- Ноды H1/VLESS (панель входит в тариф «Свой VPN» h1cloud) ----------
# Для каждой страны (сервера) из кабинета h1cloud:
#   URL API, токен и шаблон ссылки подписки: name|api_url|token|sub_url_template
#   api_url — с суффиксом /api, например https://1.2.3.4:25626/api
#   sub_url_template — https://1.2.3.4:25627/sub/{uuid}
# Ноды разделяются точкой с запятой:
# H1_NODES=Германия|https://1.2.3.4:25626/api|token1|https://1.2.3.4:25627/sub/{uuid};Турция|...
H1_VERIFY_SSL: bool = _bool(os.getenv("H1_VERIFY_SSL", "false"))
H1_REQUEST_TIMEOUT: int = int(os.getenv("H1_REQUEST_TIMEOUT", "20") or 20)


def _parse_nodes(raw: str) -> List[dict]:
    nodes = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split("|")
        if len(parts) < 2:
            continue
        nodes.append({
            "name": parts[0].strip() or "Node",
            "api_url": parts[1].strip(),
            "token": parts[2].strip() if len(parts) > 2 else "",
            "sub_url": parts[3].strip() if len(parts) > 3 else "",
        })
    return nodes


H1_NODES: List[dict] = _parse_nodes(os.getenv("H1_NODES", ""))


def h1_configured() -> bool:
    return bool(H1_NODES)


# ---------- RollyPay ----------
RP_API_KEY: str = os.getenv("ROLLYPAY_API_KEY", "").strip()
RP_SIGNING_SECRET: str = os.getenv("ROLLYPAY_SIGNING_SECRET", "").strip()
RP_BASE_URL: str = os.getenv("ROLLYPAY_BASE_URL", "https://rollypay.io").strip().rstrip("/")
RP_TEST_MODE: bool = _bool(os.getenv("ROLLYPAY_TEST_MODE", "false"))


def rollypay_configured() -> bool:
    return bool(RP_API_KEY)


# ---------- Вебхуки RollyPay ----------
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080") or "8080")
PUBLIC_URL: str = os.getenv("PUBLIC_URL", "").strip().rstrip("/")

# ---------- Рефералка ----------
REF_BONUS_REFERRER_DAYS: int = int(os.getenv("REF_BONUS_REFERRER_DAYS", "7") or 0)
REF_BONUS_REFEREE_DAYS: int = int(os.getenv("REF_BONUS_REFEREE_DAYS", "3") or 0)
REF_BONUS_IMMEDIATE_DAYS: int = int(os.getenv("REF_BONUS_IMMEDIATE_DAYS", "0") or 0)

# ---------- Пробный период ----------
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "3") or 0)
TRIAL_TRAFFIC_GB: int = int(os.getenv("TRIAL_TRAFFIC_GB", "10") or 0)
TRIAL_DEVICES: int = int(os.getenv("TRIAL_DEVICES", "1") or 0)

# ---------- Фоновые задачи ----------
NOTIFY_CHECK_MINUTES: int = int(os.getenv("NOTIFY_CHECK_MINUTES", "10") or 10)
PAYMENT_CHECK_MINUTES: int = int(os.getenv("PAYMENT_CHECK_MINUTES", "5") or 5)


# ---------- Тарифы ----------
# price — в рублях; traffic_gb — лимит трафика за весь срок (0 = безлимит);
# devices — лимит одновременных устройств (0 = без лимита)
PLANS: List[dict] = [
    {"id": "m1", "title": "1 месяц", "days": 30, "price": 199, "traffic_gb": 0, "devices": 3},
    {"id": "m3", "title": "3 месяца", "days": 90, "price": 499, "traffic_gb": 0, "devices": 3},
    {"id": "m6", "title": "6 месяцев", "days": 180, "price": 899, "traffic_gb": 0, "devices": 3},
    {"id": "m12", "title": "12 месяцев", "days": 365, "price": 1499, "traffic_gb": 0, "devices": 5},
]


def get_plan(plan_id: str) -> Optional[dict]:
    for p in PLANS:
        if p["id"] == plan_id:
            return p
    return None


def notify_bot_url() -> str:
    """Callback_url для личного кабинета RollyPay."""
    if PUBLIC_URL:
        return f"{PUBLIC_URL}/rollypay/callback"
    return ""
