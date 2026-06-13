import os
import re
import psycopg2
import psycopg2.extras
from datetime import date, datetime

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS client_groups (
            id          SERIAL PRIMARY KEY,
            chat_id     BIGINT  UNIQUE NOT NULL,
            title       TEXT,
            client_name TEXT,
            client_key  TEXT,
            active      BOOLEAN DEFAULT TRUE,
            last_seen   TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS today_flowers (
            id         SERIAL PRIMARY KEY,
            file_id    TEXT NOT NULL,
            caption    TEXT,
            active     BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS flower_broadcasts (
            flower_id  INTEGER NOT NULL,
            chat_id    BIGINT  NOT NULL,
            message_id BIGINT  NOT NULL,
            PRIMARY KEY (flower_id, chat_id)
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


# ---------------------------------------------------------------------------
# Sozlamalar (admin id, karta)
# ---------------------------------------------------------------------------

DEFAULT_CARD_NUMBER = "5614 6822 1430 1048"
DEFAULT_CARD_NAME = "Xojiakbar Nasrullaev"


def get_setting(key, default=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO settings (key,value) VALUES (%s,%s) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_admin_id():
    v = get_setting("admin_id")
    return int(v) if v else None


def set_admin_id(admin_id):
    set_setting("admin_id", str(admin_id))


def get_card():
    return (
        get_setting("card_number", DEFAULT_CARD_NUMBER),
        get_setting("card_name", DEFAULT_CARD_NAME),
    )


def set_card(number, name):
    set_setting("card_number", number)
    set_setting("card_name", name)


# ---------------------------------------------------------------------------
# Mijoz guruhlari (chat_id <-> mijoz)
# ---------------------------------------------------------------------------

def title_key(title):
    """Guruh nomidan emoji/belgilarni olib, solishtirish kalitini chiqaradi."""
    if not title:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", title, flags=re.UNICODE)
    return name_key(cleaned)


def record_group(chat_id, title):
    """Guruhdan xabar kelganda chat_id va nomini eslab qoladi (bog'lamasdan)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO client_groups (chat_id,title,last_seen,active) VALUES (%s,%s,%s,TRUE) "
        "ON CONFLICT (chat_id) DO UPDATE SET title=EXCLUDED.title, "
        "last_seen=EXCLUDED.last_seen, active=TRUE",
        (chat_id, title, datetime.utcnow())
    )
    conn.commit()
    conn.close()


def bind_group(chat_id, title, client_name):
    """Guruhni aniq bir mijozga bog'laydi."""
    cn = canonical_name(client_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO client_groups (chat_id,title,client_name,client_key,last_seen,active) "
        "VALUES (%s,%s,%s,%s,%s,TRUE) "
        "ON CONFLICT (chat_id) DO UPDATE SET title=EXCLUDED.title, "
        "client_name=EXCLUDED.client_name, client_key=EXCLUDED.client_key, "
        "last_seen=EXCLUDED.last_seen, active=TRUE",
        (chat_id, title, cn, name_key(client_name), datetime.utcnow())
    )
    conn.commit()
    conn.close()
    return cn


def get_group_client(chat_id):
    """Guruh qaysi mijozga bog'langan (yoki None)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT client_name FROM client_groups WHERE chat_id=%s", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def get_group_for_client(client_name):
    """Mijoz uchun guruh chat_id'sini topadi: avval aniq bog'lash, keyin nom bo'yicha."""
    key = name_key(client_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT chat_id, title, client_key FROM client_groups WHERE active=TRUE")
    rows = c.fetchall()
    conn.close()
    for chat_id, title, ckey in rows:
        if ckey and ckey == key:
            return chat_id
    for chat_id, title, ckey in rows:
        if title_key(title) == key:
            return chat_id
    return None


def list_active_groups():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT chat_id FROM client_groups WHERE active=TRUE")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def deactivate_group(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE client_groups SET active=FALSE WHERE chat_id=%s", (chat_id,))
    conn.commit()
    conn.close()


def _client_variants(client_name):
    """Mijozning barcha ko'rinishlari (aka/oka/sof) — kichik harfda."""
    key = name_key(client_name)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT DISTINCT client_name FROM sales UNION SELECT DISTINCT client_name FROM payments")
    variants = [r[0] for r in c.fetchall() if name_key(r[0]) == key]
    conn.close()
    if not variants:
        variants = [client_name]
    return [v.lower() for v in variants]


def get_client_history(client_name, limit=30):
    """Mijoz olgan gullar (qarz qatorlarisiz), sana bo'yicha."""
    names = _client_variants(client_name)
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute(
        "SELECT date,label,quantity,price,total FROM sales "
        "WHERE LOWER(client_name)=ANY(%s) AND source<>'qarz' ORDER BY id DESC LIMIT %s",
        (names, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Bugungi chiqgan gullar (rasmlar)
# ---------------------------------------------------------------------------

def add_flower(file_id, caption=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO today_flowers (file_id,caption,active,created_at) "
        "VALUES (%s,%s,TRUE,%s) RETURNING id",
        (file_id, caption, datetime.utcnow())
    )
    fid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return fid


def get_active_flowers():
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id,file_id,caption FROM today_flowers WHERE active=TRUE ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows


def get_flower(flower_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id,file_id,caption,active FROM today_flowers WHERE id=%s", (flower_id,))
    row = c.fetchone()
    conn.close()
    return row


def deactivate_flower(flower_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE today_flowers SET active=FALSE WHERE id=%s", (flower_id,))
    conn.commit()
    conn.close()


def clear_flowers():
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE today_flowers SET active=FALSE WHERE active=TRUE")
    conn.commit()
    conn.close()


def record_broadcast(flower_id, chat_id, message_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO flower_broadcasts (flower_id,chat_id,message_id) VALUES (%s,%s,%s) "
        "ON CONFLICT (flower_id,chat_id) DO UPDATE SET message_id=EXCLUDED.message_id",
        (flower_id, chat_id, message_id)
    )
    conn.commit()
    conn.close()


def get_broadcasts(flower_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT chat_id,message_id FROM flower_broadcasts WHERE flower_id=%s", (flower_id,))
    rows = c.fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]
