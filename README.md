# 🔓 Crypthon & SO Decoder Bot

A Telegram bot that decodes **Crypthon-style obfuscated `.py` files** (marshal + zlib + base64 layers) and analyzes **`.so` compiled extensions**.

> ⚠️ **Educational Purpose Only** — Use only on files you own or have permission to analyze.

---

## ✨ Features

- 🐍 Decodes multi-layer Crypthon `.py` files (`marshal`, `zlib`, `base64`)
- 🔍 Extracts printable strings & base64 blobs from `.so` files
- 🤖 Auto file-type detection
- 🌐 Webhook-based (perfect for Render free tier)
- 🇧🇩 Bangla + English UI
- 🧪 Local polling mode for testing
- 🛡️ 100% static analysis — never executes user code

---

## 🇧🇩 বাংলা পরিচিতি

এই বটটি Telegram-এ যেকোনো **Crypthon দিয়ে এনক্রিপ্ট করা `.py` ফাইল** এবং **`.so` ফাইল** ডিকোড করতে পারে। আপনি শুধু ফাইলটি বটে পাঠান, বট স্বয়ংক্রিয়ভাবে ডিকোড করে আসল কোড ফেরত দেবে।

---

## 🚀 Deployment Guide

### 1️⃣ Create a Bot (BotFather)

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → choose a name & username
3. Copy the **BOT_TOKEN** (you'll need it)

### 2️⃣ Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/crypthon-so-decoder-bot.git
git push -u origin main
```

### 3️⃣ Deploy on Render.com

1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repo
3. Configure:
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. Add **Environment Variable**:
   - `BOT_TOKEN` = `123456:ABC...` (from BotFather)
5. Click **Create Web Service** ✅

Render auto-injects `RENDER_EXTERNAL_URL` — the bot uses it to set its webhook automatically.

### 4️⃣ Local Testing (Polling Mode)

```bash
git clone <your-repo>
cd crypthon-so-decoder-bot
pip install -r requirements.txt
export BOT_TOKEN="your_token_here"
export MODE="polling"
python bot.py
```

---

## 🧠 How It Works

### Crypthon `.py` Decoder
1. Reads the source as text
2. Finds the longest base64 blob via regex
3. Iteratively reverses: `base64 → zlib → marshal` (in any order, multiple layers)
4. If `marshal` produces a code object → tries to decompile with `uncompyle6` / falls back to `dis` disassembly
5. Returns the recovered Python code

### `.so` Decoder
1. Extracts ASCII/UTF-8 printable strings (`min_len=6`)
2. Finds Python keywords (`import`, `def`, `exec`, `marshal`...)
3. Searches & decodes embedded base64 blobs
4. Reports file metadata (size, magic bytes)

---

## 🔐 Environment Variables

| Variable             | Required | Description                              |
| -------------------- | -------- | ---------------------------------------- |
| `BOT_TOKEN`          | ✅       | Telegram bot token from BotFather        |
| `RENDER_EXTERNAL_URL`| auto     | Auto-set by Render                        |
| `MODE`               | ❌       | `polling` for local, default = `webhook` |
| `PORT`               | ❌       | Auto-set by Render (default 10000)       |

---

## 📜 License

MIT — for educational & research use only.
