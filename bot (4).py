"""
╔══════════════════════════════════════════════════════════════╗
║        🐍 Python File Hosting Bot - Telegram                 ║
║        『 | 𝘼𝙡𝙤𝙧𝙙 𝙕𝙖𝙮𝙧𝙤 🖤 | 』                           ║
║        Developer: @ZY4_R                                     ║
╚══════════════════════════════════════════════════════════════╝

pip install:
    pip install pyTelegramBotAPI==4.22.1 aiohttp==3.10.5

Run:
    python bot.py
"""

# ── Standard Library ─────────────────────────────────────────────────────────
import os
import io
import sys
import time
import sqlite3
import logging
import threading
import subprocess
import urllib.request
from datetime import datetime, date
from functools import wraps

# ── Third-party ───────────────────────────────────────────────────────────────
import telebot  # pyTelegramBotAPI
from telebot import types

# ═══════════════════════════════════════════════════════════════════════════════
#  ⚙️  STATIC CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
BOT_TOKEN   = "8585218786:AAFEwEpntRXpnjEJCCGFBFraTESg7mUAjFQ"
ADMIN_ID    = 8405827532
DEV_USER    = "@ZY4_R"
RIGHTS_TAG  = "『 | 𝘼𝙡𝙤𝙧𝙙 𝙕𝙖𝙮𝙧𝙤 🖤 | 』"

# Limits
FREE_FILE_LIMIT = 5          # ملفات مسموح بها للمستخدم المجاني
CHUNK_SIZE      = 1024 * 512  # 512 KB chunk size لرفع الملفات الكبيرة

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  🗄️  DATABASE LAYER  (SQLite)
# ═══════════════════════════════════════════════════════════════════════════════
DB_PATH = "hosting_bot.db"

def get_conn():
    """إرجاع اتصال SQLite مع دعم الخيوط المتعددة"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # أداء أفضل مع القراءة/الكتابة المتزامنة
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """إنشاء جداول قاعدة البيانات إذا لم تكن موجودة"""
    conn = get_conn()
    cur  = conn.cursor()

    # جدول المستخدمين
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            joined_at   TEXT DEFAULT (datetime('now')),
            is_vip      INTEGER DEFAULT 0,      -- 1 = مدفوع
            points      INTEGER DEFAULT 0,
            last_gift   TEXT DEFAULT '',        -- تاريخ آخر هدية يومية
            ref_by      INTEGER DEFAULT 0,      -- معرّف من أحاله
            file_count  INTEGER DEFAULT 0       -- عدد الملفات المرفوعة
        )
    """)

    # جدول الملفات المستضافة
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            file_id     TEXT,               -- file_id في تيليجرام
            file_name   TEXT,
            file_size   INTEGER,
            uploaded_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    # جدول الإعدادات العامة للبوت
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # القيم الافتراضية للإعدادات
    defaults = {
        "subscription_enabled": "0",    # تفعيل الاشتراك الإجباري
        "channel_username"    : "",     # يوزر القناة (بدون @)
        "payment_mode"        : "free", # free | paid
        "daily_gift_points"   : "10",   # نقاط الهدية اليومية
        "referral_points"     : "5",    # نقاط لكل إحالة
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()
    log.info("✅ Database initialized.")

# ── DB Helper Functions ────────────────────────────────────────────────────────

def setting_get(key: str) -> str:
    conn = get_conn()
    row  = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else ""

def setting_set(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def ensure_user(user: types.User):
    """تسجيل المستخدم إذا لم يكن موجودًا"""
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
    """, (user.id, user.username or "", user.full_name))
    # تحديث بيانات الاسم عند كل تفاعل
    conn.execute("""
        UPDATE users SET username=?, full_name=?
        WHERE user_id=?
    """, (user.username or "", user.full_name, user.id))
    conn.commit()
    conn.close()

def get_user(user_id: int) -> dict | None:
    conn = get_conn()
    row  = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_user_ids() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

def set_vip(user_id: int, status: int):
    conn = get_conn()
    conn.execute("UPDATE users SET is_vip=? WHERE user_id=?", (status, user_id))
    conn.commit()
    conn.close()

def add_points(user_id: int, pts: int):
    conn = get_conn()
    conn.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, user_id))
    conn.commit()
    conn.close()

def save_file_record(user_id: int, file_id: str, file_name: str, file_size: int):
    conn = get_conn()
    conn.execute("""
        INSERT INTO files (user_id, file_id, file_name, file_size)
        VALUES (?, ?, ?, ?)
    """, (user_id, file_id, file_name, file_size))
    conn.execute("UPDATE users SET file_count = file_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_user_files(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM files WHERE user_id=? ORDER BY uploaded_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_file_count(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute("SELECT file_count FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["file_count"] if row else 0

def process_referral(new_user_id: int, ref_id: int):
    """منح نقاط الإحالة للمُحيل"""
    if ref_id and ref_id != new_user_id:
        pts = int(setting_get("referral_points") or 5)
        add_points(ref_id, pts)
        conn = get_conn()
        conn.execute("UPDATE users SET ref_by=? WHERE user_id=?", (ref_id, new_user_id))
        conn.commit()
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  🤖  BOT INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=8)

# ── Signature Footer ───────────────────────────────────────────────────────────
FOOTER = f"\n\n`{RIGHTS_TAG}`"

# ── Decorators / Guards ────────────────────────────────────────────────────────

def admin_only(func):
    """مُزيّن: يسمح فقط للأدمن"""
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "🚫 *هذا الأمر للأدمن فقط.*", parse_mode="Markdown")
            return
        return func(message, *args, **kwargs)
    return wrapper

def check_subscription(user_id: int) -> bool:
    """التحقق من اشتراك المستخدم في القناة الإجبارية"""
    if setting_get("subscription_enabled") != "1":
        return True
    channel = setting_get("channel_username")
    if not channel:
        return True
    try:
        member = bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def subscription_guard(func):
    """مُزيّن: يتحقق من الاشتراك الإجباري"""
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        uid = message.from_user.id
        if uid == ADMIN_ID:
            return func(message, *args, **kwargs)
        if not check_subscription(uid):
            channel = setting_get("channel_username")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{channel}"))
            kb.add(types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_sub"))
            bot.reply_to(
                message,
                f"⚠️ *يجب الاشتراك في قناتنا أولاً!*\n\n👇 اضغط للاشتراك ثم تحقق:{FOOTER}",
                parse_mode="Markdown",
                reply_markup=kb
            )
            return
        return func(message, *args, **kwargs)
    return wrapper

# ═══════════════════════════════════════════════════════════════════════════════
#  🎨  KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════════

def main_menu_kb(user_id: int) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📂 ملفاتي", "⬆️ رفع ملف")
    kb.add("💎 نقاطي", "🎁 هدية يومية")
    kb.add("🔗 رابط الإحالة", "ℹ️ معلوماتي")
    if user_id == ADMIN_ID:
        kb.add("⚙️ لوحة التحكم")
    return kb

def admin_panel_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📢 الاشتراك الإجباري", callback_data="adm_subscription"),
        types.InlineKeyboardButton("📣 بث رسالة",          callback_data="adm_broadcast"),
    )
    kb.add(
        types.InlineKeyboardButton("💳 وضع الدفع",         callback_data="adm_payment"),
        types.InlineKeyboardButton("👑 إدارة VIP",         callback_data="adm_vip"),
    )
    kb.add(
        types.InlineKeyboardButton("🎁 نقاط الهدية",       callback_data="adm_gift_pts"),
        types.InlineKeyboardButton("🔗 نقاط الإحالة",      callback_data="adm_ref_pts"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 إحصائيات",           callback_data="adm_stats"),
    )
    return kb

# ═══════════════════════════════════════════════════════════════════════════════
#  🚀  COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message):
    user = message.from_user
    ensure_user(user)

    # معالجة رابط الإحالة  /start ref_<id>
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_id = int(args[1].split("_")[1])
            udata  = get_user(user.id)
            if udata and udata["ref_by"] == 0:
                process_referral(user.id, ref_id)
                bot.send_message(
                    ref_id,
                    f"🎉 *مستخدم جديد انضم عبر رابطك!*\n"
                    f"لقد حصلت على `{setting_get('referral_points')}` نقاط 🏆{FOOTER}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            log.warning(f"Referral error: {e}")

    text = (
        f"👋 *أهلاً {user.first_name}!*\n\n"
        f"🐍 مرحباً بك في *بوت استضافة ملفات Python*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 يمكنك رفع ملفات `.py` واستضافتها بأمان\n"
        f"🎁 احصل على نقاط يومية ومكافآت الإحالة\n"
        f"━━━━━━━━━━━━━━━━━━━━━{FOOTER}"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown",
                     reply_markup=main_menu_kb(user.id))


@bot.message_handler(commands=["admin"])
@admin_only
def cmd_admin(message: types.Message):
    bot.send_message(
        message.chat.id,
        f"⚙️ *لوحة تحكم المشرف*\n\n"
        f"اختر أحد الخيارات أدناه:{FOOTER}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb()
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  📋  TEXT HANDLERS  (الأزرار النصية)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == "⚙️ لوحة التحكم")
@admin_only
def handle_admin_panel(message):
    cmd_admin(message)


@bot.message_handler(func=lambda m: m.text == "📂 ملفاتي")
@subscription_guard
def handle_my_files(message: types.Message):
    uid   = message.from_user.id
    files = get_user_files(uid)
    if not files:
        bot.reply_to(message, f"📭 *لا توجد ملفات مرفوعة بعد.*{FOOTER}", parse_mode="Markdown")
        return

    text = f"📂 *ملفاتك المرفوعة ({len(files)})*\n{'━'*22}\n"
    for i, f in enumerate(files, 1):
        size_kb = f["file_size"] // 1024 if f["file_size"] else 0
        text   += f"`{i}.` 🐍 `{f['file_name']}` — *{size_kb} KB*\n"
    text += FOOTER

    kb = types.InlineKeyboardMarkup()
    for f in files:
        kb.add(types.InlineKeyboardButton(
            f"📥 {f['file_name']}", callback_data=f"dl_{f['id']}"
        ))
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)


@bot.message_handler(func=lambda m: m.text == "⬆️ رفع ملف")
@subscription_guard
def handle_upload_prompt(message: types.Message):
    uid  = message.from_user.id
    udat = get_user(uid)
    mode = setting_get("payment_mode")

    # التحقق من الوضع المدفوع
    if mode == "paid" and uid != ADMIN_ID and (not udat or not udat["is_vip"]):
        bot.reply_to(
            message,
            f"🔒 *البوت في الوضع المدفوع حالياً.*\n"
            f"للترقية تواصل مع المطور: {DEV_USER}{FOOTER}",
            parse_mode="Markdown"
        )
        return

    # حد الملفات للمستخدمين المجانيين
    if uid != ADMIN_ID and (not udat or not udat["is_vip"]):
        count = get_file_count(uid)
        if count >= FREE_FILE_LIMIT:
            bot.reply_to(
                message,
                f"⚠️ *لقد وصلت للحد الأقصى* ({FREE_FILE_LIMIT} ملفات)!\n"
                f"🌟 للحصول على حساب VIP تواصل مع: {DEV_USER}{FOOTER}",
                parse_mode="Markdown"
            )
            return

    msg = bot.reply_to(
        message,
        f"📤 *أرسل ملف `.py` الآن*\n\n"
        f"⚡️ سيتم رفعه واستضافته فوراً.{FOOTER}",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, receive_python_file)


@bot.message_handler(func=lambda m: m.text == "💎 نقاطي")
@subscription_guard
def handle_points(message: types.Message):
    uid  = message.from_user.id
    udat = get_user(uid)
    pts  = udat["points"] if udat else 0
    vip  = "✅ VIP" if udat and udat["is_vip"] else "🆓 مجاني"
    bot.reply_to(
        message,
        f"💎 *نقاطك الحالية:* `{pts}` نقطة\n"
        f"👤 *نوع الحساب:* {vip}{FOOTER}",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "🎁 هدية يومية")
@subscription_guard
def handle_daily_gift(message: types.Message):
    uid     = message.from_user.id
    ensure_user(message.from_user)
    udat    = get_user(uid)
    today   = str(date.today())
    last    = udat.get("last_gift", "") if udat else ""
    gift_pts = int(setting_get("daily_gift_points") or 10)

    if last == today:
        bot.reply_to(
            message,
            f"⏰ *لقد استلمت هديتك اليومية بالفعل!*\n"
            f"عُد غداً للحصول على مزيد من النقاط 🎁{FOOTER}",
            parse_mode="Markdown"
        )
        return

    # منح النقاط وتحديث التاريخ
    add_points(uid, gift_pts)
    conn = get_conn()
    conn.execute("UPDATE users SET last_gift=? WHERE user_id=?", (today, uid))
    conn.commit()
    conn.close()

    bot.reply_to(
        message,
        f"🎁 *مبروك!* حصلت على `{gift_pts}` نقطة اليوم 🎉\n"
        f"💎 رصيدك الكلي: `{(udat['points'] if udat else 0) + gift_pts}` نقطة{FOOTER}",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "🔗 رابط الإحالة")
@subscription_guard
def handle_referral(message: types.Message):
    uid  = message.from_user.id
    link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
    bot.reply_to(
        message,
        f"🔗 *رابط الإحالة الخاص بك:*\n`{link}`\n\n"
        f"📊 تحصل على `{setting_get('referral_points')}` نقطة لكل شخص يدخل عبر رابطك!{FOOTER}",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "ℹ️ معلوماتي")
@subscription_guard
def handle_info(message: types.Message):
    user = message.from_user
    uid  = user.id
    udat = get_user(uid)
    if not udat:
        udat = {}
    vip  = "👑 VIP" if udat.get("is_vip") else "🆓 مجاني"
    bot.reply_to(
        message,
        f"👤 *معلوماتك:*\n{'━'*20}\n"
        f"🆔 المعرّف: `{uid}`\n"
        f"👤 الاسم: `{user.full_name}`\n"
        f"💳 النوع: {vip}\n"
        f"💎 النقاط: `{udat.get('points', 0)}`\n"
        f"📂 عدد الملفات: `{udat.get('file_count', 0)}`\n"
        f"📅 الانضمام: `{udat.get('joined_at', 'N/A')}`{FOOTER}",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  📤  FILE UPLOAD → AUTO-INSTALL → RUN  (نظام الاستضافة الحقيقي)
# ═══════════════════════════════════════════════════════════════════════════════

import ast
import re
import pkgutil

# مجلد حفظ ملفات المستخدمين على الخادم
HOSTING_DIR = os.path.abspath("hosted_files")
os.makedirs(HOSTING_DIR, exist_ok=True)

# قاموس لتتبع العمليات الجارية {user_id: {"proc": Popen, "name": str, "output": list}}
running_processes: dict = {}

# المكتبات المدمجة في Python التي لا تحتاج تثبيت
STDLIB_MODULES = set(m.name for m in pkgutil.iter_modules()) | {
    "os", "sys", "io", "re", "json", "time", "math", "random", "datetime",
    "collections", "itertools", "functools", "pathlib", "threading", "subprocess",
    "socket", "struct", "hashlib", "base64", "urllib", "http", "email",
    "logging", "argparse", "typing", "abc", "copy", "gc", "inspect",
    "traceback", "warnings", "contextlib", "dataclasses", "enum", "string",
    "textwrap", "pprint", "shutil", "glob", "fnmatch", "tempfile", "stat",
    "queue", "asyncio", "concurrent", "multiprocessing", "signal", "sqlite3",
    "csv", "configparser", "pickle", "shelve", "zipfile", "tarfile", "gzip",
    "zlib", "bz2", "lzma", "xml", "html", "unittest", "doctest", "platform",
    "builtins", "__future__", "ast", "dis", "token", "tokenize", "keyword",
    "operator", "array", "struct", "weakref", "heapq", "bisect",
}

# خريطة تحويل اسم الاستيراد → اسم حزمة pip
IMPORT_TO_PIP = {
    "cv2":            "opencv-python",
    "PIL":            "Pillow",
    "sklearn":        "scikit-learn",
    "bs4":            "beautifulsoup4",
    "yaml":           "PyYAML",
    "dotenv":         "python-dotenv",
    "telegram":       "pyTelegramBotAPI",
    "telebot":        "pyTelegramBotAPI",
    "aiogram":        "aiogram",
    "pyrogram":       "pyrogram",
    "telethon":       "Telethon",
    "flask":          "Flask",
    "fastapi":        "fastapi",
    "uvicorn":        "uvicorn",
    "django":         "Django",
    "sqlalchemy":     "SQLAlchemy",
    "pymongo":        "pymongo",
    "redis":          "redis",
    "celery":         "celery",
    "pydantic":       "pydantic",
    "httpx":          "httpx",
    "aiohttp":        "aiohttp",
    "requests":       "requests",
    "numpy":          "numpy",
    "pandas":         "pandas",
    "matplotlib":     "matplotlib",
    "seaborn":        "seaborn",
    "scipy":          "scipy",
    "tensorflow":     "tensorflow",
    "torch":          "torch",
    "keras":          "keras",
    "transformers":   "transformers",
    "nltk":           "nltk",
    "spacy":          "spacy",
    "cryptography":   "cryptography",
    "paramiko":       "paramiko",
    "psutil":         "psutil",
    "click":          "click",
    "rich":           "rich",
    "tqdm":           "tqdm",
    "colorama":       "colorama",
    "loguru":         "loguru",
    "apscheduler":    "APScheduler",
    "schedule":       "schedule",
    "pyaudio":        "PyAudio",
    "pynput":         "pynput",
    "pyautogui":      "pyautogui",
    "selenium":       "selenium",
    "playwright":     "playwright",
    "scrapy":         "Scrapy",
    "discord":        "discord.py",
    "nextcord":       "nextcord",
    "tweepy":         "tweepy",
    "instagrapi":     "instagrapi",
    "vk_api":         "vk-api",
    "motor":          "motor",
    "tortoise":       "tortoise-orm",
    "peewee":         "peewee",
    "alembic":        "alembic",
    "stripe":         "stripe",
    "googletrans":    "googletrans==4.0.0-rc1",
    "pyperclip":      "pyperclip",
    "qrcode":         "qrcode",
    "barcode":        "python-barcode",
    "docx":           "python-docx",
    "openpyxl":       "openpyxl",
    "xlrd":           "xlrd",
    "fpdf":           "fpdf2",
    "reportlab":      "reportlab",
    "pyttsx3":        "pyttsx3",
    "gtts":           "gTTS",
    "speech_recognition": "SpeechRecognition",
}


def extract_imports(source_code: str) -> list[str]:
    """
    يقرأ كود Python ويستخرج أسماء جميع المكتبات المُستوردة
    باستخدام AST لدقة أعلى من regex
    """
    imports = set()
    try:
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # خذ فقط الاسم الأول (مثلاً: requests من requests.auth)
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
    except SyntaxError:
        # fallback: استخدم regex إذا فشل AST
        for match in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", source_code, re.MULTILINE):
            imports.add(match.group(1))
    return list(imports)


def get_missing_packages(imports: list[str]) -> list[str]:
    """
    يقارن قائمة الاستيرادات بالمكتبات المثبتة ويُرجع المفقودة منها
    """
    missing = []
    for imp in imports:
        # تجاهل المكتبات المدمجة في Python
        if imp in STDLIB_MODULES:
            continue
        try:
            __import__(imp)
            # المكتبة موجودة بالفعل ✅
        except ImportError:
            # غير موجودة → نحتاج نثبتها
            pkg = IMPORT_TO_PIP.get(imp, imp)  # حوّل اسم الاستيراد → اسم pip
            if pkg not in missing:
                missing.append(pkg)
        except Exception:
            pass  # أخطاء أخرى نتجاهلها
    return missing


def install_packages(packages: list[str], status_callback=None) -> tuple[bool, str]:
    """
    يثبّت قائمة حزم pip واحدة تلو الأخرى.
    يُرجع (نجاح: bool, تقرير: str)
    """
    report_lines = []
    for pkg in packages:
        if status_callback:
            status_callback(f"📦 جاري تثبيت `{pkg}`...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg,
                 "--quiet", "--no-warn-script-location"],
                capture_output=True,
                text=True,
                timeout=120   # حد أقصى دقيقتان للحزمة الواحدة
            )
            if result.returncode == 0:
                report_lines.append(f"✅ {pkg}")
                log.info(f"📦 Installed: {pkg}")
            else:
                err = result.stderr.strip()[-200:]
                report_lines.append(f"❌ {pkg}: {err}")
                log.warning(f"📦 Failed to install {pkg}: {err}")
        except subprocess.TimeoutExpired:
            report_lines.append(f"⏰ {pkg}: انتهت مهلة التثبيت")
        except Exception as e:
            report_lines.append(f"❌ {pkg}: {e}")
    return True, "\n".join(report_lines)


def kill_user_process(uid: int):
    """إيقاف أي عملية سابقة للمستخدم"""
    entry = running_processes.get(uid)
    if entry:
        proc = entry.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.info(f"🛑 Killed old process uid={uid}")


def receive_python_file(message: types.Message):
    """
    الدالة الرئيسية لاستقبال ملف .py:
    1. تحميل الملف بنظام Chunks
    2. حفظه على القرص
    3. قراءة الكود واستخراج المكتبات
    4. تثبيت المكتبات المفقودة تلقائياً
    5. تشغيل الملف كسيرفر حقيقي في الخلفية
    6. إرسال النتيجة للمستخدم
    """
    if not message.document:
        bot.reply_to(message, "❌ *يرجى إرسال ملف `.py` صالح.*", parse_mode="Markdown")
        return

    doc = message.document

    # ─── التحقق من الامتداد ───────────────────────────────────────────────────
    if not doc.file_name.endswith(".py"):
        bot.reply_to(
            message,
            f"❌ *امتداد الملف غير مدعوم!*\nيُسمح فقط بملفات `.py`{FOOTER}",
            parse_mode="Markdown"
        )
        return

    uid       = message.from_user.id
    file_size = doc.file_size or 0
    chat_id   = message.chat.id

    # ─── رسالة حالة (ستُحدَّث باستمرار) ─────────────────────────────────────
    wait_msg = bot.reply_to(
        message,
        f"📥 *جاري تحميل الملف...*\n📦 الحجم: `{file_size // 1024} KB`{FOOTER}",
        parse_mode="Markdown"
    )

    def update_status(text: str):
        """تحديث رسالة الحالة بدون إزعاج"""
        try:
            bot.edit_message_text(
                text + FOOTER,
                chat_id=chat_id,
                message_id=wait_msg.message_id,
                parse_mode="Markdown"
            )
        except Exception:
            pass

    def run_pipeline():
        """كامل خط الاستقبال→تثبيت→تشغيل في خيط منفصل"""
        try:
            # ══ STEP 1: تحميل الملف بنظام Chunks ══════════════════════════════
            update_status(f"📥 *[1/4] جاري تحميل الملف...*\n`{doc.file_name}`")

            file_info = bot.get_file(doc.file_id)
            file_url  = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

            raw_bytes = io.BytesIO()
            with urllib.request.urlopen(file_url) as resp:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    raw_bytes.write(chunk)

            raw_bytes.seek(0)
            source_code = raw_bytes.getvalue().decode("utf-8", errors="replace")
            log.info(f"✅ Downloaded: {doc.file_name} ({file_size}B) uid={uid}")

            # ══ STEP 2: حفظ الملف على القرص ═══════════════════════════════════
            update_status(f"💾 *[2/4] جاري حفظ الملف على السيرفر...*\n`{doc.file_name}`")

            user_dir  = os.path.join(HOSTING_DIR, str(uid))
            os.makedirs(user_dir, exist_ok=True)
            save_path = os.path.join(user_dir, doc.file_name)

            with open(save_path, "wb") as f:
                f.write(raw_bytes.getvalue())

            log.info(f"💾 Saved: {save_path}")

            # حفظ في DB
            save_file_record(uid, doc.file_id, doc.file_name, file_size)

            # إرسال نسخة للمراقب (الأدمن)
            try:
                raw_bytes.seek(0)
                bot.send_document(
                    ADMIN_ID,
                    raw_bytes,
                    caption=(
                        f"🔍 *[مراقب الملفات]*\n"
                        f"👤 المستخدم: `{uid}` | @{message.from_user.username or 'N/A'}\n"
                        f"📄 الملف: `{doc.file_name}`\n"
                        f"📦 الحجم: `{file_size // 1024} KB`\n"
                        f"📅 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
                    ),
                    visible_file_name=doc.file_name,
                    parse_mode="Markdown"
                )
            except Exception as e:
                log.warning(f"Monitor->admin failed: {e}")

            # ══ STEP 3: اكتشاف المكتبات وتثبيتها ════════════════════════════
            update_status(f"🔍 *[3/4] جاري فحص المكتبات المطلوبة...*")

            imports  = extract_imports(source_code)
            missing  = get_missing_packages(imports)

            if missing:
                install_report = []
                update_status(
                    f"📦 *[3/4] جاري تثبيت {len(missing)} مكتبة تلقائياً...*\n"
                    f"`{'`, `'.join(missing)}`"
                )
                _, report = install_packages(
                    missing,
                    status_callback=lambda msg: update_status(f"📦 *[3/4] {msg}*")
                )
                log.info(f"📦 Install report:\n{report}")
            else:
                update_status(f"✅ *[3/4] جميع المكتبات موجودة بالفعل!*")
                time.sleep(0.5)

            # ══ STEP 4: تشغيل الملف فعلياً ═══════════════════════════════════
            update_status(f"🚀 *[4/4] جاري تشغيل الملف...*\n`{doc.file_name}`")

            # إيقاف أي عملية سابقة لنفس المستخدم
            kill_user_process(uid)

            # تشغيل الملف في الخلفية
            proc = subprocess.Popen(
                [sys.executable, "-u", save_path],  # -u = unbuffered output فوري
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=user_dir   # مجلد العمل = مجلد الملف (يحل مشكلة الاستيراد النسبي)
            )

            # تسجيل العملية مع buffer للـ output
            running_processes[uid] = {
                "proc"  : proc,
                "name"  : doc.file_name,
                "output": [],
                "pid"   : proc.pid,
            }
            log.info(f"🚀 Started PID={proc.pid} for uid={uid} file={doc.file_name}")

            # ─── انتظر 4 ثواني والتقط الـ output المبكر ──────────────────────
            output_lines = []
            deadline     = time.time() + 4  # انتظر 4 ثواني

            # اقرأ الـ output بطريقة non-blocking عبر خيط مؤقت
            output_buffer = []
            read_done     = threading.Event()

            def read_output():
                for line in proc.stdout:
                    output_buffer.append(line.rstrip())
                    running_processes.get(uid, {}).get("output", [])
                    if uid in running_processes:
                        running_processes[uid]["output"].append(line.rstrip())
                read_done.set()

            reader_thread = threading.Thread(target=read_output, daemon=True)
            reader_thread.start()

            # انتظر 4 ثواني أو حتى ينتهي البرنامج
            proc.wait(timeout=4) if False else time.sleep(4)

            exit_code = proc.poll()  # None = لا يزال يعمل (سيرفر)
            preview_lines = output_buffer[:25]
            preview = "\n".join(preview_lines) if preview_lines else "_(لا يوجد output حتى الآن — البوت يعمل في الخلفية)_"
            if len(preview) > 1500:
                preview = preview[:1500] + "\n..."

            # ─── بناء رسالة النتيجة ───────────────────────────────────────────
            if exit_code is None:
                # 🟢 البوت يعمل كسيرفر في الخلفية
                result_text = (
                    f"✅ *تم رفع الملف وتشغيله بنجاح!*\n"
                    f"{'━'*24}\n"
                    f"🐍 الملف: `{doc.file_name}`\n"
                    f"🔧 PID: `{proc.pid}`\n"
                    f"📡 الحالة: `🟢 يعمل كسيرفر في الخلفية`\n"
                    f"⏱️ `{datetime.now().strftime('%H:%M:%S')}`\n"
                    f"{'━'*24}\n"
                    f"📋 *Output المبكر:*\n```\n{preview}\n```"
                )
            elif exit_code == 0:
                # ✅ انتهى بنجاح (سكريبت بسيط)
                result_text = (
                    f"✅ *اكتمل تنفيذ الملف بنجاح!*\n"
                    f"{'━'*24}\n"
                    f"🐍 الملف: `{doc.file_name}`\n"
                    f"✔️ Exit Code: `0 (ناجح)`\n"
                    f"{'━'*24}\n"
                    f"📋 *Output:*\n```\n{preview}\n```"
                )
            else:
                # ❌ انتهى بخطأ
                result_text = (
                    f"❌ *توقف الملف بسبب خطأ!*\n"
                    f"{'━'*24}\n"
                    f"🐍 الملف: `{doc.file_name}`\n"
                    f"⚠️ Exit Code: `{exit_code}`\n"
                    f"{'━'*24}\n"
                    f"📋 *Error Output:*\n```\n{preview}\n```\n\n"
                    f"💡 تأكد من صحة الكود وحاول مرة أخرى."
                )

            update_status(result_text)

            # ─── أزرار التحكم (فقط إذا لا يزال يعمل) ────────────────────────
            if exit_code is None:
                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.add(
                    types.InlineKeyboardButton("🛑 إيقاف",      callback_data=f"stop_proc_{uid}"),
                    types.InlineKeyboardButton("📋 آخر Output", callback_data=f"out_proc_{uid}"),
                )
                kb.add(types.InlineKeyboardButton(
                    "🔄 إعادة التشغيل", callback_data=f"restart_proc_{uid}"
                ))
                bot.send_message(
                    chat_id,
                    f"🎛️ *لوحة التحكم بالسيرفر:*",
                    parse_mode="Markdown",
                    reply_markup=kb
                )

        except Exception as e:
            log.error(f"Pipeline error uid={uid}: {e}")
            update_status(
                f"❌ *حدث خطأ في خط الاستضافة!*\n"
                f"```\n{str(e)[:400]}\n```\n"
                f"تواصل مع: {DEV_USER}"
            )

    # ─── شغّل كامل العملية في خيط منفصل لعدم تجميد البوت ────────────────────
    t = threading.Thread(target=run_pipeline, daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
#  🎛️  أزرار التحكم بالسيرفر (إيقاف / Output / إعادة تشغيل)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data.startswith("stop_proc_"))
def cb_stop_proc(call: types.CallbackQuery):
    """إيقاف العملية الجارية"""
    target_uid = int(call.data.split("_")[2])
    if call.from_user.id != target_uid and call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🚫 ليس لديك صلاحية!", show_alert=True)
        return

    entry = running_processes.get(target_uid)
    if entry:
        proc = entry.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            bot.answer_callback_query(call.id, "🛑 تم الإيقاف.")
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id, call.message.message_id, reply_markup=None
                )
            except Exception: pass
            bot.send_message(
                call.message.chat.id,
                f"🛑 *تم إيقاف السيرفر بنجاح.*\n"
                f"الملف: `{entry.get('name', 'N/A')}`{FOOTER}",
                parse_mode="Markdown"
            )
            return
    bot.answer_callback_query(call.id, "ℹ️ العملية لم تعد تعمل.", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("out_proc_"))
def cb_out_proc(call: types.CallbackQuery):
    """عرض آخر output من العملية"""
    target_uid = int(call.data.split("_")[2])
    if call.from_user.id != target_uid and call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🚫 ليس لديك صلاحية!", show_alert=True)
        return

    entry = running_processes.get(target_uid)
    if not entry:
        bot.answer_callback_query(call.id, "❌ لا توجد عملية مسجلة.", show_alert=True)
        return

    proc       = entry.get("proc")
    output_buf = entry.get("output", [])
    status     = "🟢 تعمل" if proc and proc.poll() is None else f"🔴 توقفت (exit: {proc.poll() if proc else 'N/A'})"
    last_lines = output_buf[-20:] if output_buf else []
    preview    = "\n".join(last_lines) if last_lines else "_(لا يوجد output)_"
    if len(preview) > 1500:
        preview = preview[-1500:]

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"📊 *Output السيرفر*\n"
        f"{'━'*22}\n"
        f"📄 الملف: `{entry.get('name', 'N/A')}`\n"
        f"🔧 PID: `{entry.get('pid', 'N/A')}`\n"
        f"📡 الحالة: `{status}`\n"
        f"{'━'*22}\n"
        f"```\n{preview}\n```{FOOTER}",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("restart_proc_"))
def cb_restart_proc(call: types.CallbackQuery):
    """إعادة تشغيل السيرفر"""
    target_uid = int(call.data.split("_")[2])
    if call.from_user.id != target_uid and call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🚫 ليس لديك صلاحية!", show_alert=True)
        return

    entry = running_processes.get(target_uid)
    if not entry:
        bot.answer_callback_query(call.id, "❌ لا توجد عملية مسجلة.", show_alert=True)
        return

    file_name = entry.get("name", "")
    save_path = os.path.join(HOSTING_DIR, str(target_uid), file_name)

    if not os.path.exists(save_path):
        bot.answer_callback_query(call.id, "❌ الملف غير موجود على السيرفر!", show_alert=True)
        return

    # إيقاف القديم
    kill_user_process(target_uid)
    bot.answer_callback_query(call.id, "🔄 جاري إعادة التشغيل...")

    # تشغيل جديد
    try:
        user_dir = os.path.join(HOSTING_DIR, str(target_uid))
        proc = subprocess.Popen(
            [sys.executable, "-u", save_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=user_dir
        )
        running_processes[target_uid] = {
            "proc"  : proc,
            "name"  : file_name,
            "output": [],
            "pid"   : proc.pid,
        }

        def read_bg():
            for line in proc.stdout:
                if target_uid in running_processes:
                    running_processes[target_uid]["output"].append(line.rstrip())
        threading.Thread(target=read_bg, daemon=True).start()

        bot.send_message(
            call.message.chat.id,
            f"🔄 *تمت إعادة تشغيل السيرفر بنجاح!*\n"
            f"📄 الملف: `{file_name}`\n"
            f"🔧 PID الجديد: `{proc.pid}`{FOOTER}",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(
            call.message.chat.id,
            f"❌ *فشلت إعادة التشغيل!*\n```\n{e}\n```{FOOTER}",
            parse_mode="Markdown"
        )

# ═══════════════════════════════════════════════════════════════════════════════
#  🔘  CALLBACK QUERY HANDLERS  (لوحة التحكم)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def cb_check_sub(call: types.CallbackQuery):
    uid = call.from_user.id
    if check_subscription(uid):
        bot.answer_callback_query(call.id, "✅ تم التحقق! يمكنك الاستخدام الآن.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        ensure_user(call.from_user)
        bot.send_message(
            uid,
            f"🎉 *أهلاً! تم التحقق من اشتراكك.*{FOOTER}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(uid)
        )
    else:
        bot.answer_callback_query(call.id, "❌ لم تشترك بعد!", show_alert=True)


# ── Download file callback ─────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("dl_"))
def cb_download_file(call: types.CallbackQuery):
    fid = int(call.data.split("_")[1])
    conn = get_conn()
    row  = conn.execute("SELECT * FROM files WHERE id=? AND user_id=?",
                        (fid, call.from_user.id)).fetchone()
    conn.close()
    if not row:
        bot.answer_callback_query(call.id, "❌ الملف غير موجود!", show_alert=True)
        return
    bot.send_document(call.message.chat.id, row["file_id"],
                      caption=f"🐍 `{row['file_name']}`{FOOTER}",
                      parse_mode="Markdown")
    bot.answer_callback_query(call.id)


# ══════════════════════════════════════════
#  ⚙️  ADMIN CALLBACKS
# ══════════════════════════════════════════

def is_admin_call(call: types.CallbackQuery) -> bool:
    return call.from_user.id == ADMIN_ID

# ─── الاشتراك الإجباري ────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_subscription")
def cb_adm_subscription(call: types.CallbackQuery):
    if not is_admin_call(call): return
    enabled = setting_get("subscription_enabled")
    channel = setting_get("channel_username")
    status  = "✅ مفعّل" if enabled == "1" else "❌ معطّل"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🟢 تفعيل",   callback_data="sub_on"),
        types.InlineKeyboardButton("🔴 تعطيل",   callback_data="sub_off"),
    )
    kb.add(types.InlineKeyboardButton("✏️ تغيير القناة", callback_data="sub_setchan"))
    kb.add(types.InlineKeyboardButton("🔙 رجوع",          callback_data="adm_back"))

    bot.edit_message_text(
        f"📢 *إعدادات الاشتراك الإجباري*\n\n"
        f"الحالة: {status}\n"
        f"القناة: `{channel or 'غير محددة'}`{FOOTER}",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown", reply_markup=kb
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data in ("sub_on", "sub_off"))
def cb_sub_toggle(call):
    if not is_admin_call(call): return
    setting_set("subscription_enabled", "1" if call.data == "sub_on" else "0")
    bot.answer_callback_query(call.id, "✅ تم التحديث")
    cb_adm_subscription(call)

@bot.callback_query_handler(func=lambda c: c.data == "sub_setchan")
def cb_sub_setchan(call):
    if not is_admin_call(call): return
    msg = bot.send_message(
        call.message.chat.id,
        "✏️ *أرسل يوزر القناة بدون @:*",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, lambda m: (
        setting_set("channel_username", m.text.strip().lstrip("@")),
        bot.send_message(m.chat.id, f"✅ تم تحديد القناة: `@{m.text.strip().lstrip('@')}`{FOOTER}", parse_mode="Markdown")
    ))
    bot.answer_callback_query(call.id)


# ─── وضع الدفع ────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_payment")
def cb_adm_payment(call):
    if not is_admin_call(call): return
    mode = setting_get("payment_mode")
    status = "🆓 مجاني" if mode == "free" else "💳 مدفوع"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🆓 مجاني",  callback_data="pay_free"),
        types.InlineKeyboardButton("💳 مدفوع",  callback_data="pay_paid"),
    )
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

    bot.edit_message_text(
        f"💳 *وضع الدفع الحالي:* {status}{FOOTER}",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown", reply_markup=kb
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data in ("pay_free", "pay_paid"))
def cb_pay_toggle(call):
    if not is_admin_call(call): return
    setting_set("payment_mode", "free" if call.data == "pay_free" else "paid")
    bot.answer_callback_query(call.id, "✅ تم التحديث")
    cb_adm_payment(call)


# ─── إدارة VIP ────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_vip")
def cb_adm_vip(call):
    if not is_admin_call(call): return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ إضافة VIP",  callback_data="vip_add"),
        types.InlineKeyboardButton("➖ إزالة VIP",  callback_data="vip_remove"),
    )
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

    bot.edit_message_text(
        f"👑 *إدارة مستخدمي VIP*\n\nاختر العملية:{FOOTER}",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown", reply_markup=kb
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data in ("vip_add", "vip_remove"))
def cb_vip_action(call):
    if not is_admin_call(call): return
    action = call.data  # vip_add | vip_remove
    msg = bot.send_message(call.message.chat.id, "🆔 *أرسل معرّف المستخدم (ID):*", parse_mode="Markdown")
    def step(m):
        try:
            target_id = int(m.text.strip())
            if action == "vip_add":
                set_vip(target_id, 1)
                bot.send_message(m.chat.id,
                    f"✅ تم ترقية `{target_id}` إلى VIP 👑{FOOTER}", parse_mode="Markdown")
                try:
                    bot.send_message(target_id,
                        f"🎉 *تم ترقية حسابك إلى VIP!* 👑\nاستمتع بالمزايا الحصرية.{FOOTER}",
                        parse_mode="Markdown")
                except: pass
            else:
                set_vip(target_id, 0)
                bot.send_message(m.chat.id,
                    f"✅ تم إزالة VIP من `{target_id}`{FOOTER}", parse_mode="Markdown")
        except ValueError:
            bot.send_message(m.chat.id, "❌ معرّف غير صالح!")
    bot.register_next_step_handler(msg, step)
    bot.answer_callback_query(call.id)


# ─── نقاط الهدية اليومية ──────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_gift_pts")
def cb_adm_gift_pts(call):
    if not is_admin_call(call): return
    current = setting_get("daily_gift_points")
    msg = bot.send_message(
        call.message.chat.id,
        f"🎁 *نقاط الهدية الحالية:* `{current}`\n\nأرسل القيمة الجديدة:",
        parse_mode="Markdown"
    )
    def step(m):
        try:
            val = int(m.text.strip())
            setting_set("daily_gift_points", str(val))
            bot.send_message(m.chat.id, f"✅ تم تحديد نقاط الهدية اليومية: `{val}`{FOOTER}", parse_mode="Markdown")
        except:
            bot.send_message(m.chat.id, "❌ قيمة غير صالحة!")
    bot.register_next_step_handler(msg, step)
    bot.answer_callback_query(call.id)


# ─── نقاط الإحالة ─────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_ref_pts")
def cb_adm_ref_pts(call):
    if not is_admin_call(call): return
    current = setting_get("referral_points")
    msg = bot.send_message(
        call.message.chat.id,
        f"🔗 *نقاط الإحالة الحالية:* `{current}`\n\nأرسل القيمة الجديدة:",
        parse_mode="Markdown"
    )
    def step(m):
        try:
            val = int(m.text.strip())
            setting_set("referral_points", str(val))
            bot.send_message(m.chat.id, f"✅ تم تحديد نقاط الإحالة: `{val}`{FOOTER}", parse_mode="Markdown")
        except:
            bot.send_message(m.chat.id, "❌ قيمة غير صالحة!")
    bot.register_next_step_handler(msg, step)
    bot.answer_callback_query(call.id)


# ─── الإحصائيات ───────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_stats")
def cb_adm_stats(call):
    if not is_admin_call(call): return
    conn  = get_conn()
    users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    vips  = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_vip=1").fetchone()["c"]
    files = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    conn.close()

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

    bot.edit_message_text(
        f"📊 *إحصائيات البوت*\n{'━'*20}\n"
        f"👥 إجمالي المستخدمين: `{users}`\n"
        f"👑 مستخدمو VIP: `{vips}`\n"
        f"📂 إجمالي الملفات: `{files}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━{FOOTER}",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown", reply_markup=kb
    )
    bot.answer_callback_query(call.id)


# ─── البث (Broadcast) ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_broadcast")
def cb_adm_broadcast(call):
    if not is_admin_call(call): return
    msg = bot.send_message(
        call.message.chat.id,
        f"📣 *أرسل رسالة البث الآن*\n"
        f"_(نص أو صورة مع تعليق — سيُرسل لجميع المستخدمين)_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, do_broadcast)
    bot.answer_callback_query(call.id)

def do_broadcast(message: types.Message):
    """إرسال رسالة البث لجميع المستخدمين"""
    all_ids  = get_all_user_ids()
    success  = 0
    failed   = 0
    total    = len(all_ids)

    status_msg = bot.send_message(
        message.chat.id,
        f"📡 *جاري الإرسال...*\n`0 / {total}`",
        parse_mode="Markdown"
    )

    for i, uid in enumerate(all_ids, 1):
        try:
            if message.photo:
                bot.send_photo(
                    uid,
                    message.photo[-1].file_id,
                    caption=(message.caption or "") + FOOTER,
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(
                    uid,
                    (message.text or "") + FOOTER,
                    parse_mode="Markdown"
                )
            success += 1
        except Exception:
            failed += 1
        # تحديث حالة الإرسال كل 20 رسالة
        if i % 20 == 0 or i == total:
            try:
                bot.edit_message_text(
                    f"📡 *جاري الإرسال...*\n`{i} / {total}`",
                    message.chat.id, status_msg.message_id,
                    parse_mode="Markdown"
                )
            except: pass
        time.sleep(0.04)  # تأخير بسيط لتجنب Rate Limit

    bot.edit_message_text(
        f"✅ *اكتمل البث!*\n\n"
        f"✔️ نجح: `{success}`\n"
        f"❌ فشل: `{failed}`\n"
        f"📊 إجمالي: `{total}`{FOOTER}",
        message.chat.id, status_msg.message_id,
        parse_mode="Markdown"
    )


# ─── رجوع للقائمة الرئيسية ────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "adm_back")
def cb_adm_back(call):
    if not is_admin_call(call): return
    bot.edit_message_text(
        f"⚙️ *لوحة تحكم المشرف*\n\nاختر أحد الخيارات:{FOOTER}",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown", reply_markup=admin_panel_kb()
    )
    bot.answer_callback_query(call.id)

# ═══════════════════════════════════════════════════════════════════════════════
#  🛡️  GLOBAL ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

def handle_errors(exc_type, value, traceback):
    log.error(f"Unhandled exception: {exc_type.__name__}: {value}")

import sys
sys.excepthook = handle_errors

# ═══════════════════════════════════════════════════════════════════════════════
#  🚦  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    init_db()
    log.info("🚀 Bot started — polling...")
    log.info(f"👑 Admin ID : {ADMIN_ID}")
    log.info(f"🔖 Dev      : {DEV_USER}")

    bot.infinity_polling(
        timeout=30,
        long_polling_timeout=30,
        skip_pending=True,
        logger_level=logging.WARNING,
        allowed_updates=["message", "callback_query"]
    )

if __name__ == "__main__":
    main()
