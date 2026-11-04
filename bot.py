import asyncio
import datetime
import logging
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DB_NAME = "users.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TEXT
            )
        """)
        await db.commit()

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: types.ChatMemberUpdated):
    user = event.new_chat_member.user
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_users (user_id, username, full_name, joined_at) VALUES (?, ?, ?, ?)",
            (user.id, user.username, user.full_name, datetime.datetime.now().isoformat())
        )
        await db.commit()
    
    mention = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"
    welcome_text = (
        f"📌 Добро пожаловать в чат! \n"
        f"⚠️ {mention}, НАПИШИ СВОЕ РЫБЬЕ ИМЯ/ФИО + направление ⚠️\n\n"
        f"Оставаясь здесь, ты принимаешь Правила чата: https://t.me/c/1897775186/18\n"
        f"________________________"
    )
    await bot.send_message(chat_id=event.chat.id, text=welcome_text, parse_mode="HTML")

@dp.message(F.chat.id == CHAT_ID)
async def check_presentation(message: types.Message):
    if message.text:
        text_lower = message.text.lower()
        keywords = ["привет", "всем", "меня", "зовут", "имя", "танцую", "хожу", "линди", "блюз" ]
        
        if any(kw in text_lower for kw in keywords):
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("DELETE FROM pending_users WHERE user_id = ?", (message.from_user.id,))
                await db.commit()

#если молчит-отправка в должники через minutes=n 
async def daily_check():
    async with aiosqlite.connect(DB_NAME) as db:
        yesterday = (datetime.datetime.now() - datetime.timedelta(minutes=1440)).isoformat()
        async with db.execute(
            "SELECT user_id, username, full_name FROM pending_users WHERE joined_at <= ?",
            (yesterday,)
        ) as cursor:
            users_to_remind = await cursor.fetchall()

    if not users_to_remind:
        return

    tags = []
    for user_id, username, full_name in users_to_remind:
        if username:
            tags.append(f"@{username}")
        else:
            tags.append(f"<a href='tg://user?id={user_id}'>{full_name}</a>")

    remind_text = (
        f"Напоминание!\n"
        f"{', '.join(tags)}, пожалуйста, представься!\n"
        f"⚠️НАПИШИ СВОЕ РЫБЬЕ ИМЯ/ФИО + направление ⚠️\n"
        f"________________________"
    )
    await bot.send_message(chat_id=CHAT_ID, text=remind_text, parse_mode="HTML")

#напоминание должникам каждые minutes=n после деплоя
async def main():
    await init_db()
    await start_web_server()
    scheduler.add_job(daily_check, "interval", minutes=1440)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
