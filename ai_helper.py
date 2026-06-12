import os
import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"


def _claude(system, user, max_tokens=400):
    if not ANTHROPIC_API_KEY:
        return None
    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=15,
        )
        return resp.json()["content"][0]["text"].strip()
    except Exception:
        return None


def ai_match_client(input_name, all_clients):
    if not all_clients:
        return None
    low = input_name.lower()
    for c in all_clients:
        if low in c.lower() or c.lower() in low:
            return c
    client_list = "\n".join(all_clients)
    result = _claude(
        system=(
            "Sen O'zbek ismlarini taniy oluvchi yordamchisan. "
            "Foydalanuvchi mijoz ismini noto'g'ri yozishi mumkin. "
            "Ro'yxatdan eng mos ismni qaytар. Faqat ismni yoz. "
            "Mos kelmasa faqat 'YOQ' yoz."
        ),
        user="Ro'yxat:\n" + client_list + "\n\nYozilgan: " + input_name,
        max_tokens=50,
    )
    if result and result != "YOQ" and result in all_clients:
        return result
    return None


def ai_analyze_report(day, by_source, totals, balances):
    from database import SOURCE_NAMES
    src_lines = []
    for row in by_source:
        name = SOURCE_NAMES.get(row["source"], row["source"])
        src_lines.append(name + ": " + str(row["qty"]) + " dona, " + str(row["total"]) + " so'm")

    top3 = [b for b in balances if b["balance"] > 0][:3]
    debtors = ", ".join(b["name"] + " (" + str(b["balance"]) + " so'm)" for b in top3)

    user_text = (
        "Sana: " + day + "\n"
        "Manba bo'yicha:\n" + "\n".join(src_lines) + "\n"
        "Jami: " + str(totals["qty"] or 0) + " dona, " + str(totals["total"] or 0) + " so'm\n"
        "Eng katta qarzdorlar: " + (debtors or "yoq")
    )

    return _claude(
        system=(
            "Sen gul optom savdosi bo'yicha qisqa tahlilchi san. "
            "O'zbek tilida, 3-5 gapda, aniq va foydali tahlil ber. "
            "Emoji ishlatma."
        ),
        user=user_text,
        max_tokens=300,
    )


def ai_client_advice(client_name, balance):
    return _claude(
        system=(
            "Sen savdo moliyaviy maslahatchisi san. "
            "O'zbek tilida, 2 gapda, aniq maslahat ber. Emoji ishlatma."
        ),
        user="Mijoz: " + client_name + "\nQoldiq qarz: " + str(balance) + " so'm",
        max_tokens=120,
    )
