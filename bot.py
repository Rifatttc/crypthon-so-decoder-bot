# -*- coding: utf-8 -*-
"""
bot.py
------
Main entry point for the Crypthon & SO Decoder Bot.

Supports two run modes:
  1. Webhook mode  — production on Render.com (default)
  2. Polling mode  — local development (pass --polling flag)

Architecture:
  - python-telegram-bot 21.x (async)
  - Flask 3.0.3 (webhook HTTP server)
  - Automatic webhook registration when RENDER_EXTERNAL_URL is set

Fix log (v3 - Clean Bangla):
  - Fixed all corrupted Bengali text in cmd_start and cmd_help
  - Switched to ParseMode.HTML for better Bangla + formatting support
  - Kept the robust background thread + asyncio pattern for webhook

Author: Crypthon & SO Decoder Bot
"""

import asyncio
import logging
import os
import sys
import tempfile
import threading
import time

from dotenv import load_dotenv
from flask import Flask, Response, request
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load .env for local development (no-op in production)
load_dotenv()

# ---------------------------------------------------------------------------
# Decoder and utility imports
# ---------------------------------------------------------------------------
from decoders.crypthon_decoder import decode_crypthon, is_likely_obfuscated
from decoders.so_decoder import decode_so_file
from utils.helpers import (
    format_decode_result,
    format_so_result,
    get_file_extension,
    sanitize_filename,
    split_message,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
PORT: int = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL: str = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable is not set! Exiting.")
    sys.exit(1)

# Webhook path — token acts as a secret slug for basic security
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

# ---------------------------------------------------------------------------
# Flask app (webhook mode only)
# ---------------------------------------------------------------------------
flask_app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global state shared between Flask and the async bot
# ---------------------------------------------------------------------------
application: Application = None  # type: ignore[assignment]
_bot_loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]


# ===========================================================================
# Command Handlers (Clean Version)
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — Clean Bangla + English welcome."""
    user = update.effective_user
    first_name = user.first_name if user else "বন্ধু"

    text = (
        "🚀 <b>Crypthon &amp; SO Decoder Bot</b>\n\n"
        f"স্বাগতম, <b>{first_name}</b>! 👋\n\n"
        "এই বট দিয়ে তুমি পারবে:\n"
        "• <b>.py</b> ফাইল ডিকোড করতে (Crypthon / Obfuscated)\n"
        "• <b>.so</b> ফাইল অ্যানালাইজ করতে\n\n"
        "<b>যা যা পাবে:</b>\n"
        "✅ Decoded / Deobfuscated Python কোড\n"
        "✅ Bytecode Disassembly\n"
        "✅ .so ফাইল থেকে স্ট্রিং এক্সট্র্যাক্ট\n"
        "✅ Python keywords ও analysis\n\n"
        "শুধু <b>.py</b> অথবা <b>.so</b> ফাইল পাঠাও। বট অটোমেটিক প্রসেস করে দিবে!\n\n"
        "সাহায্যের জন্য: /help"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    logger.info("User %s used /start.", user.id if user else "unknown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — Clean instructions."""
    text = (
        "📖 <b>সাহায্য / Help</b>\n\n"
        "<b>কীভাবে ব্যবহার করবে:</b>\n\n"
        "🔹 <b>.py ফাইল</b> (Crypthon Obfuscated)\n"
        "• base64 → zlib → marshal প্যাটার্ন সাপোর্ট করে\n"
        "• Multi-layer obfuscation ডিকোড করে\n"
        "• Bytecode disassembly দেখায়\n\n"
        "🔹 <b>.so ফাইল</b> (Binary Analyzer)\n"
        "• Printable strings এক্সট্র্যাক্ট করে\n"
        "• Embedded base64 খুঁজে বের করে\n"
        "• Python keyword সার্চ করে\n\n"
        "<b>নিয়ম:</b>\n"
        "• সরাসরি .py অথবা .so ফাইল পাঠাও\n"
        "• বট অটো ডিটেক্ট করে প্রসেস করবে\n\n"
        "<b>সীমাবদ্ধতা:</b>\n"
        "• সর্বোচ্চ 20MB ফাইল সাপোর্ট করে\n"
        "• খুব জটিল কাস্টম এনক্রিপশন হলে আংশিক রেজাল্ট দিতে পারে\n\n"
        "কোনো সমস্যা হলে জানাও!"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ===========================================================================
# Document Handler
# ===========================================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle any document upload.
    """
    message = update.message
    document = message.document

    if not document:
        await message.reply_text("❌ কোনো ফাইল পাওয়া যায়নি। দয়া করে .py অথবা .so ফাইল পাঠান।")
        return

    filename = sanitize_filename(document.file_name or "unknown_file")
    ext = get_file_extension(filename)
    user_id = update.effective_user.id if update.effective_user else 0

    logger.info(
        "File received from user %d: %s (%d bytes, %s)",
        user_id, filename, document.file_size or 0, document.mime_type or "?",
    )

    if ext not in (".py", ".so"):
        await message.reply_text(
            f"❌ শুধুমাত্র `.py` অথবা `.so` ফাইল সাপোর্ট করি।\n"
            f"তোমার ফাইলের এক্সটেনশন: `{ext or 'অজানা'}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    file_size = document.file_size or 0
    if file_size > 20 * 1024 * 1024:
        await message.reply_text(
            "❌ ফাইলের সাইজ অনেক বড়! Telegram সর্বোচ্চ 20MB পর্যন্ত সাপোর্ট করে।",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    status_msg = await message.reply_text(
        f"⏳ ফাইল প্রসেস করা হচ্ছে...\n"
        f"📄 `{filename}` ({file_size / 1024:.1f} KB)",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False, prefix="dec_") as tmp:
            tmp_path = tmp.name

        tg_file = await context.bot.get_file(document.file_id)
        await tg_file.download_to_drive(tmp_path)
        logger.info("Saved to %s", tmp_path)

        if ext == ".py":
            await _handle_py(message, status_msg, tmp_path, filename)
        else:
            await _handle_so(message, status_msg, tmp_path, filename)

    except Exception as exc:
        logger.exception("Error processing %s: %s", filename, exc)
        try:
            await status_msg.edit_text(
                f"❌ প্রসেস করতে সমস্যা হয়েছে\n`{str(exc)[:200]}`",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            await message.reply_text(f"❌ Error: {str(exc)[:200]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# .py processor
# ---------------------------------------------------------------------------

async def _handle_py(message, status_msg, file_path: str, filename: str) -> None:
    """Decode a Crypthon-obfuscated Python file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            preview = fh.read(4096)
    except Exception:
        preview = ""

    hint = (
        "🔍 এই ফাইলটি Crypthon স্টাইলে অবফাস্কেটেড মনে হচ্ছে। ডিকোড করা হচ্ছে..."
        if is_likely_obfuscated(preview)
        else "🔍 ফাইল প্রসেস করা হচ্ছে... (obfuscation ডিটেক্ট করা যায়নি)"
    )
    await status_msg.edit_text(hint)

    result = decode_crypthon(file_path)
    full_output = format_decode_result(result, filename)
    chunks = split_message(full_output)
    total = len(chunks)

    logger.info(
        "Decode done: %s | success=%s layers=%d chunks=%d",
        filename, result.get("success"), result.get("layers", 0), total,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    for i, chunk in enumerate(chunks, 1):
        hdr = f"📄 [{i}/{total}]\n" if total > 1 else ""
        try:
            await message.reply_text(
                f"{hdr}```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            await message.reply_text(f"{hdr}{chunk}")

    if result.get("success"):
        await message.reply_text(
            f"✅ ডিকোড সফল হয়েছে!\n"
            f"🔢 Layers: {result.get('layers', 0)}\n"
            f"🛠 Method: {result.get('method', 'unknown')}"
        )
    else:
        await message.reply_text(
            f"⚠️ দুঃখিত, পুরোপুরি ডিকোড করা যায়নি। আংশিক রেজাল্ট দেয়া হলো।\n"
            f"ℹ️ {result.get('message', '')}"
        )


# ---------------------------------------------------------------------------
# .so processor
# ---------------------------------------------------------------------------

async def _handle_so(message, status_msg, file_path: str, filename: str) -> None:
    """Analyze a .so binary."""
    await status_msg.edit_text("🔍 .so ফাইল অ্যানালাইজ করা হচ্ছে... দয়া করে অপেক্ষা করুন।")

    result = decode_so_file(file_path)
    full_output = format_so_result(result, filename)
    chunks = split_message(full_output)
    total = len(chunks)

    logger.info(
        "SO analysis done: %s | success=%s type=%s chunks=%d",
        filename, result.get("success"), result.get("file_type"), total,
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    for i, chunk in enumerate(chunks, 1):
        hdr = f"📄 [{i}/{total}]\n" if total > 1 else ""
        try:
            await message.reply_text(
                f"{hdr}```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            await message.reply_text(f"{hdr}{chunk}")

    if result.get("success"):
        await message.reply_text(
            f"✅ .so ফাইল অ্যানালাইসিস সম্পন্ন হয়েছে!\n"
            f"🐍 Python strings: {len(result.get('python_strings', []))} টি\n"
            f"🔐 Base64 blobs: {len(result.get('b64_findings', []))} টি"
        )
    else:
        await message.reply_text(
            f"❌ .so ফাইল অ্যানালাইসিস করতে সমস্যা হয়েছে।\nℹ️ {result.get('message', '')}"
        )


# ===========================================================================
# Webhook Registration
# ===========================================================================

async def set_webhook(bot: Bot) -> bool:
    if not RENDER_EXTERNAL_URL:
        logger.warning("RENDER_EXTERNAL_URL not set — webhook not registered.")
        return False

    url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    try:
        await bot.set_webhook(
            url=url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("✅ Webhook registered: %s", url)
        return True
    except Exception as exc:
        logger.error("❌ Webhook registration failed: %s", exc)
        return False


# ===========================================================================
# Flask Routes
# ===========================================================================

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook_handler():
    if application is None or _bot_loop is None:
        return Response("Bot not initialized", status=503)

    try:
        json_data = request.get_json(force=True)
        if not json_data:
            return Response("Empty body", status=400)

        update = Update.de_json(json_data, application.bot)
        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            _bot_loop,
        )
        future.result(timeout=60)
        return Response("OK", status=200)

    except Exception as exc:
        logger.exception("Error handling update: %s", exc)
        return Response("Internal error", status=500)


@flask_app.route("/health", methods=["GET"])
def health():
    return Response("✅ Bot is running!", status=200)


@flask_app.route("/", methods=["GET"])
def index():
    return Response(
        "🚀 Crypthon & SO Decoder Bot — send /start on Telegram.", status=200
    )


# ===========================================================================
# Application Builder
# ===========================================================================

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    return app


# ===========================================================================
# Background Bot Thread (webhook mode)
# ===========================================================================

def _run_bot_loop(loop: asyncio.AbstractEventLoop, app: Application) -> None:
    asyncio.set_event_loop(loop)

    async def _main():
        await app.initialize()
        await app.start()

        if RENDER_EXTERNAL_URL:
            await set_webhook(app.bot)
        else:
            logger.warning("RENDER_EXTERNAL_URL is not set.")

        logger.info("✅ Bot is live in webhook mode.")
        await asyncio.Event().wait()

    loop.run_until_complete(_main())


# ===========================================================================
# Webhook Mode Entry (Production)
# ===========================================================================

def run_webhook_mode() -> None:
    global application, _bot_loop

    logger.info("🚀 Starting in WEBHOOK mode...")

    application = build_application()
    _bot_loop = asyncio.new_event_loop()

    t = threading.Thread(
        target=_run_bot_loop,
        args=(_bot_loop, application),
        daemon=True,
        name="BotLoop",
    )
    t.start()

    time.sleep(3)

    logger.info("🌐 Flask listening on port %d", PORT)
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)


# ===========================================================================
# Polling Mode Entry (Local Dev)
# ===========================================================================

def run_polling_mode() -> None:
    logger.info("🚀 Starting in POLLING mode (local dev). Ctrl+C to stop.")

    app = build_application()

    async def _clear():
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared.")

    asyncio.run(_clear())
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


# ===========================================================================
# Entry Point
# ===========================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crypthon & SO Decoder Bot")
    parser.add_argument("--polling", action="store_true", help="Use polling (local dev)")
    args = parser.parse_args()

    if args.polling:
        run_polling_mode()
    else:
        run_webhook_mode()
