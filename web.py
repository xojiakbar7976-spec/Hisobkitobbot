import os
from functools import wraps
from datetime import datetime, timezone, timedelta

from flask import Flask, request, Response, render_template_string

from database import (
    get_daily_report,
    get_all_balances,
    get_recent_sales,
    SOURCE_NAMES,
)


def fm(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    return "{:,}".format(n).replace(",", " ")


PAGE = """
<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>🌸 Gul Savdo — Boshqaruv paneli</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f4f6f8; color: #1f2933; padding: 0 0 40px;
  }
  header {
    background: linear-gradient(135deg, #ec4899 0%, #16a34a 100%);
    color: #fff; padding: 22px 18px; box-shadow: 0 2px 10px rgba(0,0,0,.12);
  }
  header h1 { font-size: 20px; font-weight: 700; }
  header p { font-size: 13px; opacity: .92; margin-top: 4px; }
  .wrap { max-width: 920px; margin: 0 auto; padding: 16px; }
  .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 22px; }
  @media (max-width: 600px) { .cards { grid-template-columns: 1fr; } }
  .card {
    background: #fff; border-radius: 14px; padding: 16px;
    box-shadow: 0 1px 6px rgba(0,0,0,.06);
  }
  .card .label { font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: .4px; }
  .card .value { font-size: 24px; font-weight: 700; margin-top: 6px; }
  .card .sub { font-size: 12px; color: #9ca3af; margin-top: 2px; }
  .green .value { color: #16a34a; }
  .red .value { color: #dc2626; }
  .pink .value { color: #ec4899; }
  section { background: #fff; border-radius: 14px; padding: 16px; margin-bottom: 18px; box-shadow: 0 1px 6px rgba(0,0,0,.06); }
  section h2 { font-size: 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
  th { color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: .3px; }
  td.num, th.num { text-align: right; }
  .scroll { overflow-x: auto; }
  .debt { color: #dc2626; font-weight: 700; }
  .credit { color: #16a34a; font-weight: 700; }
  .empty { color: #9ca3af; padding: 18px 4px; text-align: center; font-size: 14px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; background: #eef2ff; color: #4338ca; }
  footer { text-align: center; color: #9ca3af; font-size: 12px; margin-top: 8px; }
</style>
</head>
<body>
<header>
  <h1>🌸 Gul Savdo — Boshqaruv paneli</h1>
  <p>Sana: {{ day }} · Yangilangan: {{ updated }} (Toshkent) · har 60 soniyada yangilanadi</p>
</header>

<div class="wrap">

  <div class="cards">
    <div class="card green">
      <div class="label">Bugungi savdo</div>
      <div class="value">{{ fm(today_total) }}</div>
      <div class="sub">{{ today_qty }} dona sotildi</div>
    </div>
    <div class="card red">
      <div class="label">Umumiy qarz</div>
      <div class="value">{{ fm(total_debt) }}</div>
      <div class="sub">so'm</div>
    </div>
    <div class="card pink">
      <div class="label">Qarzdorlar</div>
      <div class="value">{{ debtors|length }}</div>
      <div class="sub">mijoz</div>
    </div>
  </div>

  <section>
    <h2>📊 Bugungi hisobot</h2>
    {% if by_source %}
    <div class="scroll">
    <table>
      <thead><tr><th>Manba</th><th class="num">Soni</th><th class="num">Summa</th></tr></thead>
      <tbody>
        {% for row in by_source %}
        <tr>
          <td>{{ SOURCE_NAMES.get(row.source, row.source) }}</td>
          <td class="num">{{ row.qty }}</td>
          <td class="num">{{ fm(row.total) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty">Bugun hali savdo yo'q.</div>
    {% endif %}
  </section>

  <section>
    <h2>💳 Barcha qarzlar</h2>
    {% if balances %}
    <div class="scroll">
    <table>
      <thead><tr><th>Mijoz</th><th class="num">Qoldiq</th></tr></thead>
      <tbody>
        {% for b in balances %}
          {% if b.balance != 0 %}
          <tr>
            <td>{{ b.name }}</td>
            <td class="num {{ 'debt' if b.balance > 0 else 'credit' }}">
              {{ fm(b.balance) }} {% if b.balance < 0 %}(ortiqcha){% endif %}
            </td>
          </tr>
          {% endif %}
        {% endfor %}
      </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty">Qarzdorlar yo'q. ✅</div>
    {% endif %}
  </section>

  <section>
    <h2>🧾 So'nggi sotuvlar</h2>
    {% if recent %}
    <div class="scroll">
    <table>
      <thead><tr>
        <th>Sana</th><th>Mijoz</th><th>Nav</th>
        <th class="num">Soni</th><th class="num">Narx</th><th class="num">Jami</th>
      </tr></thead>
      <tbody>
        {% for s in recent %}
        <tr>
          <td>{{ s.date }}</td>
          <td>{{ s.client_name }}</td>
          <td><span class="badge">{{ s.label }}</span></td>
          <td class="num">{{ s.quantity }}</td>
          <td class="num">{{ fm(s.price) }}</td>
          <td class="num">{{ fm(s.total) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty">Hali sotuv kiritilmagan.</div>
    {% endif %}
  </section>

  <footer>🌸 Gul Savdo Boti · Railway · PostgreSQL</footer>
</div>
</body>
</html>
"""


def _check_auth():
    pw = os.environ.get("DASHBOARD_PASSWORD", "")
    if not pw:
        return True
    auth = request.authorization
    return auth is not None and auth.password == pw


def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not _check_auth():
            return Response(
                "Parol kerak.", 401,
                {"WWW-Authenticate": 'Basic realm="Gul Savdo"'}
            )
        return f(*args, **kwargs)
    return wrapped


def create_app():
    app = Flask(__name__)

    @app.route("/health")
    def health():
        return "OK", 200

    @app.route("/")
    @require_auth
    def dashboard():
        day, by_source, totals = get_daily_report()
        balances = get_all_balances()
        recent = get_recent_sales(50)

        today_total = (totals["total"] or 0) if totals else 0
        today_qty = (totals["qty"] or 0) if totals else 0
        debtors = [b for b in balances if b["balance"] > 0]
        total_debt = sum(b["balance"] for b in debtors)

        updated = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%H:%M")

        return render_template_string(
            PAGE,
            day=day,
            updated=updated,
            by_source=by_source,
            today_total=today_total,
            today_qty=today_qty,
            balances=balances,
            debtors=debtors,
            total_debt=total_debt,
            recent=recent,
            SOURCE_NAMES=SOURCE_NAMES,
            fm=fm,
        )

    return app
