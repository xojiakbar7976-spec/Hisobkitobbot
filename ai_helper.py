import os
import json
import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"

def _claude(system: str, user: str, max_tokens: int = 400) -> str | None:
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
                "model": "claude-sonnet-4-20250514",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=15,
        )
        return resp.json()["content"][0]["text"].strip()
    except Exception:
        return None


def ai_match_client(input_name: str, all_clients: list[str]) -> str | None:
    """Noto'g'ri yozilgan mijoz ismini topadi."""
    if not all_clients:
        return None
    # Avval oddiy substring search
    low = input_name.lower()
    for c in all_clients:
        if low in c.lower() or c.lower() in low:
            return c
    # Keyin AI
    result = _claude(
        system=(
            "Sen O'zbek ismlarini taniy oluvchi yordamchisan. "
            "Foydalanuvchi mijoz ismini noto'g'ri yozishi mumkin. "
            "Ro'yxatdan eng mos ismni qaytар. Faqat ismni yoz. "
            "Mos kelmasa faqat 'YOQ' yoz."
        ),
        user=f"Ro'yxat:\n{chr(10).join(all_clients)}\n\nYozilgan: {input_name}",
        max_tokens=50,
    )
    if result and result != "YOQ" and result in all_clients:
        return result
    return None


def ai_analyze_report(day: str, by_source: list, totals, balances: list) -> str | None:
    """Kunlik hisobotni tahlil qiladi."""
    from database import SOURCE_NAMES
    src_lines = []
    for row in by_source:
        name = SOURCE_NAMES.get(row["source"], row["source"])
        src_lines.append(f"{name}: {row['qty']} dona, {row['total']:,} so'm")
    top3 = [b for b in balances if b["balance"] > 0][:3]
    debtors = ", ".join(f"{b['name']} ({b['balance']:,} so'm)" for b in top3)

    return _claude(
        system=(
            "Sen gul optom savdosi bo'yicha qisqa tahlilchi san. "
            "O'zbek tilida, 3-5 gapda, aniq va foydali tahlil ber. "
            "Emoji ishlatma."
        ),
        user=(
            f"Sana: {day}\n"
            f"Manba bo'yicha:\n" + "\n".join(src_lines) + "\n"
            f"Jami: {totals['qty']} dona, {totals['total']:,} so'm\n"
            f"Eng katta qarzdorlar: {debtors or 'yo\'q'}"
        ),
        max_tokens=300,
    )


def ai_client_advice(client_name: str, balance: int) -> str | None:
    """Mijoz qarzi bo'yicha qisqa maslahat."""
    return _claude(
        system=(
            "Sen savdo moliyaviy maslahatchisi san. "
            "O'zbek tilida, 2 gapda, aniq maslahat ber. Emoji ishlatma."
        ),
        user=f"Mijoz: {client_name}\nQoldiq qarz: {balance:,} so'm",
        max_tokens=120,
    )
