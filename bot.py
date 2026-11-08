import logging
import sys
import asyncio
import datetime
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID", 1))
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
    await bot.send_message(
    chat_id=event.chat.id, 
    text=welcome_text, 
    parse_mode="HTML",
    message_thread_id=getattr(event, "message_thread_id", None)
    )

@dp.message(F.chat.id == CHT_ID if isinstance(CHAT_ID, int) else F.chat.id == int(CHAT_ID))
async def check_presentation(message: types.Message):
    if message.message_thread_id != TOPIC_ID:
        return
        
    if message.text:
        text_lower = message.text.lower()
        keywords = ["привет", "всем", "меня", "зовут", "имя", "танцую", "хожу", "линди", "блюз"]
        
        if any(kw in text_lower for kw in keywords):
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("DELETE FROM pending_users WHERE user_id = ?", (message.from_user.id,))
                await db.commit()

#если молчит-отправка в должники через minutes=n 
async def daily_check():
    logging.info("Запуск проверки должников...")
    async with aiosqlite.connect(DB_NAME) as db:
        yesterday = (datetime.datetime.now() - datetime.timedelta(minutes=1400)).isoformat()
        async with db.execute(
            "SELECT user_id, username, full_name FROM pending_users WHERE joined_at <= ?",
            (yesterday,)
        ) as cursor:
            users_to_remind = await cursor.fetchall()

    logging.info(f"Найдено должников для напоминания: {len(users_to_remind)}")
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
    await bot.send_message(
    chat_id=CHAT_ID, 
    text=remind_text, 
    parse_mode="HTML",
    message_thread_id=TOPIC_ID
)


async def log_current_pending_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, username, full_name, joined_at FROM pending_users") as cursor:
            users = await cursor.fetchall()
            
    total_users = len(users)
    
    if total_users == 0:
        logging.info("--- База пуста: всего пользователей в очереди: 0 ---")
        return

    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(days=1)
    
    debtors_count = 0
    fresh_count = 0
    
    for u_id, username, full_name, joined_at_str in users:
        joined_at = datetime.datetime.fromisoformat(joined_at_str)
        if joined_at <= yesterday:
            debtors_count += 1
            status = "ДОЛЖНИК (прошло > 24ч)"
        else:
            fresh_count += 1
            time_left = datetime.timedelta(days=1) - (now - joined_at)
            hours_left = round(time_left.total_seconds() / 3600, 1)
            status = f"Новый (осталось ~{hours_left} ч)"

        logging.info(f"  > ID: {u_id} | Name: {full_name} (@{username}) | Встал в очередь: {joined_at_str} | Статус: {status}")

    job = scheduler.get_job('daily_check_job')
    if job and job.next_run_time:
        next_run = job.next_run_time.replace(tzinfo=None)
        time_to_next = next_run - now
        hours_to_next = round(max(0, time_to_next.total_seconds()) / 3600, 1)
        next_run_str = f"~{hours_to_next} ч"
    else:
        next_run_str = "не запланировано"

    logging.info(f"--- [СВОДКА] Всего в базе: {total_users} | Должников (>24ч): {debtors_count} | Ожидают (<24ч): {fresh_count} | Следующая рассылка через: {next_run_str} ---")
    



async def main():
    await init_db()
    await start_web_server()
    #напоминание должникам каждые minutes=n после деплоя
    scheduler.add_job(daily_check, "interval", minutes=720, id="daily_check_job")
    #логи на чтение базы
    scheduler.add_job(log_current_pending_users, "interval", minutes=10)
    scheduler.start()    
    await log_current_pending_users()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
