# -*- coding: utf-8 -*-
"""
bot.py
------
Main entry point for the Crypthon & SO Decoder Bot.

Supports two run modes:
  1. Webhook mode  — production on Render.com (default)
  2. Polling mode  — local development (pass --polling flag)

Architecture:
  - python-telegram-bot 20.8 (async)
  - Flask 3.0.3 (webhook HTTP server)
  - Automatic webhook registration when RENDER_EXTERNAL_URL is set

Author: Crypthon & SO Decoder Bot
"""

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

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
# Logging configuration
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

# Webhook path — use token as secret slug for security
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

# ---------------------------------------------------------------------------
# Flask app (used only in webhook mode)
# ---------------------------------------------------------------------------
flask_app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global telegram Application instance (shared between Flask and handlers)
# ---------------------------------------------------------------------------
application: Application = None  # type: ignore[assignment]


# ===========================================================================
# Telegram Command Handlers
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command — Bangla + English welcome message."""
    user = update.effective_user
    first_name = user.first_name if user else "বন্ধু"

    welcome_text = (
        f"🔓 *Crypthon \\& SO Decoder Bot*\n"
        f"{'─' * 32}\n\n"
        f"স্বাগতম, *{first_name}*\\! 👋\n\n"
        f"আমি obfuscated Python ফাইল এবং\\.so ফাইল analyze করতে পারি\\.\n\n"
        f"*📤 কী পাঠাবেন:*\n"
        f"• `.py` ফাইল \\(Crypthon obfuscated\\)\n"
        f"• `.so` ফাইল \\(shared object\\)\n\n"
        f"*🤖 কী পাবেন:*\n"
        f"• Decoded/deobfuscated Python code\n"
        f"• Bytecode disassembly\n"
        f"• Extracted strings ও keywords\n"
        f"• File type ও section analysis\n\n"
        f"শুধু ফাইলটি এখানে পাঠান — বাকি কাজ আমি করব\\! 🚀\n\n"
        f"_/help টাইপ করুন আরো জানতে_"
    )

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    logger.info("User %s started the bot.", user.id if user else "unknown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "📖 *সাহায্য / Help*\n"
        "══════════════════════════\n\n"
        "*সমর্থিত ফাইল টাইপ:*\n\n"
        "🔐 *\\.py ফাইল \\(Crypthon Decoder\\)*\n"
        "• base64 → zlib → marshal pattern\n"
        "• নেস্টেড/layered obfuscation \\(৬\\+ layer\\)\n"
        "• exec\\(marshal\\.loads\\(\\.\\.\\)\\) pattern\n"
        "• Bytecode disassembly fallback\n\n"
        "🔬 *\\.so ফাইল \\(Binary Analyzer\\)*\n"
        "• Printable string extraction\n"
        "• Embedded base64 detection\n"
        "• Python keyword search\n"
        "• ELF section analysis\n\n"
        "*ব্যবহার:*\n"
        "শুধু ফাইলটি এই চ্যাটে পাঠান\\.\n"
        "Bot স্বয়ংক্রিয়ভাবে ফাইল টাইপ detect করবে\\.\n\n"
        "*সীমাবদ্ধতা:*\n"
        "• সর্বোচ্চ ফাইল সাইজ: ২০MB \\(Telegram সীমা\\)\n"
        "• সব obfuscation decode নাও হতে পারে\n"
        "• Custom encryption সমর্থিত নয়\n\n"
        "_তৈরি করা হয়েছে বাংলাদেশ ও ভারতের Python সম্প্রদায়ের জন্য_"
    )

    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ===========================================================================
# Document Handler — core functionality
# ===========================================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle any document sent to the bot.

    Steps:
      1. Validate file type (.py or .so)
      2. Send "processing" acknowledgement
      3. Download file to a temp directory
      4. Call appropriate decoder
      5. Send results (split into multiple messages if needed)
      6. Clean up temp files
    """
    message = update.message
    document = message.document

    if not document:
        await message.reply_text("❌ কোনো ফাইল পাওয়া যায়নি। দয়া করে একটি ফাইল পাঠান।")
        return

    filename = sanitize_filename(document.file_name or "unknown_file")
    ext = get_file_extension(filename)
    user_id = update.effective_user.id if update.effective_user else 0

    logger.info(
        "Received file from user %d: %s (size: %d bytes, mime: %s)",
        user_id, filename, document.file_size or 0, document.mime_type or "unknown"
    )

    # ------------------------------------------------------------------ #
    # Validate supported file types                                        #
    # ------------------------------------------------------------------ #
    if ext not in (".py", ".so"):
        await message.reply_text(
            f"⚠️ দুঃখিত! শুধুমাত্র `.py` এবং `.so` ফাইল সমর্থিত।\n"
            f"আপনি পাঠিয়েছেন: `{ext or 'কোনো extension নেই'}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # ------------------------------------------------------------------ #
    # Check file size                                                      #
    # ------------------------------------------------------------------ #
    file_size = document.file_size or 0
    if file_size > 20 * 1024 * 1024:  # 20 MB
        await message.reply_text(
            "❌ ফাইলটি অনেক বড়! Telegram সর্বোচ্চ ২০MB ফাইল সমর্থন করে।"
        )
        return

    # ------------------------------------------------------------------ #
    # Send acknowledgement                                                 #
    # ------------------------------------------------------------------ #
    processing_text = (
        "⏳ ফাইল পেয়েছি। ডিকোড করা শুরু করছি...\n"
        f"📄 ফাইল: `{filename}`\n"
        f"📦 সাইজ: {file_size / 1024:.1f} KB"
    )
    status_msg = await message.reply_text(
        processing_text,
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    # ------------------------------------------------------------------ #
    # Download to temp file                                               #
    # ------------------------------------------------------------------ #
    tmp_path: str | None = None
    try:
        # Create a temporary file with the correct extension
        with tempfile.NamedTemporaryFile(
            suffix=ext,
            delete=False,
            prefix="decoder_",
        ) as tmp:
            tmp_path = tmp.name

        # Download from Telegram
        telegram_file = await context.bot.get_file(document.file_id)
        await telegram_file.download_to_drive(tmp_path)

        logger.info("Downloaded file to temp path: %s", tmp_path)

        # ------------------------------------------------------------------ #
        # Route to the correct decoder                                         #
        # ------------------------------------------------------------------ #
        if ext == ".py":
            await _process_py_file(message, status_msg, tmp_path, filename)
        elif ext == ".so":
            await _process_so_file(message, status_msg, tmp_path, filename)

    except Exception as exc:
        logger.exception("Unexpected error processing file %s: %s", filename, exc)
        try:
            await status_msg.edit_text(
                f"❌ একটি অপ্রত্যাশিত সমস্যা হয়েছে।\n"
                f"বিস্তারিত: `{str(exc)[:200]}`",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            await message.reply_text(f"❌ Error: {str(exc)[:200]}")

    finally:
        # Always clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.info("Temp file deleted: %s", tmp_path)
            except Exception:
                pass  # Non-critical


# ---------------------------------------------------------------------------
# Internal: process a .py file
# ---------------------------------------------------------------------------

async def _process_py_file(message, status_msg, file_path: str, filename: str) -> None:
    """Download, decode, and report a .py obfuscated file."""

    # Quick check: is this file even obfuscated?
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            source_preview = fh.read(4096)
    except Exception:
        source_preview = ""

    is_obfuscated = is_likely_obfuscated(source_preview)

    if is_obfuscated:
        await status_msg.edit_text(
            "🔐 এই ফাইলটি Crypthon দিয়ে এনক্রিপ্ট করা হয়েছে। ডিকোড করছি..."
        )
    else:
        await status_msg.edit_text(
            "🔍 ফাইলটি স্ক্যান করছি... (obfuscation সনাক্ত হয়নি, তবুও চেষ্টা করছি)"
        )

    # Run the decoder
    result = decode_crypthon(file_path)

    # Format the full output
    full_output = format_decode_result(result, filename)

    # Split into Telegram-safe chunks
    chunks = split_message(full_output)

    total = len(chunks)
    logger.info(
        "Decode complete for %s: success=%s, layers=%d, output=%d chars, chunks=%d",
        filename, result.get("success"), result.get("layers", 0), len(full_output), total,
    )

    # Delete the "processing" status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Send all chunks
    for i, chunk in enumerate(chunks, 1):
        prefix = f"📨 _{i}/{total}_ — " if total > 1 else ""
        try:
            await message.reply_text(
                f"{prefix}```\n{chunk}\n```",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            # Fallback: send as plain text (MarkdownV2 may choke on special chars)
            try:
                await message.reply_text(chunk)
            except Exception as exc:
                await message.reply_text(
                    f"⚠️ Output পাঠাতে সমস্যা: {str(exc)[:100]}"
                )

    # Final status summary
    if result.get("success"):
        await message.reply_text(
            f"✅ ডিকোড সফল হয়েছে!\n"
            f"🔄 Layers decoded: {result.get('layers', 0)}\n"
            f"🛠️ Method: {result.get('method', 'unknown')}"
        )
    else:
        await message.reply_text(
            f"⚠️ দুঃখিত, পুরোপুরি ডিকোড করা সম্ভব হয়নি। আংশিক রেজাল্ট দেওয়া হয়েছে।\n"
            f"💬 {result.get('message', '')}"
        )


# ---------------------------------------------------------------------------
# Internal: process a .so file
# ---------------------------------------------------------------------------

async def _process_so_file(message, status_msg, file_path: str, filename: str) -> None:
    """Analyze and report a .so shared object file."""

    await status_msg.edit_text("🔬 .SO ফাইল বিশ্লেষণ করছি... একটু অপেক্ষা করুন।")

    # Run the analyzer
    result = decode_so_file(file_path)

    # Format the output
    full_output = format_so_result(result, filename)

    # Split into Telegram-safe chunks
    chunks = split_message(full_output)
    total = len(chunks)

    logger.info(
        "SO analysis complete for %s: success=%s, file_type=%s, chunks=%d",
        filename, result.get("success"), result.get("file_type"), total,
    )

    # Delete status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Send all chunks
    for i, chunk in enumerate(chunks, 1):
        prefix = f"📨 _{i}/{total}_ — " if total > 1 else ""
        try:
            await message.reply_text(
                f"{prefix}```\n{chunk}\n```",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            try:
                await message.reply_text(chunk)
            except Exception as exc:
                await message.reply_text(
                    f"⚠️ Output পাঠাতে সমস্যা: {str(exc)[:100]}"
                )

    # Final status
    if result.get("success"):
        py_count = len(result.get("python_strings", []))
        b64_count = len(result.get("b64_findings", []))
        await message.reply_text(
            f"✅ .so ফাইল থেকে স্ট্রিং এক্সট্র্যাক্ট করা হয়েছে।\n"
            f"🐍 Python strings: {py_count} টি\n"
            f"🔐 Base64 blobs: {b64_count} টি"
        )
    else:
        await message.reply_text(
            f"❌ .so ফাইল analysis ব্যর্থ হয়েছে।\n"
            f"💬 {result.get('message', '')}"
        )


# ===========================================================================
# Webhook Setup
# ===========================================================================

async def set_webhook(bot: Bot) -> bool:
    """
    Register the webhook URL with Telegram.
    Only called when RENDER_EXTERNAL_URL is set.

    Returns True on success, False on failure.
    """
    if not RENDER_EXTERNAL_URL:
        logger.warning("RENDER_EXTERNAL_URL not set — skipping webhook registration.")
        return False

    webhook_url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    try:
        await bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("✅ Webhook set successfully: %s", webhook_url)
        return True
    except Exception as exc:
        logger.error("❌ Failed to set webhook: %s", exc)
        return False


# ===========================================================================
# Flask Webhook Routes
# ===========================================================================

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook_handler():
    """Receive Telegram updates via webhook POST requests."""
    if not application:
        return Response("Bot not initialized", status=503)

    try:
        json_data = request.get_json(force=True)
        if not json_data:
            return Response("Empty body", status=400)

        # Parse the Update and feed it to the application
        update = Update.de_json(json_data, application.bot)

        # Run the async update processing in the existing event loop
        asyncio.get_event_loop().run_until_complete(
            application.process_update(update)
        )
        return Response("OK", status=200)

    except Exception as exc:
        logger.exception("Error processing webhook update: %s", exc)
        return Response("Error", status=500)


@flask_app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint — Render uses this to verify the service is up."""
    return Response("🤖 Crypthon & SO Decoder Bot is running!", status=200)


@flask_app.route("/", methods=["GET"])
def index():
    """Root endpoint — friendly message."""
    return Response(
        "🔓 Crypthon & SO Decoder Bot\n"
        "Send /start to the Telegram bot to get started.\n"
        "Health check: /health",
        status=200,
    )


# ===========================================================================
# Application Builder
# ===========================================================================

def build_application() -> Application:
    """
    Build and configure the python-telegram-bot Application.
    Registers all handlers.
    """
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    # Document handler — catches all file uploads
    app.add_handler(
        MessageHandler(filters.Document.ALL, handle_document)
    )

    return app


# ===========================================================================
# Webhook Mode (Production — Render.com)
# ===========================================================================

def run_webhook_mode() -> None:
    """
    Start the bot in webhook mode.
      1. Build the Application
      2. Set the webhook with Telegram
      3. Start Flask server
    """
    global application

    logger.info("🚀 Starting bot in WEBHOOK mode...")

    application = build_application()

    # Initialize the application (needed before using bot.set_webhook)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(application.initialize())

    # Register webhook with Telegram
    if RENDER_EXTERNAL_URL:
        success = loop.run_until_complete(set_webhook(application.bot))
        if not success:
            logger.warning("Webhook registration failed — bot may not receive updates.")
    else:
        logger.warning(
            "RENDER_EXTERNAL_URL not set. "
            "Webhook not registered. Set this variable on Render."
        )

    logger.info("🌐 Starting Flask server on port %d...", PORT)

    # Start Flask (blocking)
    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


# ===========================================================================
# Polling Mode (Local Development)
# ===========================================================================

def run_polling_mode() -> None:
    """
    Start the bot in polling mode (for local development).
    Uses python-telegram-bot's built-in polling mechanism.
    No Flask server is started.
    """
    logger.info("🔄 Starting bot in POLLING mode (local development)...")
    logger.info("Press Ctrl+C to stop.")

    application = build_application()

    # Remove any existing webhook before polling
    async def clear_webhook():
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared for polling mode.")

    asyncio.get_event_loop().run_until_complete(clear_webhook())

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


# ===========================================================================
# Entry Point
# ===========================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Crypthon & SO Decoder Telegram Bot"
    )
    parser.add_argument(
        "--polling",
        action="store_true",
        help="Run in polling mode (for local development)",
    )
    args = parser.parse_args()

    if args.polling:
        run_polling_mode()
    else:
        run_webhook_mode()
