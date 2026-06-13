import os
import logging
import threading
from datetime import date
from telegram import (
    Update, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    CallbackQueryHandler, ChatMemberHandler,
)
from telegram.error import TelegramError
from database import (
    init_db, save_sale, save_payment, add_manual_debt,
    get_client_balance, get_daily_report,
    get_all_balances, get_all_clients, search_clients,
    canonical_name, name_key,
    SOURCE_NAMES,
    get_admin_id, set_admin_id, get_card,
    record_group, bind_group, get_group_client, get_group_for_client,
    list_active_groups, deactivate_group, get_client_history,
    add_flower, get_active_flowers, deactivate_flower, clear_flowers,
    record_broadcast, get_broadcasts, title_key,
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
        ["🌸 Bugungi gullar", "ℹ️ Yordam"],
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


def fmt_dot(n):
    return "{:,}".format(int(n)).replace(",", ".")


def fmt_date(s):
    try:
        y, m, d = str(s).split("-")
        return d + "." + m + "." + y
    except Exception:
        return str(s)


def admin_id():
    env = os.environ.get("ADMIN_ID")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return get_admin_id()


def is_admin(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    aid = admin_id()
    return aid is not None and user.id == aid


def capture_admin_if_needed(update: Update) -> None:
    if os.environ.get("ADMIN_ID"):
        return
    if get_admin_id() is not None:
        return
    chat = update.effective_chat
    user = update.effective_user
    if chat and chat.type == "private" and user:
        set_admin_id(user.id)
        log.info("Admin id saqlandi: %s", user.id)


def group_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Jami qarzi", callback_data="g:debt")],
        [InlineKeyboardButton("🌷 Olgan gullari", callback_data="g:hist")],
        [InlineKeyboardButton("🌸 В наличии", callback_data="g:stock")],
    ])


def client_from_title(title):
    key = title_key(title or "")
    if not key:
        return None
    for cl in get_all_clients():
        if name_key(cl) == key:
            return canonical_name(cl)
    return None


def resolve_client_for_group(chat_id, title):
    c = get_group_client(chat_id)
    if c:
        return c
    return client_from_title(title)


def build_group_sale_text(client_name, rows, grand_total, balance):
    today = date.today().strftime("%d.%m.%Y")
    lines = ["🌸 " + client_name, "📅 " + today, ""]
    for source, label, qty, price in rows:
        total = qty * price
        lines.append(label + " " + str(qty) + "x" + fmt_dot(price) + "=" + fmt_dot(total))
    lines.append("")
    lines.append("Jami: " + fmt_dot(grand_total))
    lines.append("Umumiy qarz: " + fmt_dot(balance))
    return "\n".join(lines)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    capture_admin_if_needed(update)
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
        "👥 *Guruh funksiyalari:*\n"
        "• Sotuv kiritsangiz — mijoz guruhiga avtomatik boradi\n"
        "• Guruhni ulash: guruhda «Mijoz: Nigora opa» deb yozing\n"
        "• «🌸 Bugungi gullar» — gul rasmlarini barcha guruhga yuborish\n\n"
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

    buttons = []
    for b in debtors:
        cb = "rem:" + b["name"]
        if len(cb.encode("utf-8")) > 60:
            continue
        buttons.append([InlineKeyboardButton(b["name"] + " — " + fm(b["balance"]), callback_data=cb)])

    await update.message.reply_text(
        "📢 *Eslatma yuborish*\nMijozni tanlang — uning guruhiga qarz eslatmasi boradi:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_private_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    capture_admin_if_needed(update)
    if not is_admin(update):
        return
    text = update.message.text.strip()

    # Menyu tugmalari
    if "Hisobot" in text:
        return await cmd_hisobot(update, ctx)
    if "Bugungi gullar" in text:
        return await cmd_bugungi_gullar(update, ctx)
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

    # Mijoz guruhiga yuborish
    balance = get_client_balance(client_name)["balance"]
    group_text = build_group_sale_text(client_name, rows, grand_total, balance)
    chat_id = get_group_for_client(client_name)
    if chat_id:
        try:
            await ctx.bot.send_message(chat_id, group_text)
            await update.message.reply_text("📤 «" + client_name + "» guruhiga yuborildi.")
        except TelegramError as e:
            await update.message.reply_text("⚠️ Guruhga yuborilmadi: " + str(e))
    else:
        await update.message.reply_text(
            "⚠️ «" + client_name + "» uchun guruh topilmadi.\n"
            "Guruhda «Mijoz: " + client_name + "» deb yozing yoki guruh nomini mijoz ismi bilan bir xil qiling."
        )


async def cmd_hisobot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    capture_admin_if_needed(update)
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
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
    capture_admin_if_needed(update)
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
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
    capture_admin_if_needed(update)
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return ConversationHandler.END
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
    if not is_admin(update):
        return ConversationHandler.END
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
    capture_admin_if_needed(update)
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
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


# ---------------------------------------------------------------------------
# Bugungi chiqgan gullar (admin)
# ---------------------------------------------------------------------------

async def cmd_bugungi_gullar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    flowers = get_active_flowers()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Hammasini tozalash", callback_data="flw:clear")],
    ])
    await update.message.reply_text(
        "🌸 *Bugungi chiqgan gullar*\n\n"
        "Hozir: *" + str(len(flowers)) + " ta* gul.\n\n"
        "➕ Yangi gul qo'shish: shu yerga gul *rasmini* tashlang — bot uni barcha mijoz "
        "guruhlariga «Bugungi chiqgan gullar» deb yuboradi.\n\n"
        "🗑 Sotilgan gulni o'chirish: o'sha rasm javobidagi tugmani bosing.\n"
        "Yangi kun uchun: «Hammasini tozalash».",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def on_admin_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    capture_admin_if_needed(update)
    if not is_admin(update):
        return
    photo = update.message.photo[-1]
    file_id = photo.file_id
    caption = (update.message.caption or "").strip()
    fid = add_flower(file_id, caption)

    cap = "🌸 Bugungi chiqgan gullar"
    if caption:
        cap += "\n" + caption

    sent = 0
    for gid in list_active_groups():
        try:
            m = await ctx.bot.send_photo(gid, file_id, caption=cap)
            record_broadcast(fid, gid, m.message_id)
            sent += 1
        except TelegramError:
            continue

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 O'chirish (sotildi)", callback_data="delflw:" + str(fid))],
    ])
    await update.message.reply_text(
        "✅ Gul saqlandi va *" + str(sent) + " ta* guruhga yuborildi.\n"
        "Sotilsa, pastdagi tugma bilan o'chiring 👇",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# Guruh xabarlari va menyu
# ---------------------------------------------------------------------------

async def on_group_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    record_group(chat.id, chat.title)
    text = (update.message.text or "").strip()
    low = text.lower()

    if low.startswith("mijoz:") or low.startswith("mijoz "):
        if not is_admin(update):
            await update.message.reply_text("⚠️ Faqat admin guruhni mijozga bog'lay oladi.")
            return
        if ":" in text:
            name = text.split(":", 1)[1].strip()
        else:
            name = text[len("mijoz"):].strip()
        if not name:
            await update.message.reply_text("Misol: Mijoz: Nigora opa")
            return
        cn = bind_group(chat.id, chat.title, name)
        await update.message.reply_text(
            "✅ Bu guruh «" + cn + "» mijozga bog'landi.\n«menyu» deb yozsangiz menyu chiqadi."
        )
        return

    if low in ("menyu", "menu", "меню"):
        await update.message.reply_text("🌸 Menyu — bo'limni tanlang:", reply_markup=group_menu_kb())
        return
    # Boshqa guruh xabarlari e'tiborsiz qoldiriladi (sotuv sifatida olinmaydi)


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat:
        record_group(chat.id, chat.title)
    await update.message.reply_text("🌸 Menyu — bo'limni tanlang:", reply_markup=group_menu_kb())


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()
    chat = q.message.chat

    # Guruh menyusi
    if data.startswith("g:"):
        if data == "g:stock":
            flowers = get_active_flowers()
            if not flowers:
                await q.message.reply_text("📭 Bugungi gullar hali yo'q.")
                return
            for f in flowers:
                cap = "🌸 Bugungi chiqgan gullar"
                if f["caption"]:
                    cap += "\n" + f["caption"]
                try:
                    await ctx.bot.send_photo(chat.id, f["file_id"], caption=cap)
                except TelegramError:
                    continue
            return

        client = resolve_client_for_group(chat.id, chat.title)
        if not client:
            await q.message.reply_text(
                "⚠️ Bu guruh mijozga bog'lanmagan.\nAdmin «Mijoz: <ism>» deb yozsin."
            )
            return

        if data == "g:debt":
            d = get_client_balance(client)
            bal = d["balance"]
            if bal > 0:
                txt = "👤 " + client + "\n🔴 Jami qarz: " + fm(bal)
            elif bal < 0:
                txt = "👤 " + client + "\n🟢 Ortiqcha to'lov: " + fm(abs(bal))
            else:
                txt = "👤 " + client + "\n🟢 Qarz yo'q!"
            await q.message.reply_text(txt)
            return

        if data == "g:hist":
            hist = get_client_history(client, 30)
            if not hist:
                await q.message.reply_text("📭 Hali gul olinmagan.")
                return
            lines = ["🌷 " + client + " — olgan gullari:\n"]
            tot = 0
            for h in hist:
                lines.append(
                    fmt_date(h["date"]) + " — " + h["label"] + " " + str(h["quantity"])
                    + "x" + fmt_dot(h["price"]) + "=" + fmt_dot(h["total"])
                )
                tot += h["total"]
            lines.append("\nJami: " + fmt_dot(tot))
            await q.message.reply_text("\n".join(lines))
            return
        return

    # Eslatma yuborish (admin)
    if data.startswith("rem:"):
        if not is_admin(update):
            await q.message.reply_text("⚠️ Faqat admin.")
            return
        client = data[4:]
        target = get_group_for_client(client)
        if not target:
            await q.message.reply_text(
                "⚠️ «" + client + "» uchun guruh topilmadi. Avval guruhni bog'lang."
            )
            return
        d = get_client_balance(client)
        num, cardname = get_card()
        msg = (
            "Assalomu alekum " + client + ", qarzingizni yopib bering iltimos 🙏\n"
            "Jami qarz: " + fm(d["balance"]) + "\n\n"
            + num + "\n" + cardname
        )
        try:
            await ctx.bot.send_message(target, msg)
            await q.message.reply_text("✅ Eslatma yuborildi: " + client)
        except TelegramError as e:
            await q.message.reply_text("❌ Yuborilmadi: " + str(e))
        return

    # Gulni o'chirish (admin)
    if data.startswith("delflw:"):
        if not is_admin(update):
            await q.message.reply_text("⚠️ Faqat admin o'chira oladi.")
            return
        try:
            fid = int(data.split(":", 1)[1])
        except ValueError:
            return
        deactivate_flower(fid)
        for gid, mid in get_broadcasts(fid):
            try:
                await ctx.bot.delete_message(gid, mid)
            except TelegramError:
                pass
        try:
            await q.edit_message_text("🗑 Gul o'chirildi (barcha guruhlardan ham).")
        except TelegramError:
            pass
        return

    # Hamma gullarni tozalash (admin)
    if data == "flw:clear":
        if not is_admin(update):
            await q.message.reply_text("⚠️ Faqat admin.")
            return
        for f in get_active_flowers():
            for gid, mid in get_broadcasts(f["id"]):
                try:
                    await ctx.bot.delete_message(gid, mid)
                except TelegramError:
                    pass
        clear_flowers()
        try:
            await q.edit_message_text("🗑 Bugungi gullar tozalandi. Yangi kun uchun tayyor.")
        except TelegramError:
            pass
        return


async def on_my_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    if chat.type not in ("group", "supergroup"):
        return
    new_status = result.new_chat_member.status
    if new_status in ("member", "administrator"):
        record_group(chat.id, chat.title)
        try:
            await ctx.bot.send_message(
                chat.id,
                "🌸 Salom! Men gul-savdo botiman.\n\n"
                "Bu guruhni mijozga bog'lash uchun admin «Mijoz: <ism>» deb yozsin "
                "(masalan: «Mijoz: Nigora opa»).\n\n"
                "Menyu uchun «menyu» deb yozing.",
            )
        except TelegramError:
            pass
    elif new_status in ("left", "kicked"):
        deactivate_group(chat.id)


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
        entry_points=[CommandHandler("tolov", cmd_tolov, filters=filters.ChatType.PRIVATE)],
        states={WAIT_AMOUNT: [MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, tolov_amount)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("hisobot", cmd_hisobot, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("qarz", cmd_qarz, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("barchaqarz", cmd_barcha_qarz, filters=filters.ChatType.PRIVATE))
    app.add_handler(tolov_conv)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_admin_photo))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, on_group_text))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, handle_private_text))

    log.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
