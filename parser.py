"""
parser.py — Xabarni sotuv qatorlariga ajratadi.

Qo'llab-quvvatlanadigan formatlar:
  Manba:
    A                  → Alisher aka  (faqat A, qo'shimcha so'zsiz)
    N <anything>       → Nazarbek     (N dan keyin ixtiyoriy so'z)
    Dala <anything>    → Dala         (Dala dan keyin ixtiyoriy so'z)

  Raqam formatlari (soni x narxi):
    10x60000
    10 x 60000
    10x60.000
    10 x 60.000
    10x60,000

  Mijoz ismi:
    Xabarning oxirgi qatori (sotuv pattern topilmagan qator)
"""

import re
from typing import Optional


# ── raqamni tozalash ──────────────────────────────────
def _num(s: str) -> int:
    """'60.000' | '60,000' | '60000'  →  60000"""
    return int(s.replace(".", "").replace(",", "").replace(" ", ""))


# ── bir qatorni parse qilish ──────────────────────────
_NUM = r'(\d[\d.,]*)'                          # raqam (nuqta/vergul bilan)
_SEP = r'\s*[xX×]\s*'                          # x ajratuvchi
_ROW = re.compile(
    r'^'
    r'(A|N(?:\s+\S+)?|[Dd][Aa][Ll][Aa](?:\s+\S+)?)'  # manba (gr 1)
    r'\s+'
    r'(\d[\d.,]*)'                                     # soni  (gr 2)
    r'\s*[xX×]\s*'                                     # x
    r'(\d[\d.,]*)'                                     # narxi (gr 3)
    r'\s*$'
)


def _source_key(raw: str) -> str:
    """'N babls' → 'N',  'Dala red' → 'dala',  'A' → 'A'"""
    upper = raw.strip().upper()
    if upper == "A":
        return "A"
    if upper.startswith("N"):
        return "N"
    if upper.upper().startswith("D"):
        return "dala"
    return "?"


def parse_message(text: str) -> Optional[tuple]:
    """
    Qaytaradi: (client_name, [(source, label, qty, price), ...])
    yoki None — agar format noto'g'ri bo'lsa.

    source → 'A' | 'N' | 'dala'
    label  → original yozuv, masalan 'N babls'
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None

    sale_rows = []
    non_sale  = []

    for line in lines:
        m = _ROW.match(line)
        if m:
            raw_src = m.group(1).strip()
            qty     = _num(m.group(2))
            price   = _num(m.group(3))
            source  = _source_key(raw_src)
            label   = raw_src          # e.g. 'N babls', 'Dala red', 'A'
            sale_rows.append((source, label, qty, price))
        else:
            non_sale.append(line)

    if not sale_rows:
        return None

    # Mijoz ismi: oxirgi non-sale qator
    client_name = non_sale[-1] if non_sale else None
    if not client_name:
        return None

    return client_name, sale_rows
