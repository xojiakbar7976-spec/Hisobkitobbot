import re
from typing import Optional

# "son x narx" namunasi: 50x2000, 150 x 3000, 30×12000
_CALC = re.compile(r'(\d[\d.,]*)\s*[xX\xd7]\s*(\d[\d.,]*)')


def _num(s: str) -> int:
    return int(s.replace(".", "").replace(",", "").replace(" ", ""))


def _source_key(line: str) -> str:
    parts = line.strip().split()
    if not parts:
        return "?"
    first = parts[0].upper()
    if first == "A":
        return "A"
    if first.startswith("DALA") or first == "D":
        return "dala"
    if first[0] == "N":
        return "N"
    return "?"


def parse_message(text: str) -> Optional[tuple]:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None

    sale_rows = []
    non_sale = []

    for line in lines:
        calcs = list(_CALC.finditer(line))
        if calcs:
            last = calcs[-1]  # hisob-kitob odatda satr oxirida bo'ladi
            qty = _num(last.group(1))
            price = _num(last.group(2))
            source = _source_key(line)
            label = line[:last.start()].strip() or line
            sale_rows.append((source, label, qty, price))
        else:
            # "x" yo'q satr — ortiqcha yozuv, o'tkazib yuboriladi
            non_sale.append(line)

    if not sale_rows:
        return None

    # oxirgi "x"siz satr — mijoz ismi
    client_name = non_sale[-1] if non_sale else None
    if not client_name:
        return None

    return client_name, sale_rows
