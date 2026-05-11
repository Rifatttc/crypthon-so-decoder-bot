# -*- coding: utf-8 -*-
"""
bot.py
------
Main entry point for the Crypthon & SO Decoder Bot.

Supports two run modes:
  1. Webhook mode  тАФ production on Render.com (default)
  2. Polling mode  тАФ local development (pass --polling flag)

Architecture:
  - python-telegram-bot 21.x (async)
  - Flask 3.0.3 (webhook HTTP server)
  - Automatic webhook registration when RENDER_EXTERNAL_URL is set

Fix log (v2):
  - Upgraded PTB to 21.x (fixes Updater.__polling_cleanup_cb AttributeError
    that occurred with PTB 20.8 on Python 3.14)
  - Bot async loop now runs in a dedicated background thread; Flask routes
    forward updates via asyncio.run_coroutine_threadsafe() тАФ the correct
    pattern for Flask + PTB 21.x webhook integration.
  - Added runtime.txt to pin Python 3.11 on Render.

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

# Webhook path тАФ token acts as a secret slug for basic security
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

# ---------------------------------------------------------------------------
# Flask app (webhook mode only)
# ---------------------------------------------------------------------------
flask_app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global state shared between Flask and the async bot
# ---------------------------------------------------------------------------
# PTB Application instance тАФ set once during startup
application: Application = None  # type: ignore[assignment]

# Dedicated event loop that lives in its own daemon thread (webhook mode).
# Flask routes are synchronous; they submit coroutines to this loop via
# asyncio.run_coroutine_threadsafe() instead of run_until_complete().
_bot_loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]


# ===========================================================================
# Command Handlers
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start тАФ Bangla + English welcome."""
    user = update.effective_user
    first_name = user.first_name if user else "ржмржирзНржзрзБ"

    text = (
        f"ЁЯФУ *Crypthon \\& SO Decoder Bot*\n"
        f"{'тФА' * 32}\n\n"
        f"рж╕рзНржмрж╛ржЧрждржо, *{first_name}*\\! ЁЯСЛ\n\n"
        f"ржЖржорж┐ obfuscated Python ржлрж╛ржЗрж▓ ржПржмржВ \\.so ржлрж╛ржЗрж▓ analyze ржХрж░рждрзЗ ржкрж╛рж░рж┐\\.\n\n"
        f"*ЁЯУд ржХрзА ржкрж╛ржарж╛ржмрзЗржи:*\n"
        f"тАв `.py` ржлрж╛ржЗрж▓ \\(Crypthon obfuscated\\)\n"
        f"тАв `.so` ржлрж╛ржЗрж▓ \\(shared object\\)\n\n"
        f"*ЁЯдЦ ржХрзА ржкрж╛ржмрзЗржи:*\n"
        f"тАв Decoded/deobfuscated Python code\n"
        f"тАв Bytecode disassembly\n"
        f"тАв Extracted strings ржУ keywords\n"
        f"тАв File type ржУ section analysis\n\n"
        f"рж╢рзБржзрзБ ржлрж╛ржЗрж▓ржЯрж┐ ржПржЦрж╛ржирзЗ ржкрж╛ржарж╛ржи тАФ ржмрж╛ржХрж┐ ржХрж╛ржЬ ржЖржорж┐ ржХрж░ржм\\! ЁЯЪА\n\n"
        f"_/help ржЯрж╛ржЗржк ржХрж░рзБржи ржЖрж░рзЛ ржЬрж╛ржирждрзЗ_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info("User %s used /start.", user.id if user else "unknown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    text = (
        "ЁЯУЦ *рж╕рж╛рж╣рж╛ржпрзНржп / Help*\n"
        "тХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХРтХР\n\n"
        "*рж╕ржорж░рзНржерж┐ржд ржлрж╛ржЗрж▓ ржЯрж╛ржЗржк:*\n\n"
        "ЁЯФР *\\.py ржлрж╛ржЗрж▓ \\(Crypthon Decoder\\)*\n"
        "тАв base64 тЖТ zlib тЖТ marshal pattern\n"
        "тАв ржирзЗрж╕рзНржЯрзЗржб/layered obfuscation \\(рзм\\+ layer\\)\n"
        "тАв exec\\(marshal\\.loads\\(\\.\\.\\)\\) pattern\n"
        "тАв Bytecode disassembly fallback\n\n"
        "ЁЯФм *\\.so ржлрж╛ржЗрж▓ \\(Binary Analyzer\\)*\n"
        "тАв Printable string extraction\n"
        "тАв Embedded base64 detection\n"
        "тАв Python keyword search\n"
        "тАв ELF section analysis\n\n"
        "*ржмрзНржпржмрж╣рж╛рж░:*\n"
        "рж╢рзБржзрзБ ржлрж╛ржЗрж▓ржЯрж┐ ржПржЗ ржЪрзНржпрж╛ржЯрзЗ ржкрж╛ржарж╛ржи\\.\n"
        "Bot рж╕рзНржмржпрж╝ржВржХрзНрж░рж┐ржпрж╝ржнрж╛ржмрзЗ ржлрж╛ржЗрж▓ ржЯрж╛ржЗржк detect ржХрж░ржмрзЗ\\.\n\n"
        "*рж╕рзАржорж╛ржмржжрзНржзрждрж╛:*\n"
        "тАв рж╕рж░рзНржмрзЛржЪрзНржЪ ржлрж╛ржЗрж▓ рж╕рж╛ржЗржЬ: рзирзжMB \\(Telegram рж╕рзАржорж╛\\)\n"
        "тАв рж╕ржм obfuscation decode ржирж╛ржУ рж╣рждрзЗ ржкрж╛рж░рзЗ\n"
        "тАв Custom encryption рж╕ржорж░рзНржерж┐ржд ржиржпрж╝\n\n"
        "_рждрзИрж░рж┐ ржХрж░рж╛ рж╣ржпрж╝рзЗржЫрзЗ ржмрж╛ржВрж▓рж╛ржжрзЗрж╢ ржУ ржнрж╛рж░рждрзЗрж░ Python рж╕ржорзНржкрзНрж░ржжрж╛ржпрж╝рзЗрж░ ржЬржирзНржп_ ЁЯЗзЁЯЗйЁЯЗоЁЯЗ│"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


# ===========================================================================
# Document Handler
# ===========================================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle any document upload.

    Flow:
      1. Validate extension (.py / .so)
      2. Acknowledge with a status message
      3. Download to a temp file
      4. Decode / analyze
      5. Return results (chunked if > 3900 chars)
      6. Delete temp file
    """
    message = update.message
    document = message.document

    if not document:
        await message.reply_text("тЭМ ржХрзЛржирзЛ ржлрж╛ржЗрж▓ ржкрж╛ржУржпрж╝рж╛ ржпрж╛ржпрж╝ржирж┐ред ржжржпрж╝рж╛ ржХрж░рзЗ ржПржХржЯрж┐ ржлрж╛ржЗрж▓ ржкрж╛ржарж╛ржиред")
        return

    filename = sanitize_filename(document.file_name or "unknown_file")
    ext = get_file_extension(filename)
    user_id = update.effective_user.id if update.effective_user else 0

    logger.info(
        "File received from user %d: %s (%d bytes, %s)",
        user_id, filename, document.file_size or 0, document.mime_type or "?",
    )

    # --- Validate extension ---
    if ext not in (".py", ".so"):
        await message.reply_text(
            f"тЪая╕П рж╢рзБржзрзБржорж╛рждрзНрж░ `.py` ржПржмржВ `.so` ржлрж╛ржЗрж▓ рж╕ржорж░рзНржерж┐рждред\n"
            f"ржЖржкржирж┐ ржкрж╛ржарж┐ржпрж╝рзЗржЫрзЗржи: `{ext or 'ржХрзЛржирзЛ extension ржирзЗржЗ'}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # --- File size guard ---
    file_size = document.file_size or 0
    if file_size > 20 * 1024 * 1024:
        await message.reply_text(
            "тЭМ ржлрж╛ржЗрж▓ржЯрж┐ ржЕржирзЗржХ ржмржбрж╝\\! Telegram рж╕рж░рзНржмрзЛржЪрзНржЪ рзирзжMB рж╕ржорж░рзНржержи ржХрж░рзЗред",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # --- Acknowledgement ---
    status_msg = await message.reply_text(
        f"тП│ ржлрж╛ржЗрж▓ ржкрзЗржпрж╝рзЗржЫрж┐ред ржбрж┐ржХрзЛржб ржХрж░рж╛ рж╢рзБрж░рзБ ржХрж░ржЫрж┐\\.\\.\\.\n"
        f"ЁЯУД `{filename}` \\({file_size / 1024:.1f} KB\\)",
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
                f"тЭМ ржПржХржЯрж┐ рж╕ржорж╕рзНржпрж╛ рж╣ржпрж╝рзЗржЫрзЗред\n`{str(exc)[:200]}`",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            await message.reply_text(f"тЭМ Error: {str(exc)[:200]}")
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
    """Decode a Crypthon-obfuscated Python file and reply with results."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            preview = fh.read(4096)
    except Exception:
        preview = ""

    hint = (
        "ЁЯФР ржПржЗ ржлрж╛ржЗрж▓ржЯрж┐ Crypthon ржжрж┐ржпрж╝рзЗ ржПржиржХрзНрж░рж┐ржкрзНржЯ ржХрж░рж╛ рж╣ржпрж╝рзЗржЫрзЗред ржбрж┐ржХрзЛржб ржХрж░ржЫрж┐..."
        if is_likely_obfuscated(preview)
        else "ЁЯФН ржлрж╛ржЗрж▓ржЯрж┐ рж╕рзНржХрзНржпрж╛ржи ржХрж░ржЫрж┐... (obfuscation рж╕ржирж╛ржХрзНржд рж╣ржпрж╝ржирж┐, рждржмрзБржУ ржЪрзЗрж╖рзНржЯрж╛ ржХрж░ржЫрж┐)"
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
        hdr = f"ЁЯУи [{i}/{total}]\n" if total > 1 else ""
        try:
            await message.reply_text(
                f"{hdr}```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            await message.reply_text(f"{hdr}{chunk}")

    if result.get("success"):
        await message.reply_text(
            f"тЬЕ ржбрж┐ржХрзЛржб рж╕ржлрж▓ рж╣ржпрж╝рзЗржЫрзЗ!\n"
            f"ЁЯФД Layers: {result.get('layers', 0)}\n"
            f"ЁЯЫая╕П Method: {result.get('method', 'unknown')}"
        )
    else:
        await message.reply_text(
            f"тЪая╕П ржжрзБржГржЦрж┐ржд, ржкрзБрж░рзЛржкрзБрж░рж┐ ржбрж┐ржХрзЛржб ржХрж░рж╛ рж╕ржорзНржнржм рж╣ржпрж╝ржирж┐ред ржЖржВрж╢рж┐ржХ рж░рзЗржЬрж╛рж▓рзНржЯ ржжрзЗржУржпрж╝рж╛ рж╣ржпрж╝рзЗржЫрзЗред\n"
            f"ЁЯТм {result.get('message', '')}"
        )


# ---------------------------------------------------------------------------
# .so processor
# ---------------------------------------------------------------------------

async def _handle_so(message, status_msg, file_path: str, filename: str) -> None:
    """Analyze a .so binary and reply with results."""
    await status_msg.edit_text("ЁЯФм .SO ржлрж╛ржЗрж▓ ржмрж┐рж╢рзНрж▓рзЗрж╖ржг ржХрж░ржЫрж┐... ржПржХржЯрзБ ржЕржкрзЗржХрзНрж╖рж╛ ржХрж░рзБржиред")

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
        hdr = f"ЁЯУи [{i}/{total}]\n" if total > 1 else ""
        try:
            await message.reply_text(
                f"{hdr}```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            await message.reply_text(f"{hdr}{chunk}")

    if result.get("success"):
        await message.reply_text(
            f"тЬЕ .so ржлрж╛ржЗрж▓ ржерзЗржХрзЗ рж╕рзНржЯрзНрж░рж┐ржВ ржПржХрзНрж╕ржЯрзНрж░рзНржпрж╛ржХрзНржЯ ржХрж░рж╛ рж╣ржпрж╝рзЗржЫрзЗред\n"
            f"ЁЯРН Python strings: {len(result.get('python_strings', []))} ржЯрж┐\n"
            f"ЁЯФР Base64 blobs: {len(result.get('b64_findings', []))} ржЯрж┐"
        )
    else:
        await message.reply_text(
            f"тЭМ .so ржлрж╛ржЗрж▓ analysis ржмрзНржпрж░рзНрже рж╣ржпрж╝рзЗржЫрзЗред\nЁЯТм {result.get('message', '')}"
        )


# ===========================================================================
# Webhook Registration
# ===========================================================================

async def set_webhook(bot: Bot) -> bool:
    """Register the bot's webhook URL with Telegram."""
    if not RENDER_EXTERNAL_URL:
        logger.warning("RENDER_EXTERNAL_URL not set тАФ webhook not registered.")
        return False

    url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    try:
        await bot.set_webhook(
            url=url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("тЬЕ Webhook registered: %s", url)
        return True
    except Exception as exc:
        logger.error("тЭМ Webhook registration failed: %s", exc)
        return False


# ===========================================================================
# Flask Routes
# ===========================================================================

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook_handler():
    """
    Receive Telegram updates via POST.

    Uses asyncio.run_coroutine_threadsafe() to safely hand the update
    to the bot's event loop running in a separate thread.
    This is the correct pattern for PTB 21.x + Flask.
    """
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
    return Response("ЁЯдЦ Bot is running!", status=200)


@flask_app.route("/", methods=["GET"])
def index():
    return Response(
        "ЁЯФУ Crypthon & SO Decoder Bot тАФ send /start on Telegram.", status=200
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
    """
    Runs inside a daemon thread.
    Initializes PTB, registers the webhook, then keeps the loop alive
    so Flask can push updates into it.
    """
    asyncio.set_event_loop(loop)

    async def _main():
        await app.initialize()
        await app.start()

        if RENDER_EXTERNAL_URL:
            await set_webhook(app.bot)
        else:
            logger.warning(
                "RENDER_EXTERNAL_URL is not set. "
                "Webhook not registered тАФ updates will not arrive in webhook mode. "
                "Use --polling for local testing."
            )

        logger.info("ЁЯдЦ Bot is live in webhook mode.")
        # Block forever тАФ Flask feeds updates via run_coroutine_threadsafe
        await asyncio.Event().wait()

    loop.run_until_complete(_main())


# ===========================================================================
# Webhook Mode Entry (Production)
# ===========================================================================

def run_webhook_mode() -> None:
    """
    Production startup:
      1. Build PTB Application
      2. Start background thread with its own event loop
      3. Flask runs on the main thread (blocking)
    """
    global application, _bot_loop

    logger.info("ЁЯЪА Starting in WEBHOOK mode...")

    application = build_application()
    _bot_loop = asyncio.new_event_loop()

    t = threading.Thread(
        target=_run_bot_loop,
        args=(_bot_loop, application),
        daemon=True,
        name="BotLoop",
    )
    t.start()

    # Let the bot thread initialize before Flask starts accepting connections
    time.sleep(3)

    logger.info("ЁЯМР Flask listening on port %d", PORT)
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)


# ===========================================================================
# Polling Mode Entry (Local Dev)
# ===========================================================================

def run_polling_mode() -> None:
    """Local development: PTB polling, no Flask."""
    logger.info("ЁЯФД Starting in POLLING mode (local dev). Ctrl+C to stop.")

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
