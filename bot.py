import os
import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from supabase import create_client, Client

# === КОНФІГУРАЦІЯ ===
BOT_TOKEN    = os.environ.get('BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
ADMIN_ID     = int(os.environ.get('ADMIN_CHAT_ID'))   # твій Telegram ID
APP_URL      = os.environ.get('APP_URL', 'https://doroslist-kayf.netlify.app')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─── /start ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    res  = supabase.table('participants').select('*').eq('telegram_id', user.id).execute()

    if res.data:
        p = res.data[0]
        if p['is_active']:
            await update.message.reply_text(
                f"Привіт, {user.first_name}! 🤍\n\n"
                f"Твій доступ до програми активний.\n\n"
                f"Відкрий свій кабінет:\n{APP_URL}?id={user.id}"
            )
        else:
            await update.message.reply_text(
                f"Привіт, {user.first_name}! 🤍\n\n"
                "Твій доступ наразі неактивний.\n"
                "Надішли скрін оплати — і я активую твій кабінет."
            )
    else:
        await update.message.reply_text(
            f"Привіт, {user.first_name}! 🤍\n\n"
            "Ласкаво просимо до програми «Дорослість в кайф».\n\n"
            "Щоб отримати доступ — надішли скрін оплати і я активую твій особистий кабінет."
        )


# ─── Скрін оплати ──────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Якщо це сама Кет — ігноруємо
    if user.id == ADMIN_ID:
        return

    # Поточний статус учасника
    res = supabase.table('participants').select('*').eq('telegram_id', user.id).execute()
    participant = res.data[0] if res.data else None

    if participant and participant['is_active']:
        until = participant.get('active_until', 'безстроково')
        status = f"Активний до: {until}"
    elif participant:
        status = "Неактивний (оплата прострочена)"
    else:
        status = "🆕 Новий учасник"

    caption = (
        f"💳 *Скрін оплати*\n\n"
        f"👤 {user.first_name} {user.last_name or ''}\n"
        f"🔗 @{user.username or '—'}\n"
        f"🆔 ID: `{user.id}`\n"
        f"📊 Статус: {status}"
    )

    keyboard = [[
        InlineKeyboardButton("✅ Активувати", callback_data=f"activate_{user.id}_{user.first_name}"),
        InlineKeyboardButton("❌ Відхилити",  callback_data=f"reject_{user.id}"),
    ]]

    # Пересилаємо фото Кет
    await context.bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=update.effective_chat.id,
        message_id=update.message.message_id
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

    await update.message.reply_text(
        "Дякую! Скрін отримано. Я перевірю оплату і активую твій доступ найближчим часом 🤍"
    )


# ─── Кнопки Активувати / Відхилити ────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    # ── АКТИВУВАТИ ──
    if data.startswith('activate_'):
        parts       = data.split('_', 2)
        telegram_id = int(parts[1])
        name        = parts[2] if len(parts) > 2 else 'Учасник'
        active_until = (date.today() + timedelta(days=30)).isoformat()

        res = supabase.table('participants').select('id').eq('telegram_id', telegram_id).execute()
        if res.data:
            supabase.table('participants').update({
                'is_active':    True,
                'active_until': active_until,
                'type':         'paid'
            }).eq('telegram_id', telegram_id).execute()
        else:
            supabase.table('participants').insert({
                'telegram_id':   telegram_id,
                'telegram_name': name,
                'start_date':    date.today().isoformat(),
                'type':          'paid',
                'is_active':     True,
                'active_until':  active_until
            }).execute()

        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"🎉 Твій доступ активовано!\n\n"
                f"Активний до: {active_until}\n\n"
                f"Відкривай свій особистий кабінет:\n"
                f"{APP_URL}?id={telegram_id}\n\n"
                "Збережи це посилання або додай застосунок на головний екран телефону 🤍"
            )
        )
        await query.edit_message_text(
            f"✅ Активовано: {name} (ID: {telegram_id})\nДо: {active_until}"
        )

    # ── ВІДХИЛИТИ ──
    elif data.startswith('reject_'):
        telegram_id = int(data.split('_')[1])
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "На жаль, оплата не підтверджена 😔\n\n"
                "Якщо вважаєш що це помилка — напиши мені особисто @ket_deep"
            )
        )
        await query.edit_message_text(f"❌ Відхилено (ID: {telegram_id})")

    # ── ЗРОБИТИ БЕЗКОШТОВНИМ ──
    elif data.startswith('free_'):
        telegram_id = int(data.split('_')[1])
        supabase.table('participants').update({
            'type':         'free',
            'is_active':    True,
            'active_until': None
        }).eq('telegram_id', telegram_id).execute()
        await query.edit_message_text(f"✅ Безкоштовний доступ встановлено (ID: {telegram_id})")

    # ── ДЕАКТИВУВАТИ ──
    elif data.startswith('deactivate_'):
        telegram_id = int(data.split('_')[1])
        supabase.table('participants').update({
            'is_active': False
        }).eq('telegram_id', telegram_id).execute()
        await query.edit_message_text(f"🔒 Доступ деактивовано (ID: {telegram_id})")


# ─── /admin — список учасників ─────────────────────────────────────────────
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    res = supabase.table('participants').select('*').order('created_at', desc=True).execute()
    if not res.data:
        await update.message.reply_text("Учасників поки немає.")
        return

    text = "📋 *Учасники програми:*\n\n"
    for p in res.data:
        status = "✅ Активний" if p['is_active'] else "🔒 Неактивний"
        ptype  = "Безкоштовний" if p['type'] == 'free' else f"Платний до {p.get('active_until','?')}"
        text  += (
            f"👤 {p['telegram_name']} | ID: `{p['telegram_id']}`\n"
            f"   {status} | {ptype}\n\n"
        )

    await update.message.reply_text(text, parse_mode='Markdown')


# ─── /free ID — дати безкоштовний доступ ───────────────────────────────────
async def set_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Використання: /free 123456789")
        return

    telegram_id = int(context.args[0])
    res = supabase.table('participants').select('id').eq('telegram_id', telegram_id).execute()

    if res.data:
        supabase.table('participants').update({
            'type': 'free', 'is_active': True, 'active_until': None
        }).eq('telegram_id', telegram_id).execute()
    else:
        supabase.table('participants').insert({
            'telegram_id': telegram_id,
            'telegram_name': str(telegram_id),
            'start_date': date.today().isoformat(),
            'type': 'free',
            'is_active': True,
            'active_until': None
        }).execute()

    await context.bot.send_message(
        chat_id=telegram_id,
        text=(
            "🎁 Тобі надано безкоштовний доступ до програми «Дорослість в кайф» 🤍\n\n"
            f"Відкривай свій кабінет:\n{APP_URL}?id={telegram_id}"
        )
    )
    await update.message.reply_text(f"✅ Безкоштовний доступ надано: {telegram_id}")


# ─── Запуск ────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("admin",  admin))
    app.add_handler(CommandHandler("free",   set_free))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Бот запущено...")
    app.run_polling()


if __name__ == '__main__':
    main()
