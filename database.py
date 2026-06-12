import sqlite3
from datetime import date

DB_NAME = "flower.db"

# Manba nomlari
SOURCE_NAMES = {
    "A": "Alisher aka",
    "N": "Nazarbek",
    "dala": "Dala",
}

def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            client_name TEXT    NOT NULL,
            source      TEXT    NOT NULL,   -- 'A' | 'N' | 'dala'
            label       TEXT    NOT NULL,   -- original label, e.g. 'N babls', 'Dala red'
            quantity    INTEGER NOT NULL,
            price       INTEGER NOT NULL,
            total       INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            client_name TEXT    NOT NULL,
            amount      INTEGER NOT NULL,
            note        TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_sale(client_name: str, source: str, label: str, quantity: int, price: int) -> int:
    total = quantity * price
    conn = get_conn()
    conn.execute(
        "INSERT INTO sales (date,client_name,source,label,quantity,price,total) VALUES (?,?,?,?,?,?,?)",
        (str(date.today()), client_name, source, label, quantity, price, total)
    )
    conn.commit()
    conn.close()
    return total

def save_payment(client_name: str, amount: int, note: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO payments (date,client_name,amount,note) VALUES (?,?,?,?)",
        (str(date.today()), client_name, amount, note)
    )
    conn.commit()
    conn.close()

def get_client_balance(client_name: str) -> dict:
    conn = get_conn()
    debt = conn.execute(
        "SELECT COALESCE(SUM(total),0) as v FROM sales WHERE LOWER(client_name)=LOWER(?)",
        (client_name,)
    ).fetchone()["v"]
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as v FROM payments WHERE LOWER(client_name)=LOWER(?)",
        (client_name,)
    ).fetchone()["v"]
    sales_hist = conn.execute(
        """SELECT date,label,quantity,price,total FROM sales
           WHERE LOWER(client_name)=LOWER(?) ORDER BY id DESC LIMIT 10""",
        (client_name,)
    ).fetchall()
    pay_hist = conn.execute(
        """SELECT date,amount,note FROM payments
           WHERE LOWER(client_name)=LOWER(?) ORDER BY id DESC LIMIT 5""",
        (client_name,)
    ).fetchall()
    conn.close()
    return {
        "debt": debt,
        "paid": paid,
        "balance": debt - paid,
        "sales_history": sales_hist,
        "pay_history": pay_hist,
    }

def get_daily_report(day: str = None) -> tuple:
    if day is None:
        day = str(date.today())
    conn = get_conn()
    by_source = conn.execute(
        """SELECT source, SUM(quantity) as qty, SUM(total) as total
           FROM sales WHERE date=? GROUP BY source""",
        (day,)
    ).fetchall()
    totals = conn.execute(
        "SELECT SUM(quantity) as qty, SUM(total) as total FROM sales WHERE date=?",
        (day,)
    ).fetchone()
    conn.close()
    return day, by_source, totals

def get_all_balances() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT client_name, SUM(total) as debt FROM sales GROUP BY LOWER(client_name)"
    ).fetchall()
    result = []
    for row in rows:
        name = row["client_name"]
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as v FROM payments WHERE LOWER(client_name)=LOWER(?)",
            (name,)
        ).fetchone()["v"]
        balance = row["debt"] - paid
        result.append({"name": name, "balance": balance})
    conn.close()
    return sorted(result, key=lambda x: x["balance"], reverse=True)

def get_all_clients() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT client_name FROM sales ORDER BY client_name"
    ).fetchall()
    conn.close()
    return [r["client_name"] for r in rows]

def search_clients(query: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT client_name FROM sales WHERE LOWER(client_name) LIKE LOWER(?)",
        (f"%{query}%",)
    ).fetchall()
    conn.close()
    return [r["client_name"] for r in rows]
