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
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO payments (date,client_name,amount,note) VALUES (%s,%s,%s,%s)",
        (str(date.today()), client_name, amount, note)
    )
    conn.commit()
    conn.close()


def get_client_balance(client_name):
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    c.execute(
        "SELECT COALESCE(SUM(total),0) as v FROM sales WHERE LOWER(client_name)=LOWER(%s)",
        (client_name,)
    )
    debt = c.fetchone()["v"]

    c.execute(
        "SELECT COALESCE(SUM(amount),0) as v FROM payments WHERE LOWER(client_name)=LOWER(%s)",
        (client_name,)
    )
    paid = c.fetchone()["v"]

    c.execute(
        "SELECT date,label,quantity,price,total FROM sales WHERE LOWER(client_name)=LOWER(%s) ORDER BY id DESC LIMIT 10",
        (client_name,)
    )
    sales_hist = c.fetchall()

    c.execute(
        "SELECT date,amount,note FROM payments WHERE LOWER(client_name)=LOWER(%s) ORDER BY id DESC LIMIT 5",
        (client_name,)
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
        "SELECT source, SUM(quantity) as qty, SUM(total) as total FROM sales WHERE date=%s GROUP BY source",
        (day,)
    )
    by_source = c.fetchall()

    c.execute(
        "SELECT SUM(quantity) as qty, SUM(total) as total FROM sales WHERE date=%s",
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
        "FROM sales ORDER BY id DESC LIMIT %s",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_balances():
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    c.execute("SELECT client_name, SUM(total) as debt FROM sales GROUP BY LOWER(client_name), client_name")
    rows = c.fetchall()

    result = []
    for row in rows:
        name = row["client_name"]
        c.execute(
            "SELECT COALESCE(SUM(amount),0) as v FROM payments WHERE LOWER(client_name)=LOWER(%s)",
            (name,)
        )
        paid = c.fetchone()["v"]
        balance = row["debt"] - paid
        result.append({"name": name, "balance": balance})

    conn.close()
    return sorted(result, key=lambda x: x["balance"], reverse=True)


def get_all_clients():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT DISTINCT client_name FROM sales ORDER BY client_name")
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
