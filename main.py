import logging
import secrets
import re
from datetime import datetime
import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from motor.motor_asyncio import AsyncIOMotorClient

from langs import LANGS, LANG_NAMES

# --- New imports for image and config feature ---
from config import GENERATE_IMAGE_ON_ANONYMOUS, ALLOW_ANONYMOUS_REPLY
from image_utils import generate_message_image
import os

API_TOKEN = "8032679205:AAHFMO9t-T7Lavbbf_noiePQoniDSHzSuVA"
MONGODB_URL = "mongodb+srv://itxcriminal:qureshihashmI1@cluster0.jyqy9.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "askout"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

client = AsyncIOMotorClient(MONGODB_URL)
db = client[DB_NAME]

def generate_short_username():
    # Changed prefix from "anon" to "ask"
    return f"ask{secrets.randbelow(100000):05d}"

def today_str():
    return datetime.utcnow().strftime("%Y-%m-%d")

async def get_or_create_user(user_id):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        while True:
            short_username = generate_short_username()
            if not await db.users.find_one({"short_username": short_username}):
                break
        link_id = secrets.token_urlsafe(8)
        await db.users.insert_one({
            "user_id": user_id,
            "link_id": link_id,
            "short_username": short_username,
            "messages_received": 0,
            "link_clicks": 0,
            "messages_received_daily": {},
            "link_clicks_daily": {},
            "language": "en"
        })
        return short_username
    return user.get("short_username") or user.get("link_id")

async def get_user_by_link_id(link_id):
    return await db.users.find_one({"$or": [{"short_username": link_id}, {"link_id": link_id}]})

def extract_link_id(start_param):
    return start_param if start_param else None

def get_share_keyboard(link, lang):
    btn = InlineKeyboardButton(
        text=LANGS[lang]['share_btn'],
        switch_inline_query=f"Ask me anything! It's anonymous: {link}"
    )
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])

async def get_user_lang(user_id):
    user = await db.users.find_one({"user_id": user_id})
    return user.get("language", "en") if user else "en"

def get_lang_markup():
    buttons = [
        [InlineKeyboardButton(text=LANG_NAMES[code], callback_data=f"lang_{code}")]
        for code in LANGS
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- Helper to send thumbs up reaction using the raw Bot API (Bot API 7.0+ only) ---
async def set_reaction(bot, chat_id, message_id, emoji):
    token = bot.token
    url = f"https://api.telegram.org/bot{token}/setMessageReaction"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [
            {
                "type": "emoji",
                "emoji": emoji
            }
        ]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return True
                else:
                    logging.warning(f"Failed to set reaction: {await resp.text()}")
    except Exception as e:
        logging.warning(f"Failed to set reaction: {e}")
    return False

@router.message(Command("language"))
@router.message(Command("setlang"))
async def set_language_command(message: Message):
    await message.answer(LANGS["en"]["choose_lang"], reply_markup=get_lang_markup())

@router.callback_query(lambda c: c.data and c.data.startswith("lang_"))
async def language_selected(callback_query, state: FSMContext):
    lang_code = callback_query.data.split("_", 1)[1]
    data = await state.get_data()
    start_param = data.get("start_param")

    # Create user if not exists
    user = await db.users.find_one({"user_id": callback_query.from_user.id})
    if not user:
        while True:
            short_username = generate_short_username()
            if not await db.users.find_one({"short_username": short_username}):
                break
        link_id = secrets.token_urlsafe(8)
        await db.users.insert_one({
            "user_id": callback_query.from_user.id,
            "link_id": link_id,
            "short_username": short_username,
            "messages_received": 0,
            "link_clicks": 0,
            "messages_received_daily": {},
            "link_clicks_daily": {},
            "language": lang_code
        })
    else:
        await db.users.update_one(
            {"user_id": callback_query.from_user.id},
            {"$set": {"language": lang_code}},
        )
        short_username = user.get("short_username") or user.get("link_id")

    await callback_query.answer()

    if start_param:
        target_user = await get_user_by_link_id(start_param)
        if target_user:
            await state.update_data(target_link_id=start_param)
            await callback_query.message.edit_text(
                LANGS[lang_code]["send_anonymous"]
            )
        else:
            await callback_query.message.edit_text(
                LANGS[lang_code]["invalid_link"]
            )
        await state.update_data(start_param=None)
        return

    # If no start_param, show welcome and user own link
    bot_username = (await bot.me()).username
    user_short_username = await get_or_create_user(callback_query.from_user.id)
    link = f"https://t.me/{bot_username}?start={user_short_username}"
    await callback_query.message.edit_text(
        LANGS[lang_code]["welcome"].format(link=link),
        reply_markup=get_share_keyboard(link, lang_code)
    )
    await state.clear()

@router.message(CommandStart(deep_link=True))
async def start_with_param(message: Message, command: CommandStart, state: FSMContext):
    link_id = extract_link_id(command.args)
    user = await db.users.find_one({"user_id": message.from_user.id})
    if not user:
        await state.update_data(start_param=link_id)
        await message.answer(LANGS["en"]["choose_lang"], reply_markup=get_lang_markup())
        return
    lang = await get_user_lang(message.from_user.id)
    if link_id:
        user = await get_user_by_link_id(link_id)
        if not user:
            await message.answer(LANGS[lang]["invalid_link"])
            return
        if user["user_id"] != message.from_user.id:
            today = today_str()
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {
                    "$inc": {"link_clicks": 1},
                    "$set": {f"link_clicks_daily.{today}": (user.get("link_clicks_daily", {}).get(today, 0) + 1)}
                }
            )
        await state.update_data(target_link_id=link_id)
        await message.answer(LANGS[lang]["send_anonymous"])
    else:
        user_short_username = await get_or_create_user(message.from_user.id)
        bot_username = (await bot.me()).username
        link = f"https://t.me/{bot_username}?start={user_short_username}"
        await message.answer(
            LANGS[lang]["welcome"].format(link=link),
            reply_markup=get_share_keyboard(link, lang)
        )

@router.message(CommandStart(deep_link=False))
async def start_no_param(message: Message, state: FSMContext):
    user = await db.users.find_one({"user_id": message.from_user.id})
    if not user:
        await state.clear()
        await message.answer(LANGS["en"]["choose_lang"], reply_markup=get_lang_markup())
        return
    lang = await get_user_lang(message.from_user.id)
    user_short_username = await get_or_create_user(message.from_user.id)
    bot_username = (await bot.me()).username
    link = f"https://t.me/{bot_username}?start={user_short_username}"
    await message.answer(
        LANGS[lang]["welcome"].format(link=link),
        reply_markup=get_share_keyboard(link, lang)
    )
    await state.clear()

@router.message(F.reply_to_message)
async def handle_reply(message: Message):
    if not ALLOW_ANONYMOUS_REPLY:
        return
    replied = message.reply_to_message
    if replied:
        record = await db.anonymous_links.find_one({
            "reply_message_id": replied.message_id,
            "to_user_id": message.from_user.id
        })
        if record:
            orig_sender_id = record["from_user_id"]
            lang = await get_user_lang(orig_sender_id)
            sent = await bot.send_message(
                orig_sender_id,
                f"📩 <b>You received a reply to your anonymous message:</b>\n\n{message.text}"
            )
            # Insert mapping for the reply message, so the thread can continue
            await db.anonymous_links.insert_one({
                "reply_message_id": sent.message_id,
                "to_user_id": orig_sender_id,
                "from_user_id": message.from_user.id
            })
            await set_reaction(bot, message.chat.id, message.message_id, "👍")
            return

@router.message(Command("setusername"))
async def set_custom_username(message: Message):
    lang = await get_user_lang(message.from_user.id)
    args = message.text.strip().split()
    if len(args) != 2:
        await message.answer(LANGS[lang]["set_username_usage"])
        return
    new_username = args[1].lower()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", new_username):
        await message.answer(LANGS[lang]["invalid_username"])
        return
    existing = await db.users.find_one({"short_username": new_username})
    if existing:
        if existing["user_id"] == message.from_user.id:
            await message.answer(LANGS[lang]["already_username"])
        else:
            await message.answer(LANGS[lang]["username_taken"])
        return
    await db.users.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"short_username": new_username}},
        upsert=True
    )
    bot_username = (await bot.me()).username
    link = f"https://t.me/{bot_username}?start={new_username}"
    await message.answer(
        LANGS[lang]["username_set"].format(username=new_username, link=link),
        reply_markup=get_share_keyboard(link, lang)
    )

@router.message(Command("stats"))
async def stats_command(message: Message):
    lang = await get_user_lang(message.from_user.id)
    user = await db.users.find_one({"user_id": message.from_user.id})
    if not user:
        await message.answer(LANGS[lang]["not_registered"])
        return
    today = today_str()
    messages_received = user.get("messages_received", 0)
    link_clicks = user.get("link_clicks", 0)
    messages_received_daily = user.get("messages_received_daily", {})
    link_clicks_daily = user.get("link_clicks_daily", {})
    messages_today = messages_received_daily.get(today, 0)
    clicks_today = link_clicks_daily.get(today, 0)
    await message.answer(
        LANGS[lang]["stats"].format(
            messages_received=messages_received,
            messages_today=messages_today,
            link_clicks=link_clicks,
            clicks_today=clicks_today
        )
    )

@router.message(F.text)
async def handle_anonymous_message(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    target_link_id = data.get("target_link_id")
    if target_link_id:
        user = await get_user_by_link_id(target_link_id)
        if not user:
            await message.answer(LANGS[lang]["user_not_found"])
            return

        sent_msg = None

        # If image generation is ON, send only image with caption
        if GENERATE_IMAGE_ON_ANONYMOUS:
            image_path = generate_message_image(message.text)
            caption = LANGS[user.get('language', 'en')]['anonymous_received']
            if image_path:
                try:
                    sent_msg = await bot.send_photo(
                        user["user_id"],
                        photo=FSInputFile(image_path),
                        caption=caption
                    )
                finally:
                    if os.path.exists(image_path):
                        os.remove(image_path)
            else:
                sent_msg = await bot.send_message(
                    user["user_id"],
                    caption
                )
        else:
            sent_msg = await bot.send_message(
                user["user_id"],
                LANGS[user.get('language', 'en')]['anonymous_received'].format(message=message.text)
            )

        # Store mapping for reply (on image or fallback text message)
        if sent_msg:
            await db.anonymous_links.insert_one({
                "reply_message_id": sent_msg.message_id,
                "to_user_id": user["user_id"],
                "from_user_id": message.from_user.id
            })

        today = today_str()
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {
                "$inc": {"messages_received": 1},
                "$set": {f"messages_received_daily.{today}": (user.get("messages_received_daily", {}).get(today, 0) + 1)}
            }
        )
        await message.answer(LANGS[lang]["anonymous_sent"])
        await state.clear()
    else:
        user_short_username = await get_or_create_user(message.from_user.id)
        bot_username = (await bot.me()).username
        link = f"https://t.me/{bot_username}?start={user_short_username}"
        await message.answer(
            LANGS[lang]["welcome"].format(link=link),
            reply_markup=get_share_keyboard(link, lang)
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))
