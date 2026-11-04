import asyncio
import datetime
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from apscheduler.schedulers.asyncio import AsyncIOScheduler

BOT_TOKEN = "9139034146:AAGLJZxPRFCrn0LJjc__0kzKczD8geQ4ih4"
CHAT_ID = -1001234567890  # ID вашего чата
DB_NAME = "users.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                joined_at TIMESTAMP
            )
        """)
        await db.commit()

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: types.ChatMemberUpdated):
    user = event.new_chat_member.user
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_users (user_id, username, joined_at) VALUES (?, ?, ?)",
            (user.id, user.username, datetime.datetime.now())
        )
        await db.commit()
    
    welcome_text = (
        f"Привет, <a href='tg://user?id={user.id}'>{user.full_name}</a>!\n"
        "Добро пожаловать в чат. Пожалуйста, представься (расскажи немного о себе)."
    )
    await bot.send_message(chat_id=event.chat.id, text=welcome_text, parse_mode="HTML")

@dp.message(F.chat.id == CHAT_ID)
async def check_presentation(message: types.Message):
    if message.text and any(tag in message.text.lower() for tag in ["#знакомство", "#визитка", "меня зовут"]):    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM pending_users WHERE user_id = ?", (message.from_user.id,))
        await db.commit()

async def daily_check():
    async with aiosqlite.connect(DB_NAME) as db:
        yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        async with db.execute(
            "SELECT user_id, username FROM pending_users WHERE joined_at <= ?",
            (yesterday,)
        ) as cursor:
            users_to_remind = await cursor.fetchall()

    if not users_to_remind:
        return

    tags = []
    for user_id, username in users_to_remind:
        if username:
            tags.append(f"@{username}")
        else:
            tags.append(f"<a href='tg://user?id={user_id}'>пользователь</a>")

    remind_text = (
        "Напоминание!\n" + ", ".join(tags) +
        "\nВы еще не представились. Пожалуйста, напишите пару слов о себе!"
    )
    await bot.send_message(chat_id=CHAT_ID, text=remind_text, parse_mode="HTML")

async def main():
    await init_db()
    scheduler.add_job(daily_check, "cron", hour=12, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
