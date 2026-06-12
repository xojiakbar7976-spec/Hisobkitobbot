import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)
from database import (
    init_db, save_sale, save_payment,
    get_client_balance, get_daily_report,
    get_all_balances, get_all_clients, search_clients,
    SOURCE_NAMES,
)
from parser import parse_message
from ai_helper import ai_match_client, ai_analyze_report, ai_client_advice

TOKEN = os.environ.get("BOT_TOKEN", "")

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable topilmadi! Railway Variables bo'limida qo'shing.")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

WAIT_AMOUNT = 0  # ConversationHandler state


# ── formatlovchi ──────────────────────────────────────
def fm(n: int) -> str:
    """1500000  →  1 500 000 so'm"""
    return f"{n:,} so'm".replace(",", " ")


# ── mijoz qidirish ────────────────────────────────────
def find_client(name: str) -> str | None:
    matches = search_clients(name)
    if matches:
        return matches[0]
    all_c = get_all_clients()
    if all_c:
        return ai_match_client(name, all_c)
    return None


# ── /start ────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌸 *Gul Savdo Boti*\n\n"
        "📌 *Sotuv kiritish:*\n"
        "`N babls 10 x 60.000`\n"
        "`N bomb 6x150.000`\n"
        "`Dala 40 x 12.000`\n"
        "`Dala red 30x20.000`\n"
        "`A 75x6.000`\n"
        "`Mijoz ismi`\n\n"
        "📋 *Buyruqlar:*\n"
        "/hisobot — bugungi hisobot\n"
        "/qarz Doston aka — mijoz qarzi\n"
        "/tolov Doston aka 500000 — to'lov\n"
        "/barchaqarz — hammaning qarzi\n\n"
        "💡 A = Alisher aka | N … = Nazarbek | Dala … = Dala",
        parse_mode="Markdown",
    )


# ── sotuv xabarini qabul qilish ───────────────────────
async def handle_sale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    result = parse_message(text)

    if result is None:
        await update.message.reply_text(
            "❓ Format tanilmadi.\n\n"
            "To'g'ri misol:\n"
            "`N babls 10 x 60.000`\n"
            "`Dala 40x12.000`\n"
            "`A 75x6000`\n"
            "`Mijoz ismi`",
            parse_mode="Markdown",
        )
        return

    client_raw, rows = result

    all_c = get_all_clients()
    if all_c:
        matched = ai_match_client(client_raw, all_c)
        client_name = matched if matched else client_raw
    else:
        client_name = client_raw

    summary: dict[str, dict] = {}
    grand_qty = 0
    grand_total = 0

    for source, label, qty, price in rows:
        total = save_sale(client_name, source, label, qty, price)
        if source not in summary:
            summary[source] = {"qty": 0, "total": 0}
        summary[source]["qty"]   += qty
        summary[source]["total"] += total
        grand_qty  += qty
        grand_total += total

    lines = [f"✅ *{client_name}* — kiritildi!\n"]
    for src, d in summary.items():
        lines.append(f"🌿 *{SOURCE_NAMES[src]}:* {d['qty']} dona = {fm(d['total'])}")
    lines.append(f"\n📦 *Jami:* {grand_qty} dona = {fm(grand_total)}")
    lines.append(f"💳 Qarzga qo'shildi: *{fm(grand_total)}*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /hisobot ─────────────────────────────────────────
async def cmd_hisobot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    day_arg = ctx.args[0] if ctx.args else None
    day, by_source, totals = get_daily_report(day_arg)

    if not by_source:
        await update.message.reply_text(f"📭 {day} uchun ma'lumot yo'q.")
        return

    lines = [f"📊 *{day} — Kunlik hisobot*\n"]
    for row in by_source:
        name = SOURCE_NAMES.get(row["source"], row["source"])
        lines.append(f"🌿 *{name}* guli: {row['qty']} dona = {fm(row['total'])}")

    qty_t = totals["qty"] or 0
    sum_t = totals["total"] or 0
    lines.append(f"\n📦 *Jami sotildi:* {qty_t} dona")
    lines.append(f"💰 *Jami summa:* {fm(sum_t)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    balances = get_all_balances()
    advice = ai_analyze_report(day, by_source, totals, balances)
    if advice:
        await update.message.reply_text(f"🤖 *AI tahlil:*\n\n{advice}", parse_mode="Markdown")


# ── /qarz ────────────────────────────────────────────
async def cmd_qarz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Misol: `/qarz Doston aka`", parse_mode="Markdown")
        return

    input_name = " ".join(ctx.args)
    found = find_client(input_name)
    if not found:
        await update.message.reply_text(f"❌ *'{input_name}'* topilmadi.", parse_mode="Markdown")
        return

    d = get_client_balance(found)
    bal = d["balance"]

    lines = [f"👤 *{found}*\n"]
    lines.append(f"📦 Umumiy qarz:  {fm(d['debt'])}")
    lines.append(f"✅ To'lagan:      {fm(d['paid'])}")
    if bal > 0:
        lines.append(f"🔴 *Qoldiq qarz: {fm(bal)}*")
    elif bal < 0:
        lines.append(f"🟢 *Ortiqcha to'lagan: {fm(abs(bal))}*")
    else:
        lines.append("🟢 *Qarz yo'q!*")

    if d["sales_history"]:
        lines.append("\n📋 *Oxirgi sotuvlar:*")
        for s in d["sales_history"][:5]:
            lines.append(f"  {s['date']} | {s['label']} | {s['quantity']}×{s['price']:,} = {fm(s['total'])}")

    if d["pay_history"]:
        lines.append("\n💸 *Oxirgi to'lovlar:*")
        for p in d["pay_history"]:
            lines.append(f"  {p['date']} | {fm(p['amount'])}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    if bal > 500_000:
        advice = ai_client_advice(found, bal)
        if advice:
            await update.message.reply_text(f"🤖 *AI maslahat:*\n{advice}", parse_mode="Markdown")


# ── /tolov ───────────────────────────────────────────
async def cmd_tolov(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Misol: `/tolov Doston aka 500000`", parse_mode="Markdown"
        )
        return ConversationHandler.END

    args = ctx.args
    try:
        amount = int(args[-1].replace(".", "").replace(",", "").replace(" ", ""))
        input_name = " ".join(args[:-1])
    except ValueError:
        input_name = " ".join(args)
        ctx.user_data["tolov_client"] = input_name
        await update.message.reply_text(f"💰 *{input_name}* uchun summa yozing:", parse_mode="Markdown")
        return WAIT_AMOUNT

    found = find_client(input_name) or input_name
    save_payment(found, amount)
    d = get_client_balance(found)
    await update.message.reply_text(
        f"✅ *{found}* — {fm(amount)} qabul qilindi!\n"
        f"🔴 Qoldiq qarz: *{fm(d['balance'])}*",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def tolov_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.replace(".", "").replace(",", "").replace(" ", ""))
    except ValueError:
        await update.message.reply_text("❌ Faqat raqam kiriting!")
        return WAIT_AMOUNT

    input_name = ctx.user_data.get("tolov_client", "")
    found = find_client(input_name) or input_name
    save_payment(found, amount)
    d = get_client_balance(found)
    await update.message.reply_text(
        f"✅ *{found}* — {fm(amount)} qabul qilindi!\n"
        f"🔴 Qoldiq qarz: *{fm(d['balance'])}*",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ── /barchaqarz ──────────────────────────────────────
async def cmd_barcha_qarz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    balances = get_all_balances()
    if not balances:
        await update.message.reply_text("✅ Hech kimda qarz yo'q!")
        return

    lines = ["📋 *Barcha mijozlar qarzi:*\n"]
    total = 0
    for b in balances:
        if b["balance"] == 0:
            continue
        emoji = "🔴" if b["balance"] > 0 else "🟢"
        lines.append(f"{emoji} *{b['name']}:* {fm(b['balance'])}")
        total += b["balance"]

    lines.append(f"\n💰 *Umumiy qarz:* {fm(total)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── main ─────────────────────────────────────────────
def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    tolov_conv = ConversationHandler(
        entry_points=[CommandHandler("tolov", cmd_tolov)],
        states={WAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tolov_amount)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("hisobot",    cmd_hisobot))
    app.add_handler(CommandHandler("qarz",       cmd_qarz))
    app.add_handler(CommandHandler("barchaqarz", cmd_barcha_qarz))
    app.add_handler(tolov_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sale))

    # Railway port talabini qondirish uchun Flask health server
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def health():
        return "OK", 200

    port = int(os.environ.get("PORT", 8080))
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=port),
        daemon=True,
    )
    flask_thread.start()
    log.info(f"Health server port {port} da ishga tushdi.")

    log.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
