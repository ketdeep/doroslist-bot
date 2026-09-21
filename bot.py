import os
import asyncio
import signal
import logging
import threading
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

BOT_TOKEN    = os.environ.get('BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
ADMIN_ID     = int(os.environ.get('ADMIN_CHAT_ID'))
APP_URL      = os.environ.get('APP_URL', 'https://doroslist-kayf.netlify.app')
PORT         = int(os.environ.get('PORT', 10000))

HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'return=representation'
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')
    def log_message(self, format, *args):
        pass

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    logger.info(f"HTTP сервер слухає порт {PORT}")
    server.serve_forever()


def db_get(telegram_id):
    url = f"{SUPABASE_URL}/rest/v1/participants?telegram_id=eq.{telegram_id}"
    with httpx.Client() as client:
        r = client.get(url, headers=HEADERS)
        data = r.json()
        return data[0] if data else None

def db_insert(data):
    url = f"{SUPABASE_URL}/rest/v1/participants"
    with httpx.Client() as client:
        r = client.post(url, headers=HEADERS, json=data)
        return r.json()

def db_update(telegram_id, data):
    url = f"{SUPABASE_URL}/rest/v1/participants?telegram_id=eq.{telegram_id}"
    with httpx.Client() as client:
        r = client.patch(url, headers=HEADERS, json=data)
        return r.json()

def db_all():
    url = f"{SUPABASE_URL}/rest/v1/participants?order=created_at.desc"
    with httpx.Client() as client:
        r = client.get(url, headers=HEADERS)
        return r.json()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = db_get(user.id)
    if p and p.get('is_active'):
        await update.message.reply_text(
            f"Привіт, {user.first_name}! 🤍\n\n"
            f"Твій доступ активний.\n\n"
            f"Відкрий свій кабінет:\n{APP_URL}?id={user.id}"
        )
    elif p:
        await update.message.reply_text(
            f"Привіт, {user.first_name}! 🤍\n\n"
            "Твій доступ неактивний.\n"
            "Надішли скрін оплати — і я активую твій кабінет."
        )
    else:
        await update.message.reply_text(
            f"Привіт, {user.first_name}! 🤍\n\n"
            "Ласкаво просимо до «Дорослість в кайф».\n\n"
            "Надішли скрін оплати і я активую твій особистий кабінет."
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        return

    p = db_get(user.id)
    if p and p.get('is_active'):
        status = f"Активний до: {p.get('active_until', 'безстроково')}"
    elif p:
        status = "Неактивний"
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
        InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user.id}"),
    ]]

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
        "Дякую! Скрін отримано. Активую твій доступ найближчим часом 🤍"
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith('activate_'):
        parts = data.split('_', 2)
        telegram_id = int(parts[1])
        name = parts[2] if len(parts) > 2 else 'Учасник'
        active_until = (date.today() + timedelta(days=30)).isoformat()

        p = db_get(telegram_id)
        if p:
            db_update(telegram_id, {'is_active': True, 'active_until': active_until, 'type': 'paid'})
        else:
            db_insert({
                'telegram_id': telegram_id,
                'telegram_name': name,
                'start_date': date.today().isoformat(),
                'type': 'paid',
                'is_active': True,
                'active_until': active_until
            })

        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"🎉 Доступ активовано!\n\n"
                f"Активний до: {active_until}\n\n"
                f"Відкривай кабінет:\n{APP_URL}?id={telegram_id}\n\n"
                "Збережи посилання або додай застосунок на головний екран 🤍"
            )
        )
        await query.edit_message_text(f"✅ Активовано: {name} (ID: {telegram_id})\nДо: {active_until}")

    elif data.startswith('reject_'):
        telegram_id = int(data.split('_')[1])
        await context.bot.send_message(
            chat_id=telegram_id,
            text="На жаль, оплата не підтверджена 😔\n\nЯкщо помилка — напиши @ket_deep"
        )
        await query.edit_message_text(f"❌ Відхилено (ID: {telegram_id})")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    participants = db_all()
    if not participants:
        await update.message.reply_text("Учасників поки немає.")
        return
    text = "📋 *Учасники:*\n\n"
    for p in participants:
        status = "✅" if p.get('is_active') else "🔒"
        ptype = "Free" if p.get('type') == 'free' else f"До {p.get('active_until', '?')}"
        text += f"{status} {p.get('telegram_name', '?')} | `{p.get('telegram_id')}` | {ptype}\n"
    await update.message.reply_text(text, parse_mode='Markdown')


async def set_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Використання: /free 123456789")
        return
    telegram_id = int(context.args[0])
    p = db_get(telegram_id)
    if p:
        db_update(telegram_id, {'type': 'free', 'is_active': True, 'active_until': None})
    else:
        db_insert({
            'telegram_id': telegram_id,
            'telegram_name': str(telegram_id),
            'start_date': date.today().isoformat(),
            'type': 'free',
            'is_active': True,
            'active_until': None
        })
    await context.bot.send_message(
        chat_id=telegram_id,
        text=f"🎁 Безкоштовний доступ надано 🤍\n\nВідкривай кабінет:\n{APP_URL}?id={telegram_id}"
    )
    await update.message.reply_text(f"✅ Безкоштовний доступ: {telegram_id}")


async def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("free", set_free))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    async with app:
        await app.start()
        await app.updater.start_polling()
        logger.info("Бот запущено...")
        await stop_event.wait()
        await app.updater.stop()
        await app.stop()


if __name__ == '__main__':
    # HTTP сервер стартує ПЕРШИМ щоб Render не таймаутився
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Потім запускаємо бота
    asyncio.run(run_bot())
