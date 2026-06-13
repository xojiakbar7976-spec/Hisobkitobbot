import os
import logging
import threading
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)
from database import (
    init_db, save_sale, save_payment, add_manual_debt,
    get_client_balance, get_daily_report,
    get_all_balances, get_all_clients, search_clients,
    canonical_name, name_key,
    SOURCE_NAMES,
)
from parser import parse_message, parse_balance_command
from ai_helper import ai_match_client, ai_analyze_report, ai_client_advice

TOKEN = os.environ.get("BOT_TOKEN", "")

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable topilmadi! Railway Variables bo'limida qo'shing.")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

WAIT_AMOUNT = 0

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📊 Hisobot", "💳 Barcha qarzlar"],
        ["➕ Sotuv kiritish", "📢 Eslatma"],
        ["ℹ️ Yordam"],
    ],
    resize_keyboard=True,
)


def fm(n):
    return "{:,} so'm".format(n).replace(",", " ")


def find_client(name):
    key = name_key(name)
    all_c = get_all_clients()
    # 1) Aniq moslik: aka/oka/sof farqi e'tiborsiz
    for cl in all_c:
        if name_key(cl) == key:
            return canonical_name(cl)
    # 2) AI yordamida xato yozilgan ismni topadi, LEKIN magazin nomi
    #    qo'shilgan boshqa mijozga ulab yubormaymiz: faqat so'z soni
    #    teng bo'lsa qabul qilamiz ("Abdulhay" -> "Abdulhay aka Chorsu" EMAS)
    if all_c:
        m = ai_match_client(name, all_c)
        if m and len(canonical_name(m).split()) == len(canonical_name(name).split()):
            return canonical_name(m)
    return None


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
        "💰 *Qarz/kassa (qo'lda):*\n"
        "`Abdulhay aka 500.000 qarz` — qarz qo'shish\n"
        "`Abdulhay aka 500.000 kassa` — qarzdan ayirish\n\n"
        "📋 *Buyruqlar:*\n"
        "/hisobot — bugungi hisobot\n"
        "/qarz Doston aka — mijoz qarzi\n"
        "/tolov Doston aka 500000 — to'lov\n"
        "/barchaqarz — hammaning qarzi\n\n"
        "💡 A = Alisher aka | N … = Nazarbek | Dala … = Dala",
        parse_mode="Markdown",
        reply_markup=MENU_KEYBOARD,
    )


async def cmd_eslatma(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    balances = get_all_balances()
    debtors = [b for b in balances if b["balance"] > 0]
    if not debtors:
        await update.message.reply_text("✅ Hech kimda qarz yo'q! Eslatma kerak emas.")
        return

    lines = ["📢 *Qarzdorlar eslatmasi:*\n"]
    total = 0
    for b in debtors:
        lines.append("🔴 *" + b["name"] + ":* " + fm(b["balance"]))
        total += b["balance"]
    lines.append("\n💰 *Umumiy qarz:* " + fm(total))
    lines.append("💡 Yuqoridagi mijozlardan qarzni undirishni unutmang!")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_sale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Menyu tugmalari
    if "Hisobot" in text:
        return await cmd_hisobot(update, ctx)
    if "Barcha qarzlar" in text:
        return await cmd_barcha_qarz(update, ctx)
    if "Eslatma" in text:
        return await cmd_eslatma(update, ctx)
    if "Yordam" in text:
        return await cmd_start(update, ctx)
    if "Sotuv kiritish" in text:
        await update.message.reply_text(
            "➕ *Sotuv kiritish:*\n\n"
            "Quyidagi formatda yozing:\n"
            "`N babls 10 x 60.000`\n"
            "`Dala 40x12.000`\n"
            "`A 75x6000`\n"
            "`Mijoz ismi`\n\n"
            "💡 Oxirgi qatorga mijoz ismini yozing.",
            parse_mode="Markdown",
        )
        return

    # Qo'lda qarz/kassa: "Abdulhay aka 500.000 qarz" / "Abdulhay aka 500.000 kassa"
    bal_cmd = parse_balance_command(text)
    if bal_cmd:
        name_raw, amount, action = bal_cmd
        found = find_client(name_raw) or name_raw
        if action == "qarz":
            add_manual_debt(found, amount)
            head = "➕ *" + found + "* qarziga *" + fm(amount) + "* qo'shildi."
        else:
            save_payment(found, amount, "kassa")
            head = "💵 *" + found + "* — *" + fm(amount) + "* kassaga olindi (qarzdan ayirildi)."

        d = get_client_balance(found)
        bal = d["balance"]
        if bal > 0:
            bal_line = "🔴 Qoldiq qarz: *" + fm(bal) + "*"
        elif bal < 0:
            bal_line = "🟢 Ortiqcha to'lagan: *" + fm(abs(bal)) + "*"
        else:
            bal_line = "🟢 *Qarz yo'q!*"

        await update.message.reply_text(head + "\n" + bal_line, parse_mode="Markdown")
        return

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

    client_name = find_client(client_raw) or canonical_name(client_raw)

    summary = {}
    grand_qty = 0
    grand_total = 0

    for source, label, qty, price in rows:
        total = save_sale(client_name, source, label, qty, price)
        if source not in summary:
            summary[source] = {"qty": 0, "total": 0}
        summary[source]["qty"] += qty
        summary[source]["total"] += total
        grand_qty += qty
        grand_total += total

    lines = ["✅ *" + client_name + "* — kiritildi!\n"]
    for src, d in summary.items():
        lines.append("🌿 *" + SOURCE_NAMES.get(src, src) + ":* " + str(d["qty"]) + " dona = " + fm(d["total"]))
    lines.append("\n📦 *Jami:* " + str(grand_qty) + " dona = " + fm(grand_total))
    lines.append("💳 Qarzga qo'shildi: *" + fm(grand_total) + "*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_hisobot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    day_arg = ctx.args[0] if ctx.args else None
    day, by_source, totals = get_daily_report(day_arg)

    if not by_source:
        await update.message.reply_text(day + " uchun ma'lumot yo'q.")
        return

    lines = ["📊 *" + day + " — Kunlik hisobot*\n"]
    for row in by_source:
        name = SOURCE_NAMES.get(row["source"], row["source"])
        lines.append("🌿 *" + name + "* guli: " + str(row["qty"]) + " dona = " + fm(row["total"]))

    qty_t = totals["qty"] or 0
    sum_t = totals["total"] or 0
    lines.append("\n📦 *Jami sotildi:* " + str(qty_t) + " dona")
    lines.append("💰 *Jami summa:* " + fm(sum_t))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    balances = get_all_balances()
    advice = ai_analyze_report(day, by_source, totals, balances)
    if advice:
        await update.message.reply_text("🤖 *AI tahlil:*\n\n" + advice, parse_mode="Markdown")


async def cmd_qarz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Misol: `/qarz Doston aka`", parse_mode="Markdown")
        return

    input_name = " ".join(ctx.args)
    found = find_client(input_name)
    if not found:
        await update.message.reply_text("❌ *'" + input_name + "'* topilmadi.", parse_mode="Markdown")
        return

    d = get_client_balance(found)
    bal = d["balance"]

    lines = ["👤 *" + found + "*\n"]
    lines.append("📦 Umumiy qarz:  " + fm(d["debt"]))
    lines.append("✅ To'lagan:      " + fm(d["paid"]))
    if bal > 0:
        lines.append("🔴 *Qoldiq qarz: " + fm(bal) + "*")
    elif bal < 0:
        lines.append("🟢 *Ortiqcha to'lagan: " + fm(abs(bal)) + "*")
    else:
        lines.append("🟢 *Qarz yo'q!*")

    if d["sales_history"]:
        lines.append("\n📋 *Oxirgi sotuvlar:*")
        for s in d["sales_history"][:5]:
            lines.append("  " + s["date"] + " | " + s["label"] + " | " + str(s["quantity"]) + "x" + str(s["price"]) + " = " + fm(s["total"]))

    if d["pay_history"]:
        lines.append("\n💸 *Oxirgi to'lovlar:*")
        for p in d["pay_history"]:
            lines.append("  " + p["date"] + " | " + fm(p["amount"]))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    if bal > 500000:
        advice = ai_client_advice(found, bal)
        if advice:
            await update.message.reply_text("🤖 *AI maslahat:*\n" + advice, parse_mode="Markdown")


async def cmd_tolov(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Misol: `/tolov Doston aka 500000`", parse_mode="Markdown")
        return ConversationHandler.END

    args = ctx.args
    try:
        amount = int(args[-1].replace(".", "").replace(",", "").replace(" ", ""))
        input_name = " ".join(args[:-1])
    except ValueError:
        input_name = " ".join(args)
        ctx.user_data["tolov_client"] = input_name
        await update.message.reply_text("💰 *" + input_name + "* uchun summa yozing:", parse_mode="Markdown")
        return WAIT_AMOUNT

    found = find_client(input_name) or input_name
    save_payment(found, amount)
    d = get_client_balance(found)
    await update.message.reply_text(
        "✅ *" + found + "* — " + fm(amount) + " qabul qilindi!\n"
        "🔴 Qoldiq qarz: *" + fm(d["balance"]) + "*",
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
        "✅ *" + found + "* — " + fm(amount) + " qabul qilindi!\n"
        "🔴 Qoldiq qarz: *" + fm(d["balance"]) + "*",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


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
        lines.append(emoji + " *" + b["name"] + ":* " + fm(b["balance"]))
        total += b["balance"]

    lines.append("\n💰 *Umumiy qarz:* " + fm(total))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def run_flask():
    from web import create_app
    flask_app = create_app()
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def main():
    init_db()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log.info("Health server ishga tushdi.")

    app = ApplicationBuilder().token(TOKEN).build()

    tolov_conv = ConversationHandler(
        entry_points=[CommandHandler("tolov", cmd_tolov)],
        states={WAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tolov_amount)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hisobot", cmd_hisobot))
    app.add_handler(CommandHandler("qarz", cmd_qarz))
    app.add_handler(CommandHandler("barchaqarz", cmd_barcha_qarz))
    app.add_handler(tolov_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sale))

    log.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
