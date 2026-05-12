# -*- coding: utf-8 -*-
"""
bot.py - Crypthon & SO Decoder Bot (Final Updated)
"""

import asyncio
import logging
import os
import sys
import tempfile
import threading
import time
from io import BytesIO

from dotenv import load_dotenv
from flask import Flask, Response, request
from telegram import (
    Bot, Update,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

load_dotenv()

from decoders.crypthon_decoder import decode_crypthon, is_likely_obfuscated
from decoders.so_decoder import decode_so_file
from utils.helpers import (
    format_decode_result,
    format_so_result,
    get_file_extension,
    sanitize_filename,
    split_message,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN not set!")
    sys.exit(1)

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

flask_app = Flask(__name__)
application: Application = None
_bot_loop: asyncio.AbstractEventLoop = None


# ====================== COMMANDS ======================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = user.first_name if user else "বন্ধু"
    text = (
        "🚀 <b>Crypthon &amp; SO Decoder Bot</b>\n\n"
        f"স্বাগতম, <b>{first_name}</b>!\n\n"
        "• .py ফাইল → ডিকোড করতে পারবে\n"
        "• .so ফাইল → অ্যানালাইজ করতে পারবে\n\n"
        "ফাইল আপলোড করার পর বাটনে ক্লিক করে ডিকোড শুরু করুন।"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>সাহায্য</b>\n\n"
        "1. .py বা .so ফাইল আপলোড করুন\n"
        "2. বাটনে ক্লিক করুন\n"
        "3. ডিকোড/অ্যানালাইসিস শুরু হবে\n\n"
        "সর্বোচ্চ 20MB ফাইল সাপোর্ট করে।"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ====================== DOCUMENT HANDLER ======================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    document = message.document

    if not document:
        return

    filename = sanitize_filename(document.file_name or "unknown_file")
    ext = get_file_extension(filename)

    if ext not in (".py", ".so"):
        await message.reply_text("শুধু .py এবং .so ফাইল সাপোর্ট করি।")
        return

    if (document.file_size or 0) > 20 * 1024 * 1024:
        await message.reply_text("ফাইলের সাইজ 20MB এর বেশি।")
        return

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False, prefix="dec_") as tmp:
        tmp_path = tmp.name

    tg_file = await context.bot.get_file(document.file_id)
    await tg_file.download_to_drive(tmp_path)

    context.user_data["pending_file_path"] = tmp_path
    context.user_data["pending_filename"] = filename
    context.user_data["pending_file_type"] = ext

    button_text = "🔍 ডিকোড করুন" if ext == ".py" else "🔍 অ্যানালাইজ করুন"

    keyboard = [[InlineKeyboardButton(button_text, callback_data="start_decode")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        f"📄 `{filename}` ফাইল রিসিভ হয়েছে।\nবাটনে ক্লিক করে ডিকোড শুরু করুন।",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ====================== BUTTON HANDLER ======================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data != "start_decode":
        return

    file_path = context.user_data.get("pending_file_path")
    filename = context.user_data.get("pending_filename", "unknown")
    file_type = context.user_data.get("pending_file_type")

    if not file_path or not os.path.exists(file_path):
        await query.edit_message_text("❌ ফাইল পাওয়া যায়নি। আবার আপলোড করুন।")
        return

    await query.edit_message_text("⏳ প্রসেসিং শুরু হচ্ছে...")

    if file_type == ".py":
        await _process_py(query.message, file_path, filename)
    else:
        await _process_so(query.message, file_path, filename)

    try:
        os.unlink(file_path)
    except:
        pass
    context.user_data.clear()


# ====================== PROCESSING FUNCTIONS ======================

async def _process_py(message, file_path: str, filename: str):
    result = decode_crypthon(file_path)
    full_output = format_decode_result(result, filename)
    chunks = split_message(full_output)

    for i, chunk in enumerate(chunks, 1):
        hdr = f"📄 [{i}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        try:
            await message.reply_text(f"{hdr}```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN_V2)
        except:
            await message.reply_text(f"{hdr}{chunk}")

    if result.get("success"):
        await message.reply_text(f"✅ ডিকোড সফল! Layers: {result.get('layers', 0)}")
    else:
        await message.reply_text(f"⚠️ {result.get('message', 'ডিকোড করা যায়নি')}.")


async def _process_so(message, file_path: str, filename: str):
    result = decode_so_file(file_path)
    full_output = format_so_result(result, filename)

    # ডিটেইলড রেজাল্ট পাঠানো (সবচেয়ে নিরাপদ উপায়)
    try:
        if len(full_output) > 3800:
            # খুব বড় হলে .txt ফাইল হিসেবে পাঠাও
            bio = BytesIO(full_output.encode('utf-8'))
            bio.name = f"{filename}_analysis.txt"
            await message.reply_document(
                document=bio,
                caption=f"📄 {filename} এর বিস্তারিত অ্যানালাইসিস"
            )
        else:
            await message.reply_text(
                f"```\n{full_output}\n```",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as e:
        logger.warning(f"Error sending detailed result: {e}")
        # Markdown এরর হলে সাধারণ টেক্সটে পাঠাও
        await message.reply_text(full_output[:4000])

    # সামারি মেসেজ
    if result.get("success"):
        await message.reply_text(
            f"✅ .so অ্যানালাইসিস সম্পন্ন!\n"
            f"• Core Logic: {len(result.get('core_logic', []))} টি\n"
            f"• Network: {len(result.get('network_strings', []))} টি\n"
            f"• Recovered Code: {len(result.get('recovered_code', []))} টি"
        )
    else:
        await message.reply_text(f"⚠️ {result.get('message', 'কোনো তথ্য পাওয়া যায়নি।')}")


# ====================== WEBHOOK + FLASK ======================

async def set_webhook(bot: Bot):
    if not RENDER_EXTERNAL_URL:
        return False
    url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(url=url, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    logger.info("✅ Webhook registered")
    return True


@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook_handler():
    if application is None or _bot_loop is None:
        return Response("Bot not ready", status=503)
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        future = asyncio.run_coroutine_threadsafe(application.process_update(update), _bot_loop)
        future.result(timeout=60)
        return Response("OK", status=200)
    except Exception as e:
        logger.exception(e)
        return Response("Error", status=500)


@flask_app.route("/health", methods=["GET"])
def health():
    return Response("OK", status=200)


def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_callback))
    return app


def _run_bot_loop(loop, app):
    asyncio.set_event_loop(loop)
    async def _main():
        await app.initialize()
        await app.start()
        if RENDER_EXTERNAL_URL:
            await set_webhook(app.bot)
        logger.info("✅ Bot is live")
        await asyncio.Event().wait()
    loop.run_until_complete(_main())


def run_webhook_mode():
    global application, _bot_loop
    logger.info("🚀 Starting in WEBHOOK mode...")
    application = build_application()
    _bot_loop = asyncio.new_event_loop()
    t = threading.Thread(target=_run_bot_loop, args=(_bot_loop, application), daemon=True)
    t.start()
    time.sleep(3)
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)


def run_polling_mode():
    app = build_application()
    asyncio.run(app.bot.delete_webhook(drop_pending_updates=True))
    app.run_polling()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--polling", action="store_true")
    args = parser.parse_args()
    if args.polling:
        run_polling_mode()
    else:
        run_webhook_mode()
