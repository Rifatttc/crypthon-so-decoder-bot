# 🔓 Crypthon & SO Decoder Bot

একটি শক্তিশালী Telegram bot যা Crypthon দিয়ে obfuscate করা `.py` ফাইল এবং `.so` (shared object) ফাইল decode/deobfuscate করতে পারে।

A powerful Telegram bot that decodes/deobfuscates Crypthon-obfuscated `.py` files and extracts information from `.so` (shared object) files.

---

## 📋 Table of Contents
- [Features](#features)
- [How to Use the Bot](#how-to-use-the-bot)
- [Local Setup](#local-setup)
- [Render.com Deployment Guide](#rendercom-deployment-guide)
- [Getting BOT_TOKEN from BotFather](#getting-bot_token-from-botfather)
- [Environment Variables](#environment-variables)
- [Common Issues & Solutions](#common-issues--solutions)

---

## ✨ Features

### 🔐 Crypthon Decoder
- **Multi-layer deobfuscation** — handles up to 6+ nested layers
- Supports all common patterns:
  - `base64` → `zlib.decompress` → `marshal.loads`
  - `marshal` → `zlib` → `base64` (any order)
  - `exec(compile(...))` patterns
  - `exec(marshal.loads(...))` patterns
  - Long base64 strings embedded in `.py` files
- Automatic regex extraction of obfuscated payloads
- Bytecode disassembly fallback using `dis`
- Readable string extraction from code objects

### 🔬 .so File Analyzer
- Extract all printable ASCII strings (length ≥ 5)
- Automatic base64 detection and decoding inside binaries
- Python keyword detection (`import`, `def`, `class`, `exec`, `marshal`, etc.)
- File magic/type identification
- Clean, formatted report output

### 🤖 Bot Features
- Bangla + English interface
- Webhook mode (Render.com production)
- Polling mode (local development)
- Auto-webhook setup on Render
- Proper temp file cleanup
- Detailed logging
- Beautiful formatted output

---

## 🤖 How to Use the Bot

1. **Start the bot** — Send `/start` to get a welcome message
2. **Send a file** — Upload any `.py` or `.so` file directly to the chat
3. **Wait for results** — The bot will automatically detect the file type and decode it
4. **Read the output** — Results are sent back in formatted messages (split if > 4000 chars)

### Supported File Types
| Extension | Action |
|-----------|--------|
| `.py` | Crypthon/obfuscation decoder |
| `.so` | Shared object string extractor + analyzer |

---

## 💻 Local Setup

### Prerequisites
- Python 3.11+
- Git
- A Telegram Bot Token (see [Getting BOT_TOKEN](#getting-bot_token-from-botfather))

### Step 1: Clone the Repository
```bash
git clone https://github.com/yourusername/crypthon-so-decoder-bot.git
cd crypthon-so-decoder-bot
```

### Step 2: Create Virtual Environment
```bash
python -m venv venv

# On Linux/macOS:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment
```bash
cp .env.example .env
```

Edit `.env` and add your bot token:
```
BOT_TOKEN=your_actual_bot_token_here
```

### Step 5: Run in Polling Mode (Local)
```bash
python bot.py --polling
```

The bot will start and you can test it locally via Telegram.

---

## 🚀 Render.com Deployment Guide

### ধাপ ১: GitHub Repository তৈরি করুন (Step 1: Create GitHub Repository)

1. **GitHub.com** এ যান এবং লগইন করুন
2. **"New repository"** বাটনে ক্লিক করুন (ডান উপরে `+` আইকন)
3. Repository নাম দিন: `crypthon-so-decoder-bot`
4. **"Private"** সিলেক্ট করুন (বট টোকেন সুরক্ষার জন্য)
5. **"Create repository"** ক্লিক করুন
6. নিচের কমান্ড দিয়ে কোড push করুন:

```bash
git init
git add .
git commit -m "Initial commit: Crypthon & SO Decoder Bot"
git branch -M main
git remote add origin https://github.com/yourusername/crypthon-so-decoder-bot.git
git push -u origin main
```

---

### ধাপ ২: Render.com Account তৈরি করুন (Step 2: Create Render Account)

1. **https://render.com** এ যান
2. **"Get Started for Free"** ক্লিক করুন
3. **GitHub দিয়ে Sign up** করুন (সবচেয়ে সহজ)
4. GitHub permission দিন

---

### ধাপ ৩: New Web Service তৈরি করুন (Step 3: Create New Web Service)

1. Render Dashboard এ **"New +"** বাটনে ক্লিক করুন
2. **"Web Service"** সিলেক্ট করুন
3. **"Connect a repository"** সেকশনে আপনার GitHub repo সিলেক্ট করুন
   - যদি repo না দেখায়: **"Configure account"** ক্লিক করুন → GitHub settings এ repo access দিন
4. **"Connect"** ক্লিক করুন

---

### ধাপ ৪: Service Configure করুন (Step 4: Configure the Service)

নিচের settings দিন:

| Field | Value |
|-------|-------|
| **Name** | `crypthon-so-decoder-bot` |
| **Region** | Singapore (Asia এর জন্য ভালো) বা যেকোনো |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python bot.py` |
| **Instance Type** | `Free` (শুরুতে) |

---

### ধাপ ৫: Environment Variables সেট করুন (Step 5: Set Environment Variables)

"Environment" সেকশনে যান এবং **"Add Environment Variable"** ক্লিক করুন:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | `আপনার bot token` (যেমন: `1234567890:ABCdef...`) |
| `PORT` | `10000` |
| `PYTHON_VERSION` | `3.11.0` |

> ⚠️ **গুরুত্বপূর্ণ**: `RENDER_EXTERNAL_URL` Render নিজেই automatically সেট করে। আপনাকে দিতে হবে না।

---

### ধাপ ৬: Deploy করুন (Step 6: Deploy)

1. **"Create Web Service"** বাটনে ক্লিক করুন
2. Render automatically build শুরু করবে
3. **"Logs"** ট্যাবে দেখুন — build progress দেখাবে
4. সফল হলে দেখবেন:
   ```
   ✅ Webhook set successfully
   🤖 Bot started in webhook mode
   ```
5. আপনার service URL হবে: `https://crypthon-so-decoder-bot.onrender.com`

---

### ধাপ ৭: Bot Test করুন (Step 7: Test the Bot)

1. Telegram এ আপনার bot খুঁজুন
2. `/start` পাঠান
3. একটি `.py` বা `.so` ফাইল পাঠান
4. Result দেখুন! 🎉

---

### ⚡ Auto-Deploy Setup (Optional)

প্রতিটি GitHub push এ auto-deploy চালু করতে:
1. Render service এর **"Settings"** ট্যাবে যান
2. **"Auto-Deploy"** → **"Yes"** সিলেক্ট করুন

---

## 🔑 Getting BOT_TOKEN from BotFather

### বাংলায় ধাপসমূহ:

1. Telegram এ **@BotFather** সার্চ করুন এবং অফিসিয়াল account open করুন (নীল tick দেখুন)
2. `/newbot` কমান্ড পাঠান
3. বটের **display name** দিন (যেমন: `Crypthon Decoder`)
4. বটের **username** দিন — অবশ্যই `bot` দিয়ে শেষ হতে হবে (যেমন: `crypthon_decoder_bot`)
5. BotFather আপনাকে একটি token দেবে এই format এ:
   ```
   1234567890:ABCDEFghijklmNOPQRSTuvwxyz
   ```
6. এই token টি কপি করুন এবং `.env` ফাইলে অথবা Render এর environment variable এ paste করুন

> ⚠️ **সতর্কতা**: Token কখনো publicly share করবেন না বা GitHub এ upload করবেন না!

---

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ Yes | Telegram Bot Token from @BotFather |
| `PORT` | Optional | Server port (default: 10000) |
| `RENDER_EXTERNAL_URL` | Auto | Set automatically by Render |
| `PYTHON_VERSION` | Optional | `3.11.0` recommended |

---

## 🐛 Common Issues & Solutions

### ❌ Bot doesn't respond
- **Cause**: Webhook not set correctly
- **Fix**: Check logs in Render dashboard. Look for `Webhook set successfully` message
- **Fix**: Ensure `BOT_TOKEN` is correct in environment variables

### ❌ `ModuleNotFoundError`
- **Cause**: Dependencies not installed
- **Fix**: Ensure `requirements.txt` is in root and Build Command is `pip install -r requirements.txt`

### ❌ Bot works locally but not on Render
- **Cause**: Polling mode running instead of webhook
- **Fix**: Do NOT pass `--polling` flag in production. The `Procfile` should use `python bot.py`

### ❌ "Webhook was not set" error
- **Cause**: `RENDER_EXTERNAL_URL` not available
- **Fix**: Wait for full deployment — Render sets this URL only after first successful deploy. Redeploy once.

### ❌ Free tier bot goes to sleep
- **Cause**: Render free tier sleeps after 15 minutes of inactivity
- **Fix**: Upgrade to a paid plan, or use a service like UptimeRobot to ping your URL every 5 minutes

### ❌ File too large error
- **Cause**: Telegram limits file downloads via bots
- **Fix**: Telegram bot API supports files up to 20MB for downloads. The bot handles this gracefully.

### ❌ Bangla text not showing
- **Cause**: Encoding issue in older systems
- **Fix**: Ensure Python 3.11+ and UTF-8 encoding. The bot uses `# -*- coding: utf-8 -*-`

---

## 📁 Project Structure

```
crypthon-so-decoder-bot/
├── bot.py                    # Main bot application
├── decoders/
│   ├── __init__.py
│   ├── crypthon_decoder.py   # Crypthon/obfuscation decoder
│   └── so_decoder.py         # .so file analyzer
├── utils/
│   ├── __init__.py
│   └── helpers.py            # Utility functions
├── requirements.txt
├── Procfile                  # Render/Heroku process file
├── .env.example              # Example environment variables
├── render.yaml               # Render deployment config
├── .gitignore
└── README.md
```

---

## 📜 License

MIT License — feel free to use, modify, and distribute.

---

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first.

---

*Made with ❤️ for the Python community in Bangladesh & India*
