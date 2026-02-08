import asyncio
import uuid
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


# =====================
# НАСТРОЙКИ
# =====================

BOT_TOKEN = "7987974434:AAErdwEztIpkUH4MPVuWKtLytM-aeqmW0qs"
ADMIN_ID = 7388744796  # твой Telegram ID
CHANNEL_ID = "@YAKMODS"  # канал (бот должен быть админом)

START_IMAGE = "https://images-ext-1.discordapp.net/external/VYxjKWsWfuy15MhjbNSdZTAnAw7ncsq0QzRpea-7fnA/https/i.pinimg.com/736x/e2/6f/ad/e26fadfad4179906f627b7cbc253f559.jpg?format=webp&width=662&height=617"

# =====================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
posts = {}


# =====================
# FSM
# =====================

class AddPost(StatesGroup):
    photo = State()
    title = State()
    file = State()


# =====================
# КНОПКИ
# =====================

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить пост", callback_data="add_post")]
    ])


def confirm_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="confirm_post")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_post")]
    ])


# =====================
# Проверка подписки
# =====================

async def check_sub(user_id):
    member = await bot.get_chat_member(CHANNEL_ID, user_id)
    return member.status in ["member", "creator", "administrator"]


# =====================
# START
# =====================

@dp.message(F.text == "/start")
async def start(message: Message):
    text = (
        "🔥 <b>YAKMODS</b>\n\n"
        "<a href='https://discord.gg/yakfamq'>YAKFAMQ</a>\n"
        "<a href='https://t.me/YAKMODS'>YAKMODS</a>\n\n"
        "Лучшие моды в одном месте."
    )

    if message.from_user.id == ADMIN_ID:
        await message.answer_photo(
            START_IMAGE,
            caption=text,
            reply_markup=admin_menu()
        )
    else:
        await message.answer_photo(
            START_IMAGE,
            caption=text
        )


# =====================
# АДМИН ДОБАВЛЕНИЕ ПОСТА
# =====================

@dp.callback_query(F.data == "add_post")
async def add_post(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddPost.photo)
    await call.message.answer("📸 Отправь фото поста")
    await call.answer()


@dp.message(AddPost.photo, F.photo)
async def get_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(AddPost.title)
    await message.answer("📝 Введи название")


@dp.message(AddPost.title)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddPost.file)
    await message.answer("📦 Отправь файл или ссылку")


@dp.message(AddPost.file)
async def get_file(message: Message, state: FSMContext):
    data = await state.get_data()

    if message.document:
        data["file"] = message.document.file_id
    else:
        data["link"] = message.text

    post_id = str(uuid.uuid4())
    data["post_id"] = post_id

    posts[post_id] = data

    preview_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⬇️ Скачать",
            url=f"https://t.me/{(await bot.get_me()).username}?start=download_{post_id}"
        )]
    ])

    await message.answer_photo(
        data["photo"],
        caption=f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку ниже",
        reply_markup=preview_kb
    )

    await message.answer("Подтвердите публикацию:", reply_markup=confirm_menu())


@dp.callback_query(F.data == "confirm_post")
async def publish(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    post_id = data["post_id"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⬇️ Скачать",
            url=f"https://t.me/{(await bot.get_me()).username}?start=download_{post_id}"
        )]
    ])

    await bot.send_photo(
        CHANNEL_ID,
        photo=data["photo"],
        caption=f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку ниже",
        reply_markup=kb
    )

    await call.message.answer("🚀 Пост опубликован!", reply_markup=admin_menu())
    await state.clear()
    await call.answer()


@dp.callback_query(F.data == "cancel_post")
async def cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Отменено", reply_markup=admin_menu())
    await call.answer()


# =====================
# СКАЧИВАНИЕ
# =====================

@dp.message(F.text.startswith("/start download_"))
async def download(message: Message):
    post_id = message.text.split("_")[1]
    post = posts.get(post_id)

    if not post:
        return await message.answer("❌ Файл не найден")

    if not await check_sub(message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{CHANNEL_ID[1:]}")],
            [InlineKeyboardButton(text="✅ Проверить", callback_data=f"check_{post_id}")]
        ])
        return await message.answer("Подпишитесь на канал", reply_markup=kb)

    await send_file(message, post)


@dp.callback_query(F.data.startswith("check_"))
async def recheck(call: CallbackQuery):
    post_id = call.data.split("_")[1]
    post = posts.get(post_id)

    if await check_sub(call.from_user.id):
        await send_file(call.message, post)
    else:
        await call.answer("❌ Вы не подписаны", show_alert=True)


async def send_file(message, post):
    if "file" in post:
        await message.answer_document(post["file"])
    else:
        await message.answer(f"🔗 {post['link']}")


# =====================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
