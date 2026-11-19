"""Полный аудит согласованности проекта без сети."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import config
import texts
import keyboards


def main():
    # 1. Кнопки меню в клавиатуре == исключения FSM поддержки
    kb = keyboards.main_menu()
    kb_texts = [b.text for row in kb.keyboard for b in row]
    print("Кнопки клавиатуры:", kb_texts)

    from handlers.support import MENU_TEXTS
    assert set(kb_texts) == MENU_TEXTS, f"Несовпадение: {set(kb_texts) ^ MENU_TEXTS}"
    print("OK: клавиатура == MENU_TEXTS поддержки")

    # 2. Хендлеры меню существуют для каждой кнопки
    all_handlers = ""
    for f in ("handlers/user.py", "handlers/support.py", "handlers/admin.py", "handlers/buy.py"):
        all_handlers += open(f, encoding="utf-8").read()
    for btn in kb_texts:
        assert f'F.text == "{btn}"' in all_handlers, f"нет хендлера для {btn}"
    print("OK: у каждой кнопки есть хендлер")

    # 3. Упоминания в welcome совпадают с кнопками
    w = texts.welcome()
    for btn in kb_texts:
        short = btn.split("—")[0].strip().split(" ", 1)[1] if " " in btn and "—" in w else btn
        assert short.split(" ")[0] in w or btn in w, f"«{btn}» не упомянут в welcome"
    print("OK: welcome согласован")

    # 4. Планы
    for p in config.PLANS:
        assert config.get_plan(p["id"]) is p
    assert config.get_plan("nope") is None
    print("OK: планы:", [(p["id"], p["price"], p["days"], p["devices"]) for p in config.PLANS])

    # 5. Все тексты форматируются
    texts.stats(1, 2, 3, 4, 5.0, 6)
    texts.find_user({"telegram_id": 1, "username": "u", "full_name": "f", "created_at": None,
                     "referrer_id": None, "banned": 0, "trial_used": 0}, None, 0)
    texts.subscription_menu("x")
    texts.payment_created(config.PLANS[0], "http://pay", "ord-1", True)
    texts.payment_created(config.PLANS[0], "http://pay", "ord-1", False)
    texts.key_message("https://x/sub", "дата", "1 ГБ", "безлимит")
    texts.REFERRAL.format(ref_days=7, friend_days=3, link="l", count=0, earned=0, pending="")
    texts.welcome(config.BRAND_NAME)
    texts.INSTRUCTION
    texts.SUPPORT_ASK
    texts.SUPPORT_SENT.format(ticket=1)
    texts.SUPPORT_NEW_FROM_USER.format(uid=1, name="n", ticket=1, text="t")
    texts.SUPPORT_REPLY_TO_USER.format(ticket=1, text="t")
    texts.expired_notice("t", "d")
    texts.expiring_notice("t", "d", 3)
    texts.ADMIN_MENU
    texts.BROADCAST_DONE.format(ok=1, fail=0)
    texts.profile_sub(True, "d", "m1")
    texts.profile_sub(False, "", "")
    texts.TRIAL_OK
    texts.payment_activated_head(True)
    print("OK: все тексты форматируются")

    # 6. Колбэки, которые шлёт keyboards, имеют хендлеры
    kb_src = open("keyboards.py", encoding="utf-8").read()
    import re
    cbs = set(re.findall(r'callback_data="(sub:[a-z:]+|support:stop|keyc:\d*)"', kb_src))
    user_src = open("handlers/user.py", encoding="utf-8").read()
    buy_src = open("handlers/buy.py", encoding="utf-8").read()
    sup_src = open("handlers/support.py", encoding="utf-8").read()
    all_handlers = user_src + buy_src + sup_src
    for cb in cbs:
        base = cb.split(":")[0]
        assert f'"{base}:' in all_handlers or f"'{base}:'" in all_handlers, f"нет хендлера для {cb}"
    print("OK: все колбэки клавиатур имеют хендлеры:", sorted(cbs))

    # 7. Конфиг
    s = config.dotenv_status()
    print(f"OK: .env {'найден' if s['exists'] else 'НЕ НАЙДЕН'} ({len(s['keys'])} ключей), нод: {len(config.H1_NODES)}")


main()
print("PROJECT AUDIT PASSED")
