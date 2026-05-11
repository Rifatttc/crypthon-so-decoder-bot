"""
Crypthon & SO Decoder Bot — Main entrypoint.

Modes:
    - webhook (default, for Render.com)
    - polling (for local testing, set MODE=polling)
"""

import os
import logging
import asyncio
from pathlib import Path

from flask import Flask, request, abort
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from decoders import decode_crypthon, analyze_so
from utils.file_utils import (
    ensure_tmp_dir,
    safe_delete,
    split_message,
    human_size,
    MAX_FILE_SIZE,
)

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("crypthon-bot")

# --------------------------------------------------------------------------
# Env vars
# --------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable not set!")

MODE = os.environ.get("MODE", "webhook").lower()
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")  # auto by Render
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

# --------------------------------------------------------------------------
# Messages (Bangla + English)
# --------------------------------------------------------------------------
WELCOME_MSG = (
    "👋 *স্বাগতম!* / *Welcome!*\n\n"
    "আমি *Crypthon & SO Decoder Bot* 🔓\n"
    "I'm the *Crypthon & SO Decoder Bot* 🔓\n\n"
    "📌 *আমি কী করতে পারি?* / *What I do:*\n"
    "• Crypthon দিয়ে এনক্রিপ্ট করা `.py` ফাইল ডিকোড করি\n"
    "• `.so` ফাইল অ্যানালাইজ করি (strings + base64)\n\n"
    "📤 *ব্যবহার:* শুধু একটি `.py` বা `.so` ফাইল পাঠান।\n"
    "📤 *Usage:* Just send me a `.py` or `.so` file.\n\n"
    "ℹ️ আরও জানতে `/help` লিখুন।"
)

HELP_MSG = (
    "🆘 *সহায়তা / Help*\n\n"
    "*সমর্থিত ফাইল / Supported files:*\n"
    "• `.py` — Crypthon-style obfuscated Python\n"
    "• `.so` — Compiled Python extension / binary\n\n"
    "*কীভাবে কাজ করে / How it works:*\n"
    "1️⃣ ফাইল পাঠান document হিসেবে\n"
    "2️⃣ বট অটো-ডিটেক্ট করবে\n"
    "3️⃣ ডিকোড করে রেজাল্ট ফেরত দেবে\n\n"
    f"⚠️ *Max file size:* {human_size(MAX_FILE_SIZE)}\n\n"
    "🔐 *নিরাপত্তা:* কোনো কোড execute করা হয় না — শুধু static analysis।"
)


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MSG, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MSG, parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming .py / .so documents."""
    doc = update.message.document
    if not doc:
        return

    filename = doc.file_name or "unknown"
    ext = Path(filename).suffix.lower()

    if ext not in (".py", ".so"):
        await update.message.reply_text(
            "❌ শুধু `.py` বা `.so` ফাইল সমর্থিত।\n"
            "❌ Only `.py` or `.so` files are supported.",
            parse_mode="Markdown",
        )
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ ফাইল অনেক বড় ({human_size(doc.file_size)}). "
            f"Max: {human_size(MAX_FILE_SIZE)}"
        )
        return

    status = await update.message.reply_text(
        "📥 *ফাইল পাঠানো হয়েছে। ডিকোড করা হচ্ছে...*\n"
        "📥 *File received. Decoding in progress...*",
        parse_mode="Markdown",
    )

    ensure_tmp_dir()
    local_path = f"/tmp/{update.message.message_id}_{filename}"

    try:
        # 1) Download
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=local_path)
        logger.info(f"Downloaded {filename} → {local_path}")

        # 2) Decode (run sync code in a worker thread to keep loop free)
        if ext == ".py":
            result = await asyncio.to_thread(decode_crypthon, local_path)
        else:
            result = await asyncio.to_thread(analyze_so, local_path)

        # 3) Send result
        if len(result) < 3800:
            await status.edit_text(f"```\n{result}\n```", parse_mode="Markdown")
        else:
            # Too long — send as .txt
            out_path = f"/tmp/result_{update.message.message_id}.txt"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(result)
            await status.edit_text(
                "✅ ডিকোড সম্পন্ন। রেজাল্ট ফাইল হিসেবে পাঠানো হচ্ছে...\n"
                "✅ Done. Sending result as file..."
            )
            with open(out_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=f"decoded_{filename}.txt",
                    caption="📄 ডিকোডেড রেজাল্ট / Decoded result",
                )
            safe_delete(out_path)

    except Exception as e:
        logger.exception("Decoding failed")
        await status.edit_text(
            f"❌ *ত্রুটি ঘটেছে / Error:*\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )
    finally:
        safe_delete(local_path)


async def unknown_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤔 দয়া করে `.py` বা `.so` ফাইল পাঠান।\n"
        "🤔 Please send a `.py` or `.so` file.\n\n"
        "ℹ️ /help"
    )


# --------------------------------------------------------------------------
# Build Application
# --------------------------------------------------------------------------
application: Application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start_cmd))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_msg)
)


# --------------------------------------------------------------------------
# Flask App (Webhook Mode)
# --------------------------------------------------------------------------
flask_app = Flask(__name__)


@flask_app.route("/", methods=["GET"])
def index():
    return "🤖 Crypthon & SO Decoder Bot is alive!", 200


@flask_app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    """Receive updates from Telegram and pass to PTB."""
    if request.headers.get("content-type") != "application/json":
        abort(403)

    update = Update.de_json(request.get_json(force=True), application.bot)

    # Schedule update processing on the bot loop
    asyncio.run_coroutine_threadsafe(
        application.process_update(update), application.bot_loop  # type: ignore
    )
    return "ok", 200


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
async def _start_webhook_app():
    """Initialize PTB application & set webhook."""
    await application.initialize()
    await application.start()

    if not RENDER_URL:
        logger.warning(
            "⚠️ RENDER_EXTERNAL_URL not set. Set it manually if not on Render."
        )
