import re
from typing import Optional


def _num(s: str) -> int:
    return int(s.replace(".", "").replace(",", "").replace(" ", ""))


_ROW = re.compile(
    r'^'
    r'(A|N(?:\s+\S+)?|[Dd][Aa][Ll][Aa](?:\s+\S+)?)'
    r'\s+'
    r'(\d[\d.,]*)'
    r'\s*[xX\xd7]\s*'
    r'(\d[\d.,]*)'
    r'\s*$'
)


def _source_key(raw: str) -> str:
    upper = raw.strip().upper()
    if upper == "A":
        return "A"
    if upper.startswith("N"):
        return "N"
    if upper.startswith("D"):
        return "dala"
    return "?"


def parse_message(text: str) -> Optional[tuple]:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None

    sale_rows = []
    non_sale = []

    for line in lines:
        m = _ROW.match(line)
        if m:
            raw_src = m.group(1).strip()
            qty = _num(m.group(2))
            price = _num(m.group(3))
            source = _source_key(raw_src)
            label = raw_src
            sale_rows.append((source, label, qty, price))
        else:
            non_sale.append(line)

    if not sale_rows:
        return None

    client_name = non_sale[-1] if non_sale else None
    if not client_name:
        return None

    return client_name, sale_rows
