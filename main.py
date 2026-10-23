import os
import logging
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

bot = telebot.TeleBot(TOKEN)
users = set()
broadcast_mode = False
forward_mode = False
download_mode = False

def is_owner(message):
    return message.from_user.id == OWNER_ID

def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("👨‍💻 مراسلة المالك"))
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📢 الإذاعة: إيقاف", "🔁 التوجيه: إيقاف")
    markup.row("📥 التحميل: إيقاف", "📊 الإحصائيات")
    return markup

@bot.message_handler(commands=["start"])
def start(message):
    users.add(message.from_user.id)
    if is_owner(message):
        bot.send_message(message.chat.id, "أهلًا بك في لوحة تحكم المالك 👑",
                         reply_markup=admin_menu())
    else:
        bot.send_message(message.chat.id,
                         "أهلًا بك في بوت تحميل الفيديوهات 🎬\n"
                         "أرسل رابط يوتيوب للبدء، أو راسل المالك.",
                         reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "👨‍💻 مراسلة المالك")
def contact_owner(message):
    if OWNER_ID:
        bot.send_message(OWNER_ID,
            f"📩 مستخدم يريد التواصل مع المالك\n"
            f"الاسم: {message.from_user.first_name}\n"
            f"المعرف: @{message.from_user.username or 'لا يوجد'}\n"
            f"الآيدي: {message.from_user.id}")
        bot.send_message(message.chat.id, "✅ تم إبلاغ المالك برغبتك في التواصل.")
    else:
        bot.send_message(message.chat.id, "الخدمة غير مهيأة حاليًا.")

@bot.message_handler(func=lambda m: m.text in [
    "📢 الإذاعة: إيقاف", "📢 الإذاعة: تشغيل",
    "🔁 التوجيه: إيقاف", "🔁 التوجيه: تشغيل",
    "📥 التحميل: إيقاف", "📥 التحميل: تشغيل", "📊 الإحصائيات"])
def admin_actions(message):
    global broadcast_mode, forward_mode, download_mode
    if not is_owner(message):
        return

    if message.text.startswith("📢 الإذاعة"):
        broadcast_mode = not broadcast_mode
    elif message.text.startswith("🔁 التوجيه"):
        forward_mode = not forward_mode
    elif message.text.startswith("📥 التحميل"):
        download_mode = not download_mode
    elif message.text == "📊 الإحصائيات":
        bot.send_message(message.chat.id,
                         f"عدد المستخدمين منذ تشغيل البوت: {len(users)}")
        return

    markup = admin_menu()
    markup.keyboard[0][0].text = (
        "📢 الإذاعة: تشغيل" if broadcast_mode else "📢 الإذاعة: إيقاف")
    markup.keyboard[0][1].text = (
        "🔁 التوجيه: تشغيل" if forward_mode else "🔁 التوجيه: إيقاف")
    markup.keyboard[1][0].text = (
        "📥 التحميل: تشغيل" if download_mode else "📥 التحميل: إيقاف")
    bot.send_message(message.chat.id, "تم تحديث الإعدادات.", reply_markup=markup)

@bot.message_handler(content_types=["text", "photo", "video", "document", "audio"])
def messages(message):
    users.add(message.from_user.id)

    if is_owner(message) and broadcast_mode:
        bot.send_message(message.chat.id, "أرسل /broadcast متبوعًا برسالتك للإذاعة.")
        return

    if not is_owner(message) and forward_mode:
        bot.forward_message(OWNER_ID, message.chat.id, message.message_id)

    if message.text and "youtube.com" in message.text or (
        message.text and "youtu.be" in message.text
    ):
        bot.send_message(message.chat.id,
            "وصل الرابط 🎬\nخدمة التنزيل ستُفعّل بعد إعداد محرك التحميل.")
        return

    if not is_owner(message) and OWNER_ID and message.text != "👨‍💻 مراسلة المالك":
        bot.send_message(OWNER_ID,
            f"📩 رسالة من مستخدم\nالآيدي: {message.from_user.id}\n"
            f"الرسالة: {message.text or '[رسالة غير نصية]'}")

from flask import Flask
import threading
import os
import logging

app = Flask(__name__)

@app.route("/")
def home():
    return "YouTube Downloader Bot is running!"

def run_bot():
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
