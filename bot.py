import os
import asyncio
import sqlite3
import logging
import tempfile
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import yt_dlp

TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")
if not TOKEN or not OWNER_ID:
    raise RuntimeError("Set BOT_TOKEN and OWNER_ID environment variables.")

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
db = sqlite3.connect(DB_PATH)
db.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
db.commit()

def setting(key, default="0"):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def set_setting(key, value):
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    db.commit()

def save_user(user):
    db.execute("INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES(?,?,?)",
               (user.id, user.username or "", user.first_name or ""))
    db.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
               (user.username or "", user.first_name or "", user.id))
    db.commit()

def is_owner(user_id):
    return user_id == OWNER_ID

def user_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎬 تحميل من يوتيوب")],
        [KeyboardButton(text="💬 مراسلة المالك")]
    ], resize_keyboard=True)

def owner_keyboard():
    receive = "🟢 إيقاف استقبال الرسائل" if setting("inbox_enabled") == "1" else "📨 تفعيل استقبال الرسائل"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 الإحصائيات"), KeyboardButton(text="📢 إذاعة")],
        [KeyboardButton(text=receive)],
        [KeyboardButton(text="🏠 القائمة الرئيسية")]
    ], resize_keyboard=True)

class Flow(StatesGroup):
    waiting_link = State()
    waiting_owner_message = State()
    waiting_broadcast = State()
    waiting_reply = State()

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    save_user(message.from_user)
    if is_owner(message.from_user.id):
        await message.answer("أهلًا بك في لوحة تحكم المالك 👑", reply_markup=owner_keyboard())
    else:
        await message.answer("أهلًا بك! أرسل رابط فيديو تملك حق تنزيله أو اختر تحميل من يوتيوب.", reply_markup=user_keyboard())

@dp.message(Command("admin"))
async def admin(message: Message):
    save_user(message.from_user)
    if not is_owner(message.from_user.id):
        return await message.answer("هذا الأمر للمالك فقط.")
    await message.answer("لوحة تحكم المالك 👑", reply_markup=owner_keyboard())

@dp.message(F.text == "🏠 القائمة الرئيسية")
async def home(message: Message, state: FSMContext):
    await state.clear()
    if is_owner(message.from_user.id):
        await message.answer("لوحة التحكم 👑", reply_markup=owner_keyboard())
    else:
        await message.answer("القائمة الرئيسية", reply_markup=user_keyboard())

@dp.message(F.text == "📊 الإحصائيات")
async def stats(message: Message):
    if not is_owner(message.from_user.id):
        return
    total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    today = db.execute("SELECT COUNT(*) FROM users WHERE date(joined_at)=date('now')").fetchone()[0]
    await message.answer(f"📊 <b>إحصائيات البوت</b>\n👥 إجمالي المستخدمين: <b>{total}</b>\n🆕 المنضمون اليوم (UTC): <b>{today}</b>")

@dp.message(F.text == "📢 إذاعة")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    await state.set_state(Flow.waiting_broadcast)
    await message.answer("أرسل الآن نص الإذاعة أو صورة/فيديو مع تعليق. للإلغاء أرسل /cancel")

@dp.message(F.text == "📨 تفعيل استقبال الرسائل")
async def inbox_on(message: Message):
    if is_owner(message.from_user.id):
        set_setting("inbox_enabled", "1")
        await message.answer("تم تفعيل استقبال الرسائل والروابط من المستخدمين ✅", reply_markup=owner_keyboard())

@dp.message(F.text == "🟢 إيقاف استقبال الرسائل")
async def inbox_off(message: Message):
    if is_owner(message.from_user.id):
        set_setting("inbox_enabled", "0")
        await message.answer("تم إيقاف استقبال الرسائل العامة ✅", reply_markup=owner_keyboard())

@dp.message(F.text == "💬 مراسلة المالك")
async def contact_owner(message: Message, state: FSMContext):
    if is_owner(message.from_user.id):
        return await message.answer("أنت المالك بالفعل.", reply_markup=owner_keyboard())
    await state.set_state(Flow.waiting_owner_message)
    await message.answer("اكتب رسالتك للمالك، وسيتم إرسالها إليه. أرسل /cancel للإلغاء.")

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("تم الإلغاء.", reply_markup=owner_keyboard() if is_owner(message.from_user.id) else user_keyboard())

@dp.message(Flow.waiting_owner_message)
async def relay_contact(message: Message, state: FSMContext):
    if message.from_user.id == OWNER_ID:
        return
    info = f"💬 <b>رسالة للمالك</b>\nمن: {message.from_user.full_name}\nID: <code>{message.from_user.id}</code>\nUsername: @{message.from_user.username or 'لا يوجد'}"
    try:
        await bot.send_message(OWNER_ID, info)
        await bot.copy_message(OWNER_ID, message.chat.id, message.message_id)
        await message.answer("وصلت رسالتك إلى المالك ✅")
    except Exception:
        await message.answer("تعذر إرسال الرسالة حاليًا. حاول لاحقًا.")
    await state.clear()

async def maybe_forward_to_owner(message: Message):
    if message.from_user.id == OWNER_ID or setting("inbox_enabled") != "1":
        return
    info = f"📥 <b>رسالة واردة (الاستقبال مفعّل)</b>\nمن: {message.from_user.full_name}\nID: <code>{message.from_user.id}</code>\nUsername: @{message.from_user.username or 'لا يوجد'}"
    try:
        await bot.send_message(OWNER_ID, info)
        await bot.copy_message(OWNER_ID, message.chat.id, message.message_id)
    except Exception:
        logging.exception("Could not forward user message")

@dp.message(Flow.waiting_broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    users = [r[0] for r in db.execute("SELECT user_id FROM users").fetchall()]
    sent = failed = 0
    await message.answer(f"بدأت الإذاعة إلى {len(users)} مستخدم...")
    for uid in users:
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    await state.clear()
    await message.answer(f"انتهت الإذاعة.\n✅ تم الإرسال: {sent}\n❌ تعذّر: {failed}", reply_markup=owner_keyboard())

@dp.message(F.text == "🎬 تحميل من يوتيوب")
async def ask_link(message: Message, state: FSMContext):
    save_user(message.from_user)
    await state.set_state(Flow.waiting_link)
    await message.answer("أرسل رابط يوتيوب لفيديو تملك حق تنزيله. اختر الجودة بعد ذلك. أرسل /cancel للإلغاء.")

@dp.callback_query(F.data.startswith("dl:"))
async def download_choice(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    url = data.get("url")
    if not url:
        await callback.answer("انتهت صلاحية الطلب. أرسل الرابط مجددًا.", show_alert=True)
        return
    choice = callback.data.split(":", 1)[1]
    await callback.answer("بدأ تجهيز الملف...")
    status = await callback.message.answer("⏳ جارٍ تجهيز الملف، قد يستغرق ذلك بعض الوقت.")
    try:
        with tempfile.TemporaryDirectory() as td:
            outtmpl = str(Path(td) / "%(title).80s.%(ext)s")
            if choice == "audio":
                opts = {"format": "bestaudio/best", "outtmpl": outtmpl, "noplaylist": True,
                        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]}
            else:
                height = int(choice)
                opts = {"format": f"best[height<={height}][ext=mp4]/best[height<={height}]/best", "outtmpl": outtmpl,
                        "noplaylist": True, "merge_output_format": "mp4"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            paths = [p for p in Path(td).iterdir() if p.is_file()]
            if not paths:
                raise RuntimeError("No output file")
            path = max(paths, key=lambda p: p.stat().st_size)
            if path.stat().st_size > 49 * 1024 * 1024:
                await status.edit_text("الملف أكبر من حد الإرسال المتاح لهذا البوت. جرّب جودة أقل.")
                return
            await bot.send_document(callback.from_user.id, FSInputFile(path))
            await status.edit_text("تم إرسال الملف ✅")
    except Exception:
        logging.exception("Download failed")
        await status.edit_text("تعذّر التحميل. قد يكون الرابط غير متاح أو أن الخدمة لا تدعم هذا الفيديو الآن.")
    finally:
        await state.clear()

@dp.message(Flow.waiting_link)
async def receive_link(message: Message, state: FSMContext):
    url = (message.text or "").strip()
    if not ("youtube.com/" in url or "youtu.be/" in url):
        return await message.answer("أرسل رابط يوتيوب صحيحًا.")
    await state.update_data(url=url)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="360p", callback_data="dl:360"), InlineKeyboardButton(text="480p", callback_data="dl:480")],
        [InlineKeyboardButton(text="720p HD", callback_data="dl:720"), InlineKeyboardButton(text="1080p", callback_data="dl:1080")],
        [InlineKeyboardButton(text="🎵 صوت MP3", callback_data="dl:audio")]
    ])
    await message.answer("اختر الجودة أو الصوت. الخيارات تعتمد على توفرها وحجم الملف:", reply_markup=keyboard)

@dp.message()
async def fallback(message: Message, state: FSMContext):
    save_user(message.from_user)
    if is_owner(message.from_user.id):
        return await message.answer("استخدم أزرار لوحة التحكم.", reply_markup=owner_keyboard())
    current = await state.get_state()
    if current:
        return
    await maybe_forward_to_owner(message)
    await message.answer("اختر من القائمة، أو أرسل رابط يوتيوب لفيديو تملك حق تنزيله.", reply_markup=user_keyboard())

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
