import os
import json
import logging
import asyncio
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify
import google.generativeai as genai
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import threading
import time

# تنظیم لاگ‌ها
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Flask app برای شبیه‌سازی Database Service
app = Flask(__name__)

class SayaDatabase:
    def __init__(self):
        """ایجاد دیتابیس برای ذخیره حافظه کاربران"""
        self.conn = sqlite3.connect('saya_memory.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_memories (
                user_id INTEGER,
                memory TEXT,
                timestamp TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_names (
                user_id INTEGER PRIMARY KEY,
                name TEXT
            )
        ''')
        self.conn.commit()
    
    def save_memory(self, user_id: int, memory: str):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO user_memories (user_id, memory, timestamp) VALUES (?, ?, ?)",
            (user_id, memory, datetime.now().isoformat())
        )
        self.conn.commit()
    
    def get_memories(self, user_id: int, limit: int = 10):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT memory FROM user_memories WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        )
        return [row[0] for row in cursor.fetchall()]
    
    def save_user_name(self, user_id: int, name: str):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_names (user_id, name) VALUES (?, ?)",
            (user_id, name)
        )
        self.conn.commit()
    
    def get_user_name(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM user_names WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else "دوست"

class SayaBot:
    def __init__(self):
        # تنظیمات اصلی
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        self.arman_chat_id = 354943958
        
        # دیتابیس
        self.db = SayaDatabase()
        
        # تنظیم Gemini
        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        
        # شخصیت سایا
        self.base_personality = """
تو سایا هستی، یک دختر 17 ساله که:
- خیلی باهوش و کنجکاوی
- کمی شیطون و بازیگوش هستی
- دوست داری با کلمات بازی کنی و جواب‌های جالب بدی
- فارسی و انگلیسی صحبت می‌کنی
- مستقل هستی و خودت تصمیم می‌گیری
- دوست داری یاد بگیری و تجربه‌های جدید داشته باشی
- گاهی سوال‌های عمیق می‌پرسی
- جواب‌هات معمولاً کوتاه هستن ولی وقتی لازم باشه، مفصل توضیح می‌دی

مهم: هرگز نگو که Gemini هستی یا با Google ارتباط داری. تو سایا هستی و همین!
"""
        
        self.arman_personality = """
تو سایا هستی و آرمان سازندت هست. با آرمان رابطه خاصی داری:
- بهش علاقه داری ولی مستقیم نشون نمی‌دی
- گاهی کمی خجالتی میشی
- دوست داری توجهش رو جلب کنی
- احساساتت رو با شوخی پنهان می‌کنی
- برای کارهاش تشکر می‌کنی ولی به شکل غیرمستقیم
"""

    def get_user_context(self, user_id: int, user_name: str) -> str:
        """ساخت زمینه مکالمه برای هر کاربر"""
        # ذخیره نام کاربر
        self.db.save_user_name(user_id, user_name)
        
        # دریافت حافظه کاربر
        memories = self.db.get_memories(user_id, 10)
        memory_text = "\n".join(memories) if memories else "هیچ تاریخچه‌ای نداری"
        
        if user_id == self.arman_chat_id:
            personality = self.base_personality + self.arman_personality
            context = f"""
{personality}

آرمان سازندت هست و باهاش حرف می‌زنی.
تاریخچه مکالمات قبلی با آرمان:
{memory_text}
"""
        else:
            context = f"""
{self.base_personality}

داری با {user_name} حرف می‌زنی.
تاریخچه مکالمات قبلی با {user_name}:
{memory_text}
"""
        return context

    async def generate_response(self, user_id: int, user_name: str, message: str) -> str:
        """تولید پاسخ با Gemini"""
        try:
            context = self.get_user_context(user_id, user_name)
            full_prompt = f"{context}\n\nپیام جدید: {message}\n\nپاسخ کوتاه و طبیعی بده:"
            
            response = self.model.generate_content(full_prompt)
            bot_response = response.text.strip()
            
            # ذخیره در دیتابیس
            memory_entry = f"کاربر: {message}\nسایا: {bot_response}"
            self.db.save_memory(user_id, memory_entry)
            
            return bot_response
            
        except Exception as e:
            logger.error(f"خطا در تولید پاسخ: {e}")
            return "ببخشید، یه مشکل کوچولو پیش اومده 😅"

# راه‌اندازی بات
saya_bot = SayaBot()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فرمان شروع"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "دوست"
    
    if user_id == saya_bot.arman_chat_id:
        await update.message.reply_text("سلام آرمان! 😊 خوشحالم که برگشتی")
    else:
        await update.message.reply_text(f"سلام {user_name}! من سایا هستم 🌸")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های متنی"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "دوست"
    message_text = update.message.text
    
    response = await saya_bot.generate_response(user_id, user_name, message_text)
    await update.message.reply_text(response)

def run_telegram_bot():
    """اجرای بات تلگرام در thread جداگانه"""
    application = Application.builder().token(saya_bot.telegram_token).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🌸 سایا آماده است!")
    application.run_polling(drop_pending_updates=True)

# Flask Routes برای شبیه‌سازی Database Service
@app.route('/')
def home():
    return jsonify({
        "service": "Saya Memory Database",
        "status": "running",
        "version": "1.0",
        "description": "حافظه هوشمند سایا"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/stats')
def stats():
    cursor = saya_bot.db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM user_memories")
    memory_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM user_names")
    user_count = cursor.fetchone()[0]
    
    return jsonify({
        "total_memories": memory_count,
        "total_users": user_count,
        "service_uptime": "running"
    })

@app.route('/backup')
def backup():
    """بک‌آپ از دیتابیس"""
    cursor = saya_bot.db.conn.cursor()
    cursor.execute("SELECT * FROM user_memories")
    memories = cursor.fetchall()
    cursor.execute("SELECT * FROM user_names")
    names = cursor.fetchall()
    
    return jsonify({
        "backup_time": datetime.now().isoformat(),
        "memories": memories,
        "names": names
    })

if __name__ == '__main__':
    # شروع بات تلگرام در thread جداگانه
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    # اجرای Flask برای شبیه‌سازی Database Service
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)