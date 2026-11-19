"""Проверка ноды H1/VLESS: health, создание тестового клиента, ссылка подписки, удаление."""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

from h1cloud import H1CloudClient, H1CloudError  # noqa: E402
import config  # noqa: E402

TEST_NAME = "bot_selftest_check"


async def fetch_text(url: str) -> str:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=20), ssl=False) as r:
            return await r.text()


async def main() -> None:
    node_cfg = config.H1_NODES[0]
    node = H1CloudClient(
        name=node_cfg["name"], base_url=node_cfg["api_url"], token=node_cfg["token"],
        sub_url_template=node_cfg["sub_url"],
        verify_ssl=config.H1_VERIFY_SSL, timeout=config.H1_REQUEST_TIMEOUT,
    )
    print(f"Нода: {node.name} | API: {node.base_url}")

    print("\n[1/5] GET /health …")
    try:
        h = await node.health()
        print("  OK:", h)
    except H1CloudError as e:
        print("  ОШИБКА:", e)
        await node.close()
        return

    print(f"\n[2/5] Существующий клиент {TEST_NAME}?")
    existing = await node.get_client(TEST_NAME)
    print("  найден:" if existing else "  нет (создадим)", )

    print(f"\n[3/5] POST /create (клиент {TEST_NAME}, 3 дня)…")
    try:
        created = await node.create_client(TEST_NAME, 3)
        print("  OK, ответ:", {k: created[k] for k in list(created)[:8]})
    except H1CloudError as e:
        if e.code in ("name_taken", "exists", "duplicate", "bad_name"):
            print("  имя занято — пробуем продлить:", e.code)
            created = await node.edit_client(TEST_NAME, add_days=3)
        else:
            print("  ОШИБКА:", e)
            await node.close()
            return

    print("\n[4/5] Ссылка подписки …")
    client = await node.get_client(TEST_NAME)
    sub = node.build_sub_url(client or {})
    print("  uuid:", (client or {}).get("uuid"))
    print("  ссылка:", sub)
    if sub:
        try:
            body = await fetch_text(sub)
            print(f"  Ответ подписки ({len(body)} байт):", body[:200].replace("\n", " | "))
        except Exception as e:  # noqa: BLE001
            print("  Не удалось открыть ссылку:", e)

    print(f"\n[5/5] Удаляем тестового клиента {TEST_NAME} …")
    try:
        await node.delete_client(TEST_NAME)
        print("  удалён OK")
    except H1CloudError as e:
        print("  Не удалился:", e)

    await node.close()
    print("\nИТОГ: API работает — можно подключать бота.")


asyncio.run(main())
