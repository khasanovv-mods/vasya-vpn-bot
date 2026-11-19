"""Клиент API ноды H1/VLESS (панель, которая входит в тариф «Свой VPN» h1cloud).

API-токен ноды: в кабинете h1cloud → сервер → «Панель H1/VLESS» → команда `vpn api token`.
Все эндпоинты под префиксом /api, ответы JSON с полем `ok`, авторизация Bearer.
Сертификат ноды может быть самоподписанным — проверка TLS настраивается.
"""
from __future__ import annotations

import logging
import re
import ssl
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)


def sanitize_name(value: str, fallback: str = "client") -> str:
    """Нода принимает имена только из [A-Za-z0-9._-]."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    return (text or fallback)[:64]


class H1CloudError(Exception):
    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class H1CloudClient:
    """Клиент одной ноды (одной страны)."""

    def __init__(self, name: str, base_url: str, token: str, sub_url_template: str,
                 verify_ssl: bool = False, timeout: int = 20) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.sub_url_template = sub_url_template  # вида https://host:25627/sub/{uuid}
        self._ssl: ssl.SSLContext | bool = True if verify_ssl else False
        self._timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, path: str, json: Optional[dict] = None) -> Dict[str, Any]:
        if not self.configured:
            raise H1CloudError("Нода не настроена (H1_NODES)", code="not_configured")
        session = await self._session_get()
        url = f"{self.base_url}{path}"
        try:
            async with session.request(method, url, ssl=self._ssl, json=json) as resp:
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise H1CloudError(f"Нода {self.name} недоступна: {exc}", code="unreachable") from exc
        except Exception as exc:  # noqa: BLE001
            raise H1CloudError(f"Нода {self.name}: некорректный ответ", code="bad_response") from exc

        if not isinstance(data, dict):
            raise H1CloudError(f"Нода {self.name}: некорректный ответ", code="bad_response")
        if not data.get("ok", False):
            code = str(data.get("error") or "unknown")
            raise H1CloudError(f"Нода {self.name} вернула ошибку: {code}", code=code)
        return data

    # ---------- эндпоинты ----------
    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def get_client(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            data = await self._request("GET", f"/clients/{quote(sanitize_name(name), safe='')}")
        except H1CloudError as exc:
            if exc.code == "user_not_found":
                return None
            raise
        client = data.get("client")
        return client if isinstance(client, dict) else data

    async def create_client(self, name: str, days: int, traffic_limit_gb: int = 0,
                            device_limit: int = 0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"name": sanitize_name(name), "days": max(1, days)}
        if traffic_limit_gb > 0:
            payload["traffic_limit_gb"] = traffic_limit_gb
        if device_limit > 0:
            payload["device_limit"] = device_limit
        return await self._request("POST", "/create", payload)

    async def edit_client(self, name: str, add_days: Optional[int] = None,
                          traffic_limit_gb: Optional[int] = None,
                          device_limit: Optional[int] = None) -> Dict[str, Any]:
        """PATCH /edit: days прибавляется к текущему сроку клиента."""
        payload: Dict[str, Any] = {"name": sanitize_name(name)}
        if add_days is not None:
            payload["days"] = max(1, add_days)
        if traffic_limit_gb is not None:
            payload["traffic_limit_gb"] = traffic_limit_gb
        if device_limit is not None:
            payload["device_limit"] = device_limit
        return await self._request("PATCH", "/edit", payload)

    async def ban_client(self, name: str, reason: str = "") -> Dict[str, Any]:
        return await self._request(
            "PATCH", f"/clients/{quote(sanitize_name(name), safe='')}/ban", {"reason": reason}
        )

    async def unban_client(self, name: str) -> Dict[str, Any]:
        return await self._request("PATCH", f"/clients/{quote(sanitize_name(name), safe='')}/unban")

    async def delete_client(self, name: str) -> bool:
        try:
            await self._request("DELETE", f"/clients/{quote(sanitize_name(name), safe='')}")
            return True
        except H1CloudError as exc:
            if exc.code == "user_not_found":
                return True
            raise

    async def reset_traffic(self, name: str) -> Dict[str, Any]:
        return await self._request(
            "PATCH", f"/clients/{quote(sanitize_name(name), safe='')}/reset-traffic"
        )

    # ---------- высокоуровневое ----------
    def build_sub_url(self, client: Dict[str, Any]) -> str:
        """Ссылка-подписка: сначала поле sub_url от ноды, иначе шаблон + uuid."""
        if isinstance(client, dict):
            sub = client.get("sub_url") or client.get("subscription_url")
            if isinstance(sub, str) and sub.startswith("http"):
                return sub
        uuid = client.get("uuid") or client.get("id") or "" if isinstance(client, dict) else ""
        if not uuid or not self.sub_url_template or "{uuid}" not in self.sub_url_template:
            return ""
        return self.sub_url_template.replace("{uuid}", str(uuid))

    async def provision(self, name: str, days: int, traffic_limit_gb: int = 0,
                        device_limit: int = 0) -> str:
        """Создаёт клиента (или продлевает, если имя занято) и возвращает ссылку-подписку."""
        try:
            client = await self.create_client(name, days, traffic_limit_gb, device_limit)
        except H1CloudError:
            # имя уже существует на ноде — продлеваем и обновляем лимиты
            await self.edit_client(name, add_days=days, traffic_limit_gb=traffic_limit_gb,
                                   device_limit=device_limit)
            client = await self.get_client(name) or {}
        if not isinstance(client, dict) or not client:
            client = await self.get_client(name) or {}
        sub = self.build_sub_url(client)
        if not sub:
            # попытка вытащить ссылку из полей клиента
            link = client.get("link") if isinstance(client, dict) else None
            if isinstance(link, str) and link.startswith("vless://"):
                return link
            raise H1CloudError(f"Нода {self.name}: не получили ссылку подписки", code="no_link")
        return sub

    async def extend(self, name: str, add_days: int) -> None:
        await self.edit_client(name, add_days=add_days)

    async def client_links(self, name: str) -> List[str]:
        client = await self.get_client(name)
        if not client:
            return []
        links: List[str] = []
        raw = client.get("links")
        if isinstance(raw, dict):
            links.extend(v for v in raw.values() if isinstance(v, str) and v.startswith(("vless://", "http")))
        elif isinstance(raw, list):
            links.extend(v for v in raw if isinstance(v, str) and v.startswith(("vless://", "http")))
        link = client.get("link")
        if isinstance(link, str) and link.startswith(("vless://", "http")) and link not in links:
            links.append(link)
        sub = self.build_sub_url(client)
        if sub:
            links.insert(0, sub)
        return links


class H1Cluster:
    """Все ноды (страны) из конфига. Провижинит пользователя на каждой."""

    def __init__(self, nodes: List["H1CloudClient"]) -> None:
        self.nodes = nodes

    @property
    def configured(self) -> bool:
        return bool(self.nodes) and any(n.configured for n in self.nodes)

    @property
    def names(self) -> List[str]:
        return [n.name for n in self.nodes if n.configured]

    async def close(self) -> None:
        for n in self.nodes:
            await n.close()

    async def provision(self, name: str, days: int, traffic_gb: int = 0,
                        devices: int = 0) -> Dict[str, str]:
        """{страна: ссылка-подписка}; страны с ошибкой пропускаются."""
        links: Dict[str, str] = {}
        errors: List[str] = []
        for node in self.nodes:
            if not node.configured:
                continue
            try:
                links[node.name] = await node.provision(name, days, traffic_gb, devices)
            except H1CloudError as e:
                log.error("H1 provision %s: %s", node.name, e)
                errors.append(node.name)
        if not links and errors:
            raise H1CloudError(f"Ни одна нода не доступна: {', '.join(errors)}", code="all_failed")
        return links

    async def extend(self, name: str, add_days: int) -> Dict[str, str]:
        links: Dict[str, str] = {}
        for node in self.nodes:
            if not node.configured:
                continue
            try:
                await node.extend(name, add_days)
                client = await node.get_client(name)
                sub = node.build_sub_url(client or {}) if client else ""
                if sub:
                    links[node.name] = sub
            except H1CloudError as e:
                log.error("H1 extend %s: %s", node.name, e)
        return links

    async def refresh_links(self, name: str) -> Dict[str, str]:
        links: Dict[str, str] = {}
        for node in self.nodes:
            if not node.configured:
                continue
            try:
                client = await node.get_client(name)
                if client:
                    sub = node.build_sub_url(client)
                    if sub:
                        links[node.name] = sub
                        continue
                    live = await node.client_links(name)
                    if live:
                        links[node.name] = live[0]
            except H1CloudError as e:
                log.warning("H1 refresh %s: %s", node.name, e)
        return links

    async def ban(self, name: str) -> None:
        for node in self.nodes:
            if not node.configured:
                continue
            try:
                await node.ban_client(name, reason="bot ban")
            except H1CloudError as e:
                log.warning("H1 ban %s: %s", node.name, e)

    async def unban(self, name: str) -> None:
        for node in self.nodes:
            if not node.configured:
                continue
            try:
                await node.unban_client(name)
            except H1CloudError as e:
                log.warning("H1 unban %s: %s", node.name, e)
