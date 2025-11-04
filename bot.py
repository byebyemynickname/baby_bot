import asyncio
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
import os
import pytz

# --- Загрузка токена ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Клавиатура ---
kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛌 Уснул"), KeyboardButton(text="🌞 Проснулся")],
        [KeyboardButton(text="Кормление 🍼"), KeyboardButton(text="Отчёт 📊")],
        [KeyboardButton(text="📅 История")]
    ],
    resize_keyboard=True
)

# --- Инициализация БД ---
async def init_db():
    async with aiosqlite.connect("baby_data.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS sleep (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            sleep_start TEXT,
            sleep_end TEXT,
            duration INTEGER,
            tz TEXT,
            date TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS feeding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            time TEXT,
            amount INTEGER,
            tz TEXT,
            date TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            timezone TEXT,
            last_sleep_start TEXT
        )
        """)
        await db.commit()

# --- Получить часовой пояс пользователя ---
async def get_user_timezone(user_id):
    async with aiosqlite.connect("baby_data.db") as db:
        async with db.execute("SELECT timezone FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "UTC"

# --- Команда /start ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👶 Привет! Я помогу отслеживать сон и кормления ребёнка.\n\n"
        "Перед началом установи свой часовой пояс командой:\n"
        "`/timezone Europe/Moscow`\n\n"
        "Потом используй кнопки ниже:",
        parse_mode="Markdown",
        reply_markup=kb
    )

# --- Команда /timezone ---
@dp.message(Command("timezone"))
async def set_timezone(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Укажи часовой пояс, например: `/timezone Europe/Moscow`", parse_mode="Markdown")
        return

    tz_name = parts[1].strip()
    if tz_name not in pytz.all_timezones:
        await message.answer("Такого часового пояса не существует 😅\nПосмотри список здесь: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
        return

    async with aiosqlite.connect("baby_data.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, timezone, last_sleep_start) VALUES (?, ?, NULL)",
            (message.from_user.id, tz_name)
        )
        await db.commit()

    await message.answer(f"✅ Часовой пояс установлен: *{tz_name}*", parse_mode="Markdown")

# --- 🛌 Уснул ---
@dp.message(lambda m: m.text == "🛌 Уснул")
async def sleep_start(message: types.Message):
    tz_name = await get_user_timezone(message.from_user.id)
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)

    async with aiosqlite.connect("baby_data.db") as db:
        await db.execute(
            "UPDATE users SET last_sleep_start = ? WHERE user_id = ?",
            (now.isoformat(), message.from_user.id)
        )
        await db.commit()

    await message.answer(f"🛌 Заснул в {now.strftime('%H:%M')} ({tz_name})")

# --- 🌞 Проснулся ---
@dp.message(lambda m: m.text == "🌞 Проснулся")
async def sleep_end(message: types.Message):
    tz_name = await get_user_timezone(message.from_user.id)
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    date_today = now.date().isoformat()

    async with aiosqlite.connect("baby_data.db") as db:
        async with db.execute("SELECT last_sleep_start FROM users WHERE user_id = ?", (message.from_user.id,)) as cur:
            row = await cur.fetchone()

        if not row or not row[0]:
            await message.answer("⚠️ Не найдено время, когда ребёнок уснул.\nСначала нажми “🛌 Уснул”.")
            return

        start_time = datetime.fromisoformat(row[0])
        duration = int((now - start_time).total_seconds() / 60)

        await db.execute(
            "INSERT INTO sleep (user_id, sleep_start, sleep_end, duration, tz, date) VALUES (?, ?, ?, ?, ?, ?)",
            (message.from_user.id, start_time.strftime("%H:%M"), now.strftime("%H:%M"), duration, tz_name, date_today)
        )
        await db.execute("UPDATE users SET last_sleep_start = NULL WHERE user_id = ?", (message.from_user.id,))
        await db.commit()

    hours, minutes = divmod(duration, 60)
    await message.answer(f"🌞 Проснулся в {now.strftime('%H:%M')} ({tz_name})\n🕐 Сон длился {hours} ч {minutes} мин")

# --- Кормление ---
@dp.message(lambda m: m.text == "Кормление 🍼")
async def feed_prompt(message: types.Message):
    await message.answer("Введи объём молока в мл, например: `120`")

@dp.message(lambda m: m.text.isdigit())
async def feed_record(message: types.Message):
    amount = int(message.text)
    tz_name = await get_user_timezone(message.from_user.id)
    tz = pytz.timezone(tz_name)
    now_local = datetime.now(tz)
    date_today = now_local.date().isoformat()

    async with aiosqlite.connect("baby_data.db") as db:
        await db.execute(
            "INSERT INTO feeding (user_id, time, amount, tz, date) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, now_local.strftime("%H:%M"), amount, tz_name, date_today)
        )
        await db.commit()

    await message.answer(f"Записано 🍼 {amount} мл в {now_local.strftime('%H:%M')} ({tz_name})")

# --- Отчёт за сегодня ---
@dp.message(lambda m: m.text == "Отчёт 📊")
async def report_today(message: types.Message):
    tz_name = await get_user_timezone(message.from_user.id)
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date().isoformat()

    async with aiosqlite.connect("baby_data.db") as db:
        # Получаем все сны
        async with db.execute("SELECT sleep_start, sleep_end, duration FROM sleep WHERE user_id = ? AND date = ?", (message.from_user.id, today)) as cur:
            sleeps = await cur.fetchall()

        # Получаем все кормления
        async with db.execute("SELECT time, amount FROM feeding WHERE user_id = ? AND date = ?", (message.from_user.id, today)) as cur:
            feeds = await cur.fetchall()

    # Формируем отчёт
    report = f"📅 *Отчёт за {today}* ({tz_name})\n\n"

    total_sleep = sum(s[2] for s in sleeps) if sleeps else 0
    total_feed = sum(f[1] for f in feeds) if feeds else 0

    # Сны
    if sleeps:
        report += "🛌 *Сон:*\n"
        for s in sleeps:
            h, m = divmod(s[2], 60)
            report += f"• {s[0]} → {s[1]} ({h}ч {m}м)\n"
    else:
        report += "🛌 Сон: нет записей\n"

    report += "\n"

    # Кормления
    if feeds:
        report += "🍼 *Кормления:*\n"
        for f in feeds:
            report += f"• {f[0]} — {f[1]} мл\n"
    else:
        report += "🍼 Кормлений нет\n"

    # Итоги
    h, m = divmod(total_sleep, 60)
    report += f"\n📊 *Итого за день:*\n🕐 Сон: {h} ч {m} мин\n🍼 Молока: {total_feed} мл"

    await message.answer(report, parse_mode="Markdown")

# --- История ---
@dp.message(lambda m: m.text == "📅 История")
async def history(message: types.Message):
    tz_name = await get_user_timezone(message.from_user.id)
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date()
    start_date = today - timedelta(days=2)

    reply = f"📅 *История за последние 3 дня* ({tz_name})\n\n"

    async with aiosqlite.connect("baby_data.db") as db:
        for offset in range(3):
            day = (start_date + timedelta(days=offset)).isoformat()
            reply += f"📆 {day}\n"

            async with db.execute("SELECT sleep_start, sleep_end, duration FROM sleep WHERE user_id = ? AND date = ?", (message.from_user.id, day)) as cur:
                sleeps = await cur.fetchall()

            async with db.execute("SELECT time, amount FROM feeding WHERE user_id = ? AND date = ?", (message.from_user.id, day)) as cur:
                feeds = await cur.fetchall()

            if not sleeps and not feeds:
                reply += "— Нет записей\n\n"
                continue

            if sleeps:
                reply += "💤 Сон:\n"
                for s in sleeps:
                    h, m = divmod(s[2], 60)
                    reply += f"  • {s[0]} → {s[1]} ({h}ч {m}м)\n"

            if feeds:
                reply += "🍼 Кормления:\n"
                for f in feeds:
                    reply += f"  • {f[0]} — {f[1]} мл\n"

            reply += "\n"

    await message.answer(reply, parse_mode="Markdown")

# --- Запуск ---
async def main():
    await init_db()
    print("Бот запущен (с улучшенным отчётом)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
