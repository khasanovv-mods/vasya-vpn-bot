"""Клиент платёжного шлюза RollyPay.

API: https://docs.rollypay.io
- Создание платежа: POST /api/v1/payments (заголовки X-API-Key, X-Nonce)
- Статус: GET /api/v1/payments/{paymentID}
- Вебхуки: подпись HMAC-SHA256 от строки "timestamp + '.' + body" секретом кассы.
"""
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any, Dict, Optional

import aiohttp

log = logging.getLogger(__name__)


class RollyPayError(Exception):
    pass


class RollyPay:
    def __init__(self, api_key: str, signing_secret: str, base_url: str = "https://rollypay.io",
                 test_mode: bool = False) -> None:
        self.api_key = api_key
        self.signing_secret = signing_secret
        self.base = base_url.rstrip("/")
        self.api_prefix = "/api/v1"
        self.test_mode = test_mode
        self._http: Optional[aiohttp.ClientSession] = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.api_key,
                },
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()

    @staticmethod
    def _nonce() -> str:
        return str(uuid.uuid4())

    async def _req(self, method: str, path: str, body: Optional[dict] = None) -> Dict[str, Any]:
        http = await self._session()
        headers = {"X-Nonce": self._nonce()}
        try:
            async with http.request(method, f"{self.base}{self.api_prefix}{path}",
                                    json=body, headers=headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RollyPayError(f"RollyPay {method} {path} -> {resp.status}: {text[:500]}")
                try:
                    return json.loads(text)
                except Exception as e:
                    raise RollyPayError(f"RollyPay вернул не-JSON: {text[:200]} ({e})")
        except aiohttp.ClientError as e:
            raise RollyPayError(f"RollyPay недоступен: {e}")

    # ---------- платёж ----------
    async def create_payment(self, amount: float, order_id: str, description: str = "",
                             metadata: Optional[dict] = None, currency: str = "RUB") -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "amount": f"{float(amount):.2f}",
            "payment_currency": currency,
            "order_id": order_id,
            "description": description,
            "metadata": metadata or {},
        }
        if self.test_mode:
            body["test"] = True
        return await self._req("POST", "/payments", body)

    async def get_payment(self, payment_id: str) -> Dict[str, Any]:
        return await self._req("GET", f"/payments/{payment_id}")

    # ---------- вебхуки ----------
    def verify_signature(self, raw_body: bytes, timestamp: str, signature: str) -> bool:
        """Проверяет подпись вебхука. Обязательно вызывать до обработки."""
        if not (self.signing_secret and timestamp and signature):
            return False
        payload = f"{timestamp}.".encode("utf-8") + raw_body
        expected = hmac.new(self.signing_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())
