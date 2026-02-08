import asyncio
import uuid
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

# =====================
# НАСТРОЙКИ
# =====================

BOT_TOKEN = "7987974434:AAErdwEztIpkUH4MPVuWKtLytM-aeqmW0qs"
ADMIN_ID = 7388744796
CHANNEL_ID = "@testyakbott"

START_IMAGE = "https://images-ext-1.discordapp.net/external/VYxjKWsWfuy15MhjbNSdZTAnAw7ncsq0QzRpea-7fnA/https/i.pinimg.com/736x/e2/6f/ad/e26fadfad4179906f627b7cbc253f559.jpg?format=webp&width=662&height=617"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =====================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# Хранилище постов (в продакшене используйте БД)
posts = {}


# =====================
# FSM States
# =====================

class AddPost(StatesGroup):
    photo = State()
    title = State()
    file = State()


# =====================
# КНОПКИ
# =====================

def admin_menu():
    """Меню администратора"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить пост", callback_data="add_post")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])


def confirm_menu():
    """Меню подтверждения публикации"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="confirm_post")],
        [InlineKeyboardButton(text="🔄 Изменить", callback_data="edit_post")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_post")]
    ])


def subscribe_keyboard(post_id):
    """Клавиатура проверки подписки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{CHANNEL_ID[1:]}")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=f"check_{post_id}")]
    ])


def download_keyboard(bot_username, post_id):
    """Кнопка скачивания"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⬇️ Скачать",
            url=f"https://t.me/{bot_username}?start=download_{post_id}"
        )]
    ])


# =====================
# Проверка подписки
# =====================

async def check_subscription(user_id: int) -> bool:
    """Проверяет подписку пользователя на канал"""
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "creator", "administrator"]
    except TelegramBadRequest as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False


# =====================
# Проверка прав администратора
# =====================

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id == ADMIN_ID


# =====================
# START
# =====================

@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обработчик команды /start"""
    
    # Обработка deep link для скачивания
    if len(message.text.split()) > 1:
        args = message.text.split()[1]
        if args.startswith("download_"):
            return await handle_download(message, args)
    
    text = (
        "🔥 <b>YAKMODS</b>\n\n"
        "Добро пожаловать в лучший источник модов!\n\n"
        "🔗 <a href='https://discord.gg/yakfamq'>Discord: YAKFAMQ</a>\n"
        "📢 <a href='https://t.me/YAKMODS'>Telegram: YAKMODS</a>\n\n"
        "💎 Лучшие моды в одном месте"
    )

    try:
        if is_admin(message.from_user.id):
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
    except Exception as e:
        logger.error(f"Ошибка отправки стартового сообщения: {e}")
        await message.answer(text)


# =====================
# АДМИН: Добавление поста
# =====================

@dp.callback_query(F.data == "add_post")
async def add_post_start(call: CallbackQuery, state: FSMContext):
    """Начало процесса добавления поста"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    await state.set_state(AddPost.photo)
    await call.message.answer("📸 Отправьте фото для поста")
    await call.answer()


@dp.message(AddPost.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """Обработка фото поста"""
    photo_id = message.photo[-1].file_id
    await state.update_data(photo=photo_id)
    await state.set_state(AddPost.title)
    await message.answer("📝 Введите название поста:")


@dp.message(AddPost.photo)
async def invalid_photo(message: Message):
    """Обработка неверного формата"""
    await message.answer("❌ Пожалуйста, отправьте фото!")


@dp.message(AddPost.title)
async def process_title(message: Message, state: FSMContext):
    """Обработка названия поста"""
    if len(message.text) > 200:
        return await message.answer("❌ Название слишком длинное (макс. 200 символов)")
    
    await state.update_data(title=message.text)
    await state.set_state(AddPost.file)
    await message.answer(
        "📦 Отправьте файл (документ) или ссылку для скачивания:\n\n"
        "💡 Совет: Для ссылок используйте прямые ссылки на файлы"
    )


@dp.message(AddPost.file)
async def process_file(message: Message, state: FSMContext):
    """Обработка файла или ссылки"""
    data = await state.get_data()
    post_id = str(uuid.uuid4())
    
    # Сохраняем файл или ссылку
    if message.document:
        data["file"] = message.document.file_id
        data["file_name"] = message.document.file_name
        data["file_size"] = message.document.file_size
    elif message.text:
        if not message.text.startswith(("http://", "https://")):
            return await message.answer("❌ Ссылка должна начинаться с http:// или https://")
        data["link"] = message.text
    else:
        return await message.answer("❌ Отправьте документ или текстовую ссылку!")
    
    data["post_id"] = post_id
    await state.update_data(**data)
    
    # Показываем превью
    bot_username = (await bot.get_me()).username
    preview_kb = download_keyboard(bot_username, post_id)
    
    caption = f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"
    
    if "file" in data:
        file_size_mb = data['file_size'] / (1024 * 1024)
        caption += f"\n\n📦 Файл: {data['file_name']}\n💾 Размер: {file_size_mb:.2f} МБ"
    
    await message.answer_photo(
        data["photo"],
        caption=caption,
        reply_markup=preview_kb
    )
    
    await message.answer(
        "📋 <b>Предпросмотр поста</b>\n\n"
        "Проверьте все данные и выберите действие:",
        reply_markup=confirm_menu()
    )
    
    # Временно сохраняем пост
    posts[post_id] = data


@dp.callback_query(F.data == "confirm_post")
async def confirm_publication(call: CallbackQuery, state: FSMContext):
    """Публикация поста в канал"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    data = await state.get_data()
    post_id = data["post_id"]
    
    bot_username = (await bot.get_me()).username
    kb = download_keyboard(bot_username, post_id)
    
    caption = f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"
    
    try:
        await bot.send_photo(
            CHANNEL_ID,
            photo=data["photo"],
            caption=caption,
            reply_markup=kb
        )
        
        await call.message.answer(
            "✅ <b>Пост успешно опубликован!</b>\n\n"
            f"📊 ID поста: <code>{post_id}</code>",
            reply_markup=admin_menu()
        )
        
        logger.info(f"Пост {post_id} опубликован администратором {call.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка публикации поста: {e}")
        await call.message.answer(
            "❌ Ошибка публикации! Проверьте:\n"
            "• Бот является админом канала\n"
            "• Канал существует\n"
            "• Правильно указан ID канала",
            reply_markup=admin_menu()
        )
    
    await state.clear()
    await call.answer()


@dp.callback_query(F.data == "edit_post")
async def edit_post(call: CallbackQuery, state: FSMContext):
    """Редактирование поста"""
    data = await state.get_data()
    post_id = data.get("post_id")
    
    if post_id and post_id in posts:
        del posts[post_id]
    
    await state.clear()
    await call.message.answer("🔄 Начните создание поста заново:", reply_markup=admin_menu())
    await call.answer()


@dp.callback_query(F.data == "cancel_post")
async def cancel_post(call: CallbackQuery, state: FSMContext):
    """Отмена создания поста"""
    data = await state.get_data()
    post_id = data.get("post_id")
    
    if post_id and post_id in posts:
        del posts[post_id]
    
    await state.clear()
    await call.message.answer("❌ Создание поста отменено", reply_markup=admin_menu())
    await call.answer()


# =====================
# СТАТИСТИКА
# =====================

@dp.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery):
    """Показывает статистику бота"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    stats_text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"📝 Всего постов: {len(posts)}\n"
        f"🤖 Версия: 2.0\n"
        f"⚡️ Статус: Активен"
    )
    
    await call.message.answer(stats_text, reply_markup=admin_menu())
    await call.answer()


# =====================
# СКАЧИВАНИЕ
# =====================

async def handle_download(message: Message, args: str):
    """Обработка запроса на скачивание"""
    post_id = args.replace("download_", "")
    post = posts.get(post_id)
    
    if not post:
        return await message.answer(
            "❌ <b>Файл не найден</b>\n\n"
            "Возможно, пост был удален или ссылка устарела."
        )
    
    # Проверка подписки
    if not await check_subscription(message.from_user.id):
        return await message.answer(
            "⚠️ <b>Требуется подписка</b>\n\n"
            "Для скачивания файлов необходимо подписаться на наш канал:",
            reply_markup=subscribe_keyboard(post_id)
        )
    
    await send_file_to_user(message, post)


@dp.callback_query(F.data.startswith("check_"))
async def recheck_subscription(call: CallbackQuery):
    """Повторная проверка подписки"""
    post_id = call.data.replace("check_", "")
    post = posts.get(post_id)
    
    if not post:
        return await call.answer("❌ Файл не найден", show_alert=True)
    
    if await check_subscription(call.from_user.id):
        await send_file_to_user(call.message, post)
        await call.answer("✅ Подписка подтверждена!")
    else:
        await call.answer(
            "❌ Вы еще не подписаны на канал!\n"
            "Подпишитесь и нажмите кнопку еще раз.",
            show_alert=True
        )


async def send_file_to_user(message: Message, post: dict):
    """Отправка файла пользователю"""
    try:
        if "file" in post:
            await message.answer(
                f"📦 <b>{post['title']}</b>\n\n"
                "⬇️ Загрузка файла..."
            )
            await message.answer_document(
                post["file"],
                caption=f"✅ <b>{post['title']}</b>\n\n💎 Спасибо за использование YAKMODS!"
            )
            logger.info(f"Файл отправлен пользователю {message.from_user.id}")
        else:
            await message.answer(
                f"📦 <b>{post['title']}</b>\n\n"
                f"🔗 Ссылка для скачивания:\n{post['link']}\n\n"
                "💎 Спасибо за использование YAKMODS!"
            )
            logger.info(f"Ссылка отправлена пользователю {message.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")
        await message.answer(
            "❌ Произошла ошибка при отправке файла.\n"
            "Попробуйте позже или обратитесь к администратору."
        )


# =====================
# ОБРАБОТКА ОШИБОК
# =====================

@dp.message()
async def unknown_message(message: Message):
    """Обработка неизвестных сообщений"""
    if is_admin(message.from_user.id):
        await message.answer(
            "ℹ️ Используйте команду /start для доступа к меню",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "ℹ️ Используйте команду /start\n\n"
            "💎 YAKMODS - лучшие моды для ваших игр!"
        )


# =====================
# ЗАПУСК БОТА
# =====================

async def on_startup():
    """Действия при запуске бота"""
    logger.info("🚀 Бот запущен!")
    try:
        bot_info = await bot.get_me()
        logger.info(f"Бот @{bot_info.username} готов к работе")
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")


async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("⛔️ Бот остановлен!")


async def main():
    """Главная функция запуска"""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")

