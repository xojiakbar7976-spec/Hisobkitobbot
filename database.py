import os
import psycopg2
import psycopg2.extras
from datetime import date

DATABASE_URL = os.environ.get("DATABASE_URL", "")

SOURCE_NAMES = {
    "A": "Alisher aka",
    "N": "Nazarbek",
    "dala": "Dala",
    "?": "Boshqa",
}

# Ism oxiridagi hurmat so'zlari (Abdulhay aka / Abdulhay oka / Abdulhay = bitta mijoz)
HONORIFICS = {"aka", "oka", "ako"}


def canonical_name(name):
    """Ism oxiridagi 'aka'/'oka' kabi so'zlarni olib tashlaydi.
    Shunda 'Abdulhay aka', 'Abdulhay oka', 'Abdulhay' — bitta mijoz bo'ladi.
    Bosh harflar saqlanadi."""
    if not name:
        return name
    parts = name.strip().split()
    while len(parts) > 1 and parts[-1].lower().strip(".,") in HONORIFICS:
        parts.pop()
    return " ".join(parts) if parts else name.strip()


def name_key(name):
    """Solishtirish uchun: kichik harf + hurmat so'zisiz."""
    return canonical_name(name).lower()


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id          SERIAL PRIMARY KEY,
            date        TEXT    NOT NULL,
            client_name TEXT    NOT NULL,
            source      TEXT    NOT NULL,
            label       TEXT    NOT NULL,
            quantity    INTEGER NOT NULL,
            price       INTEGER NOT NULL,
            total       INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id          SERIAL PRIMARY KEY,
            date        TEXT    NOT NULL,
            client_name TEXT    NOT NULL,
            amount      INTEGER NOT NULL,
            note        TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_sale(client_name, source, label, quantity, price):
    total = quantity * price
    client_name = canonical_name(client_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO sales (date,client_name,source,label,quantity,price,total) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (str(date.today()), client_name, source, label, quantity, price, total)
    )
    conn.commit()
    conn.close()
    return total


def save_payment(client_name, amount, note=""):
    client_name = canonical_name(client_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO payments (date,client_name,amount,note) VALUES (%s,%s,%s,%s)",
        (str(date.today()), client_name, amount, note)
    )
    conn.commit()
    conn.close()


def add_manual_debt(client_name, amount, note="Qarz"):
    """Qo'lda qarz qo'shish: mijoz qarzini amount'ga oshiradi.
    Kunlik gul hisobotiga kirmasligi uchun source='qarz' bilan saqlanadi."""
    client_name = canonical_name(client_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO sales (date,client_name,source,label,quantity,price,total) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (str(date.today()), client_name, "qarz", note, 1, amount, amount)
    )
    conn.commit()
    conn.close()
    return amount


def get_client_balance(client_name):
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Bir mijozning barcha ko'rinishlari (aka/oka/sof) — birga hisoblanadi
    key = name_key(client_name)
    c.execute("SELECT DISTINCT client_name FROM sales UNION SELECT DISTINCT client_name FROM payments")
    variants = [r["client_name"] for r in c.fetchall() if name_key(r["client_name"]) == key]
    if not variants:
        variants = [client_name]
    names = [v.lower() for v in variants]

    c.execute(
        "SELECT COALESCE(SUM(total),0) as v FROM sales WHERE LOWER(client_name)=ANY(%s)",
        (names,)
    )
    debt = c.fetchone()["v"]

    c.execute(
        "SELECT COALESCE(SUM(amount),0) as v FROM payments WHERE LOWER(client_name)=ANY(%s)",
        (names,)
    )
    paid = c.fetchone()["v"]

    c.execute(
        "SELECT date,label,quantity,price,total FROM sales WHERE LOWER(client_name)=ANY(%s) ORDER BY id DESC LIMIT 10",
        (names,)
    )
    sales_hist = c.fetchall()

    c.execute(
        "SELECT date,amount,note FROM payments WHERE LOWER(client_name)=ANY(%s) ORDER BY id DESC LIMIT 5",
        (names,)
    )
    pay_hist = c.fetchall()

    conn.close()
    return {
        "debt": debt,
        "paid": paid,
        "balance": debt - paid,
        "sales_history": sales_hist,
        "pay_history": pay_hist,
    }


def get_daily_report(day=None):
    if day is None:
        day = str(date.today())
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    c.execute(
        "SELECT source, SUM(quantity) as qty, SUM(total) as total FROM sales WHERE date=%s AND source<>'qarz' GROUP BY source",
        (day,)
    )
    by_source = c.fetchall()

    c.execute(
        "SELECT SUM(quantity) as qty, SUM(total) as total FROM sales WHERE date=%s AND source<>'qarz'",
        (day,)
    )
    totals = c.fetchone()
    conn.close()
    return day, by_source, totals


def get_recent_sales(limit=50):
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute(
        "SELECT date, client_name, source, label, quantity, price, total "
        "FROM sales WHERE source<>'qarz' ORDER BY id DESC LIMIT %s",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_balances():
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    c.execute("SELECT client_name, SUM(total) as debt FROM sales GROUP BY client_name")
    sales_rows = c.fetchall()
    c.execute("SELECT client_name, SUM(amount) as paid FROM payments GROUP BY client_name")
    pay_rows = c.fetchall()
    conn.close()

    # aka/oka/sof ko'rinishlarni bitta mijozga birlashtiramiz
    groups = {}

    def grp(nm):
        k = name_key(nm)
        if k not in groups:
            groups[k] = {"name": canonical_name(nm), "debt": 0, "paid": 0}
        return groups[k]

    for row in sales_rows:
        grp(row["client_name"])["debt"] += row["debt"] or 0
    for row in pay_rows:
        grp(row["client_name"])["paid"] += row["paid"] or 0

    result = [
        {"name": g["name"], "balance": g["debt"] - g["paid"]}
        for g in groups.values()
    ]
    return sorted(result, key=lambda x: x["balance"], reverse=True)


def get_all_clients():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT client_name FROM sales "
        "UNION SELECT DISTINCT client_name FROM payments "
        "ORDER BY client_name"
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def search_clients(query):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT client_name FROM sales WHERE LOWER(client_name) LIKE LOWER(%s)",
        ("%" + query + "%",)
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]
