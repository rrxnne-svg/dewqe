# -*- coding: utf-8 -*-
import asyncio
import uuid
import logging
import time
from datetime import datetime, timedelta
import json
import os
import copy
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto, InputMediaVideo, InputMediaAnimation
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "yakmodsbot"  # Имя бота в Telegram
OWNER_ID = 7388744796  # Создатель бота
admins = {7388744796}  # Множество админов (создатель по умолчанию)
admins_info = {}  # {id: username}
CHANNELS = {
    "main": "@YAKMODS",
}

START_IMAGE = "https://i.pinimg.com/736x/af/44/72/af4472a3b826bf0fdbab074deca37431.jpg"

# Категории модов
CATEGORIES = {
    "ganhaki": "🎮 Гранпаки",
    "mapping": "🗺️ Маппинг",
    "other": "📦 Остальное",
    "timers": "⏱️ Таймциклы",
    "effects": "✨ Эффекты",
    "all": "📂 Все моды"
}

SUGGESTION_COOLDOWN = 60  # 5 минут в секундах
MAX_SUGGESTIONS_PER_USER = 10  # Максимум предложений до бана

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

# Хранилища данных
posts = {}  # {post_id: {data, downloads: 0}}
users = set()  # Все пользователи
banned_users = set()  # Забаненные пользователи
suggestion_cooldowns = {}  # {user_id: last_time}
suggestion_violations = {}  # {user_id: count}

# Черновики и правки: новые посты и незавершенные изменения
drafts = {}   # {post_id: data}  (не публикуемые пока)


# FSM состояния
class AddPost(StatesGroup):
    media = State()
    title = State()
    file = State()
    category = State()
    channels = State()
    notify = State()


class Suggestion(StatesGroup):
    waiting_text = State()


class ReviewSuggestion(StatesGroup):
    waiting_comment = State()


class AddAdmin(StatesGroup):
    waiting_admin_id = State()


# ФАЙЛ ДЛЯ ХРАНЕНИЯ ПОСТОВ
POSTS_FILE = "posts.json"

def save_posts():
    """Сохраняет `posts` в JSON-файл"""
    try:
        with open(POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Не удалось сохранить posts: {e}")


def load_posts():
    """Загружает `posts` из JSON-файла (если есть)"""
    global posts
    if not os.path.exists(POSTS_FILE):
        return
    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                posts = data
    except Exception as e:
        logger.error(f"Не удалось загрузить posts: {e}")


def admin_menu():
    """Клавиатура администратора"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Моды", callback_data="mods_list")],
        [InlineKeyboardButton(text="➕ Добавить пост", callback_data="add_post")],
        [InlineKeyboardButton(text="👥 Управление админами", callback_data="manage_admins")],
        [InlineKeyboardButton(text="⚙️ Управление", callback_data="manage_mods")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])
    return kb


def main_menu():
    """Клавиатура обычного пользователя"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Просмотреть моды", callback_data="mods_list")],
        [InlineKeyboardButton(text="💡 Предложить идею", callback_data="suggest_idea")]
    ])
    return kb


def cancel_inline_kb():
    """Кнопка отмены для inline prompts"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_post")]
    ])


def notify_menu():
    """Кнопки уведомления при публикации"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Уведомить всех", callback_data="notify_yes")],
        [InlineKeyboardButton(text="❌ Не уведомлять", callback_data="notify_no")]
    ])


def download_keyboard(bot_username: str, post_id: str):
    """Кнопка скачивания/предпросмотра для превью"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ Скачать", url=f"https://t.me/{bot_username}?start=download_{post_id}")],
        [InlineKeyboardButton(text=f"@{bot_username}", url=f"https://t.me/{bot_username}")]
    ])
    return kb


def subscribe_keyboard(post_id: str, missing: list):
    """Клавиатура с ссылками на отсутствующие каналы и кнопкой проверки"""
    buttons = []
    for ch in missing:
        # Allow both @name and full URL
        ch_name = ch if ch.startswith("@") else f"@{ch}"
        buttons.append([InlineKeyboardButton(text=ch_name, url=f"https://t.me/{ch_name.lstrip('@')}")])
    buttons.append([InlineKeyboardButton(text="✅ Проверить подписки", callback_data=f"check_{post_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_menu():
    """Кнопки подтверждения/отмены публикации при предпросмотре"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="confirm_post")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_post")]
    ])


def suggestion_review_menu(suggestion_id):
    """Меню для проверки предложения"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{suggestion_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{suggestion_id}")]
    ])


def mods_pagination(page=0, total_pages=1):
    """Пагинация списка модов"""
    buttons = []
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="page_info"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================
# Проверка подписки
# =====================

async def check_subscription(user_id: int, required_channels: list = None) -> tuple:
    """Проверяет подписку пользователя на указанные каналы"""
    if required_channels is None:
        required_channels = ["main"]
    
    not_subscribed = []
    
    for channel in required_channels:
        # Если это ключ из CHANNELS, берем значение, иначе используем как есть
        if channel in CHANNELS:
            channel_id = CHANNELS[channel]
        else:
            channel_id = channel if channel.startswith("@") else "@" + channel
        
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status not in ["member", "creator", "administrator"]:
                not_subscribed.append(channel)
        except TelegramBadRequest as e:
            logger.error(f"Ошибка проверки подписки на {channel_id}: {e}")
            not_subscribed.append(channel)
    
    return len(not_subscribed) == 0, not_subscribed


# =====================
# Проверка бана
# =====================

def is_banned(user_id: int) -> bool:
    """Проверяет, забанен ли пользователь"""
    return user_id in banned_users


def check_suggestion_cooldown(user_id: int) -> tuple:
    """Проверяет кулдаун на предложения"""
    if user_id in suggestion_cooldowns:
        last_time = suggestion_cooldowns[user_id]
        time_passed = time.time() - last_time
        
        if time_passed < SUGGESTION_COOLDOWN:
            remaining = int(SUGGESTION_COOLDOWN - time_passed)
            return False, remaining
    
    return True, 0


def add_suggestion_violation(user_id: int):
    """Добавляет нарушение за спам предложениями"""
    if user_id not in suggestion_violations:
        suggestion_violations[user_id] = 0
    
    suggestion_violations[user_id] += 1
    
    if suggestion_violations[user_id] >= MAX_SUGGESTIONS_PER_USER:
        banned_users.add(user_id)
        return True
    
    return False


# =====================
# Проверка прав администратора
# =====================

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id in admins

def is_owner(user_id: int) -> bool:
    """Проверяет, является ли пользователь создателем бота"""
    return user_id == OWNER_ID

def is_owner(user_id: int) -> bool:
    """Проверяет, является ли пользователь создателем бота"""
    return user_id == OWNER_ID


# =====================
# START
# =====================

@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    users.add(user_id)
    
    # Проверка бана
    if is_banned(user_id):
        return await message.answer(
            "🚫 <b>Вы заблокированы</b>\n\n"
            "Причина: спам предложениями\n"
            "Обратитесь к администратору для разблокировки."
        )
    
    # Обработка deep link для скачивания
    if len(message.text.split()) > 1:
        args = message.text.split()[1]
        if args.startswith("download_"):
            return await handle_download(message, args)
    
    text = (
        "🔥 <b>YAKMODS</b>\n\n"
        "📂 Добро пожаловать в хранилище модов!\n\n"
        "📂 Просмотрите нашу коллекцию модов и загружайте их прямо отсюда."
    )

    try:
        if is_admin(user_id):
            await message.answer_photo(
                START_IMAGE,
                caption=text,
                reply_markup=admin_menu()
            )
        else:
            await message.answer_photo(
                START_IMAGE,
                caption=text,
                reply_markup=main_menu()
            )
    except Exception as e:
        logger.error(f"Ошибка отправки стартового сообщения: {e}")
        if is_admin(user_id):
            await message.answer(text, reply_markup=admin_menu())
        else:
            await message.answer(text, reply_markup=main_menu())


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(call: CallbackQuery):
    """Возврат в главное меню"""
    text = (
        "🔥 <b>YAKMODS</b>\n\n"
        "  Добро пожаловать в хранилище модов!\n\n"
        "📂 Просмотрите нашу коллекцию модов и загружайте их прямо отсюда."
    )
    
    try:
        if is_admin(call.from_user.id):
            await call.message.edit_caption(
                caption=text,
                reply_markup=admin_menu()
            )
        else:
            await call.message.edit_caption(
                caption=text,
                reply_markup=main_menu()
            )
    except:
        if is_admin(call.from_user.id):
            await call.message.answer(text, reply_markup=admin_menu())
        else:
            await call.message.answer(text, reply_markup=main_menu())
    
    await call.answer()


# =====================
# СПИСОК МОДОВ
# =====================

@dp.callback_query(F.data == "mods_list")
async def show_mods_list(call: CallbackQuery):
    """Показывает список категорий модов"""
    if is_banned(call.from_user.id):
        return await call.answer("🚫 Вы заблокированы", show_alert=True)
    
    if not posts:
        await call.answer("📂 Пока нет доступных модов", show_alert=True)
        return
    
    # Удаляем сообщение с кнопкой меню
    try:
        await call.message.delete()
    except:
        pass
    
    # Показываем категории
    buttons = []
    for cat_key, cat_name in CATEGORIES.items():
        # Подсчитываем количество модов в каждой категории
        cat_count = len([p for p in posts.values() if p.get('category') == cat_key]) if cat_key != 'all' else len(posts)
        if cat_count > 0 or cat_key == 'all':
            buttons.append([InlineKeyboardButton(
                text=f"{cat_name} ({cat_count})",
                callback_data=f"cat_browse_{cat_key}" if cat_key != 'all' else "all_mods"
            )])
    
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")])
    
    await call.message.answer(
        "📂 <b>Выберите категорию</b>\n\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@dp.callback_query(F.data.startswith("cat_browse_"))
async def browse_category(call: CallbackQuery):
    """Просмотр модов в категории"""
    if is_banned(call.from_user.id):
        return await call.answer("🚫 Вы заблокированы", show_alert=True)
    
    category = call.data.replace("cat_browse_", "")
    
    # Фильтруем посты по категории
    cat_posts = {pid: p for pid, p in posts.items() if p.get('category') == category}
    
    if not cat_posts:
        await call.answer("📂 В этой категории пока нет модов", show_alert=True)
        return
    
    # Показываем список модов категории
    buttons = []
    for post_id, post_data in list(cat_posts.items())[:10]:
        title = post_data.get('title', 'Без названия')
        downloads = post_data.get('downloads', 0)
        buttons.append([InlineKeyboardButton(
            text=f"📥 {title} ({downloads}⬇️)",
            callback_data=f"get_mod_{post_id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🏠 Назад", callback_data="mods_list")])
    
    cat_name = CATEGORIES.get(category, "Моды")
    await call.message.answer(
        f"📂 <b>{cat_name}</b>\n\n"
        f"Всего модов: {len(cat_posts)}\n\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@dp.callback_query(F.data == "all_mods")
async def show_all_mods(call: CallbackQuery):
    """Показывает все моды"""
    if is_banned(call.from_user.id):
        return await call.answer("🚫 Вы заблокированы", show_alert=True)
    
    if not posts:
        await call.answer("📂 Пока нет доступных модов", show_alert=True)
        return
    
    await show_mods_page(call.message, 0, delete_prev=False)
    await call.answer()


@dp.callback_query(F.data.startswith("page_"))
async def page_navigation(call: CallbackQuery):
    """Навигация по страницам модов"""
    if call.data == "page_info":
        return await call.answer()
    
    page = int(call.data.split("_")[1])
    await show_mods_page(call.message, page, edit=True)
    await call.answer()


async def show_mods_page(message: Message, page: int, edit: bool = False, delete_prev: bool = True):
    """Отображает страницу со списком модов"""
    posts_list = list(posts.items())
    posts_per_page = 5
    total_pages = (len(posts_list) + posts_per_page - 1) // posts_per_page
    
    start_idx = page * posts_per_page
    end_idx = start_idx + posts_per_page
    page_posts = posts_list[start_idx:end_idx]
    
    text = f"📂 <b>Список модов</b> (Страница {page + 1}/{total_pages})\n\n"
    
    buttons = []
    for post_id, post_data in page_posts:
        title = post_data.get('title', 'Без названия')
        downloads = post_data.get('downloads', 0)
        
        text += f"• {title} (⬇️ {downloads})\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"📥 {title}",
            callback_data=f"get_mod_{post_id}"
        )])
    
    # Добавляем навигацию
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="page_info"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
        except:
            await message.answer(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("get_mod_"))
async def get_mod_details(call: CallbackQuery):
    """Показывает детали мода и отправляет его"""
    if is_banned(call.from_user.id):
        return await call.answer("🚫 Вы заблокированы", show_alert=True)
    
    post_id = call.data.replace("get_mod_", "")
    post = posts.get(post_id)
    
    if not post:
        return await call.answer("❌ Мод не найден", show_alert=True)
    
    # Проверка подписки
    required_channels = post.get('required_channels', ['main'])
    is_subscribed, missing = await check_subscription(call.from_user.id, required_channels)
    
    if not is_subscribed:
        await call.message.answer(
            "⚠️ <b>Требуется подписка</b>\n\n"
            "Для скачивания этого мода подпишитесь на указанные каналы:",
            reply_markup=subscribe_keyboard(post_id, missing)
        )
        return await call.answer()
    
    # Увеличиваем счетчик скачиваний
    post['downloads'] = post.get('downloads', 0) + 1
    try:
        save_posts()
    except Exception as e:
        logger.error(f"Ошибка сохранения счетчика скачиваний: {e}")
    
    # Отправляем мод
    await send_file_to_user(call.message, post)
    await call.answer("✅ Мод отправлен!")


# =====================
# АДМИН: Добавление поста
# =====================

@dp.callback_query(F.data == "add_post")
async def add_post_start(call: CallbackQuery, state: FSMContext):
    """Начало процесса добавления поста"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    await state.set_state(AddPost.media)
    # удаляем исходное меню с кнопками
    try:
        await call.message.delete()
    except:
        pass
    await call.message.answer("📸 Отправьте фото, видео или гифку для поста", reply_markup=cancel_inline_kb())
    await call.answer()


@dp.message(AddPost.media, F.photo)
async def process_media_photo(message: Message, state: FSMContext):
    """Обработка фото поста"""
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    
    # Режим редактирования
    if data.get('edit_post_id'):
        post_id = data['edit_post_id']
        
        if post_id not in posts:
            await state.clear()
            return await message.answer("❌ Мод не найден", reply_markup=admin_menu())
        
        # Обновляем медиа в посте
        posts[post_id]['media'] = photo_id
        posts[post_id]['media_type'] = 'photo'
        
        # Синхронизируем с каналами
        await sync_mod_to_channels(post_id, posts[post_id])
        
        # Сохраняем
        try:
            save_posts()
        except Exception:
            pass
        
        await state.clear()
        await message.answer("✅ <b>Фото обновлено!</b>", reply_markup=admin_menu())
    else:
        # Режим создания нового поста
        await state.update_data(media=photo_id, media_type="photo")
        await state.set_state(AddPost.title)
        await message.answer("📝 Введите название поста:", reply_markup=cancel_inline_kb())


@dp.message(AddPost.media, F.video)
async def process_media_video(message: Message, state: FSMContext):
    """Обработка видео поста"""
    data = await state.get_data()
    video_id = message.video.file_id
    
    # Режим редактирования
    if data.get('edit_post_id'):
        post_id = data['edit_post_id']
        
        if post_id not in posts:
            await state.clear()
            return await message.answer("❌ Мод не найден", reply_markup=admin_menu())
        
        # Обновляем медиа в посте
        posts[post_id]['media'] = video_id
        posts[post_id]['media_type'] = 'video'
        
        # Синхронизируем с каналами
        await sync_mod_to_channels(post_id, posts[post_id])
        
        # Сохраняем
        try:
            save_posts()
        except Exception:
            pass
        
        await state.clear()
        await message.answer("✅ <b>Видео обновлено!</b>", reply_markup=admin_menu())
    else:
        # Режим создания нового поста
        await state.update_data(media=video_id, media_type="video")
        await state.set_state(AddPost.title)
        await message.answer("📝 Введите название поста:", reply_markup=cancel_inline_kb())


@dp.message(AddPost.media, F.animation)
async def process_media_animation(message: Message, state: FSMContext):
    """Обработка гифки поста"""
    data = await state.get_data()
    animation_id = message.animation.file_id
    
    # Режим редактирования
    if data.get('edit_post_id'):
        post_id = data['edit_post_id']
        
        if post_id not in posts:
            await state.clear()
            return await message.answer("❌ Мод не найден", reply_markup=admin_menu())
        
        # Обновляем медиа в посте
        posts[post_id]['media'] = animation_id
        posts[post_id]['media_type'] = 'animation'
        
        # Синхронизируем с каналами
        await sync_mod_to_channels(post_id, posts[post_id])
        
        # Сохраняем
        try:
            save_posts()
        except Exception:
            pass
        
        await state.clear()
        await message.answer("✅ <b>Гифка обновлена!</b>", reply_markup=admin_menu())
    else:
        # Режим создания нового поста
        await state.update_data(media=animation_id, media_type="animation")
        await state.set_state(AddPost.title)
        await message.answer("📝 Введите название поста:", reply_markup=cancel_inline_kb())


@dp.message(AddPost.media)
async def invalid_media(message: Message):
    """Обработка неверного формата"""
    await message.answer("❌ Пожалуйста, отправьте фото, видео или гифку!")


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
        , reply_markup=cancel_inline_kb()
    )


@dp.message(AddPost.file)
async def process_file(message: Message, state: FSMContext):
    """Обработка файла или ссылки"""
    data = await state.get_data()
    
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
    
    await state.update_data(**data)
    await state.set_state(AddPost.category)
    
    # Показываем выбор категории
    buttons = []
    for cat_key, cat_name in list(CATEGORIES.items())[:-1]:  # Все кроме "все"
        buttons.append([InlineKeyboardButton(text=cat_name, callback_data=f"cat_{cat_key}")])
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_post")])
    
    await message.answer(
        "📂 <b>Выберите категорию для мода</b>\n\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("cat_"), AddPost.category)
async def process_category(call: CallbackQuery, state: FSMContext):
    """Обработка выбора категории"""
    category = call.data.replace("cat_", "")
    
    if category not in CATEGORIES:
        return await call.answer("❌ Неверная категория", show_alert=True)
    
    await state.update_data(category=category)
    await state.set_state(AddPost.channels)
    
    await call.message.edit_text(
        "📢 <b>Укажите каналы для публикации</b>\n\n"
        "Напишите названия каналов через пробел.\n"
        "Можно указывать с @ или без:\n"
        "Пример: @YAKMODS\n"
    )
    await call.answer()


@dp.message(AddPost.channels)
async def process_channels(message: Message, state: FSMContext):
    """Обработка выбора каналов"""
    text = message.text.strip()
    data = await state.get_data()
    
    selected_channels = []
    
    # Проверяем "все" для стандартных каналов
    if text.lower() == "все":
        selected_channels = list(CHANNELS.values())
    else:
        # Парсим введённые каналы
        channel_names = text.split()
        for channel_name in channel_names:
            # Убираем @ если есть и приводим к правильному формату
            channel_name = channel_name.strip()
            if not channel_name.startswith("@"):
                channel_name = "@" + channel_name
            
            # Проверяем что это похоже на валидный канал
            if len(channel_name) < 2 or not channel_name[1:].replace("_", "").isalnum():
                return await message.answer(
                    f"❌ Некорректный формат канала: <code>{channel_name}</code>\n\n"
                    "Канал должен содержать буквы, цифры и подчеркивания.\n"
                    "Пример: @my_channel или my_channel"
                )
            
            selected_channels.append(channel_name)
    
    if not selected_channels:
        return await message.answer(
            "❌ Вы не указали ни одного канала!\n\n"
            "Напишите названия каналов через пробел, например:\n"
            "@YAKMODS "
        )
    
    await state.update_data(selected_channels=selected_channels, required_channels=selected_channels)
    await state.set_state(AddPost.notify)
    
    await message.answer(
        f"✅ <b>Выбранные каналы:</b>\n{', '.join(selected_channels)}\n\n"
        "📬 <b>Уведомить всех пользователей о новом посте?</b>",
        reply_markup=notify_menu()
    )


@dp.callback_query(F.data.startswith("channel_"), AddPost.channels)
async def toggle_channel(call: CallbackQuery, state: FSMContext):
    """Обработчик отключен - используется текстовый ввод"""
    await call.answer("Используйте текстовый ввод для выбора каналов", show_alert=True)


@dp.callback_query(F.data == "channels_done", AddPost.channels)
async def channels_done(call: CallbackQuery, state: FSMContext):
    """Обработчик отключен - используется текстовый ввод"""
    await call.answer("Используйте текстовый ввод для выбора каналов", show_alert=True)


@dp.callback_query(F.data.startswith("notify_"), AddPost.notify)
async def process_notify(call: CallbackQuery, state: FSMContext):
    """Обработка выбора уведомлений"""
    notify = call.data == "notify_yes"
    await state.update_data(notify_users=notify)
    
    data = await state.get_data()
    post_id = str(uuid.uuid4())
    data["post_id"] = post_id
    data["downloads"] = 0
    # Сохраняем как черновик (не публикуем до подтверждения)
    drafts[post_id] = data
    await state.update_data(**data)
    
    try:
        await call.message.delete()
    except:
        pass
    
    # Показываем превью
    bot_username = (await bot.get_me()).username
    preview_kb = download_keyboard(bot_username, post_id)
    
    caption = f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"
    
    if "file" in data:
        file_size_mb = data['file_size'] / (1024 * 1024)
        caption += f"\n\n📦 Файл: {data['file_name']}\n💾 Размер: {file_size_mb:.2f} МБ"
    
    selected_channels = data.get('selected_channels', [])
    
    # Проверяем наличие медиа
    if "media" not in data:
        await call.answer("❌ Медиа не найдено! Начните создание поста с начала.", show_alert=True)
        await state.clear()
        return
    
    # Отправляем медиа в зависимости от типа
    media_id = data.get("media")
    media_type = data.get("media_type", "photo")
    
    # Отправляем медиа и сохраняем ID превью-сообщений для возможного удаления
    preview_message_ids = []
    try:
        if media_type == "video":
            media_msg = await call.message.answer_video(media_id, caption=caption, reply_markup=preview_kb)
        elif media_type == "animation":
            media_msg = await call.message.answer_animation(media_id, caption=caption, reply_markup=preview_kb)
        else:  # photo
            media_msg = await call.message.answer_photo(media_id, caption=caption, reply_markup=preview_kb)
        preview_message_ids.append((media_msg.chat.id, media_msg.message_id))
    except Exception:
        media_msg = None

    notify_text = "✅ Да" if notify else "❌ Нет"

    preview_text_msg = await call.message.answer(
        "📋 <b>Предпросмотр поста</b>\n\n"
        f"📢 Каналы: {', '.join(selected_channels)}\n"
        f"📬 Уведомления: {notify_text}\n\n"
        "Проверьте все данные и выберите действие:",
        reply_markup=confirm_menu()
    )
    preview_message_ids.append((preview_text_msg.chat.id, preview_text_msg.message_id))

    # Сохраняем ID превью в черновике (чтобы удалить при отмене или публикации)
    drafts[post_id]['preview_messages'] = preview_message_ids
    await call.answer()


@dp.callback_query(F.data == "confirm_post")
async def confirm_publication(call: CallbackQuery, state: FSMContext):
    """Публикация поста в каналы"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    data = await state.get_data()
    post_id = data.get("post_id")

    # Получаем черновик (если есть). Если черновика нет — пытаемся взять из опубликованных.
    draft = drafts.pop(post_id, None)
    if draft is not None:
        data = draft
    else:
        data = posts.get(post_id, data)
    
    bot_username = (await bot.get_me()).username
    kb = download_keyboard(bot_username, post_id)
    
    caption = f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"
    
    selected_channels = data.get('selected_channels', [])
    published_count = 0
    
    # Инициализируем словарь для хранения message_id в каналах
    if 'published' not in data:
        data['published'] = {}
    
    # Публикуем в выбранные каналы
    for channel_name in selected_channels:
        # Если это ключ из CHANNELS, берем значение, иначе используем как есть
        if channel_name in CHANNELS:
            channel_id = CHANNELS[channel_name]
        else:
            channel_id = channel_name if channel_name.startswith("@") else "@" + channel_name
        
        try:
            media_id = data.get("media")
            media_type = data.get("media_type", "photo")
            
            msg = None
            if media_type == "video":
                msg = await bot.send_video(channel_id, video=media_id, caption=caption, reply_markup=kb)
            elif media_type == "animation":
                msg = await bot.send_animation(channel_id, animation=media_id, caption=caption, reply_markup=kb)
            else:  # photo
                msg = await bot.send_photo(channel_id, photo=media_id, caption=caption, reply_markup=kb)
            
            # Сохраняем message_id для возможного редактирования
            if msg:
                data['published'][channel_id] = msg.message_id
            
            published_count += 1
        except Exception as e:
            logger.error(f"Ошибка публикации в {channel_id}: {e}")
    
    # Уведомляем пользователей если нужно
    if data.get('notify_users', False):
        notified = await notify_all_users(data, post_id)
        await call.message.answer(
            f"✅ <b>Пост опубликован!</b>\n\n"
            f"📢 Опубликовано в каналов: {published_count}\n"
            f"📬 Уведомлено пользователей: {notified}\n"
            f"📊 ID поста: <code>{post_id}</code>",
            reply_markup=admin_menu()
        )
    else:
        await call.message.answer(
            f"✅ <b>Пост опубликован!</b>\n\n"
            f"📢 Опубликовано в каналов: {published_count}\n"
            f"📊 ID поста: <code>{post_id}</code>",
            reply_markup=admin_menu()
        )
    
    await state.clear()
    # Если был черновик — переносим в опубликованные и сохраняем
    if post_id not in posts and draft is not None:
        posts[post_id] = data
        try:
            save_posts()
        except Exception:
            pass

    # Удаляем превью-сообщения, если остались (берём из черновика или из поста)
    preview_msgs = []
    if draft is not None:
        preview_msgs = draft.get('preview_messages', [])
    else:
        preview_msgs = posts.get(post_id, {}).get('preview_messages', [])

    for chat_id, msg_id in preview_msgs:
        try:
            await bot.delete_message(chat_id, msg_id)
        except:
            pass
    await call.answer()


async def notify_all_users(post_data, post_id):
    """Уведомляет всех пользователей о новом посте"""
    bot_username = (await bot.get_me()).username
    kb = download_keyboard(bot_username, post_id)
    
    caption = f"🆕 <b>Новый мод!</b>\n\n🔥 {post_data['title']}\n\n📥 Нажмите кнопку для скачивания"
    
    notified = 0
    for user_id in users:
        if not is_admin(user_id) and not is_banned(user_id):
            try:
                media_id = post_data.get("media")
                media_type = post_data.get("media_type", "photo")

                if media_type == "video":
                    await bot.send_video(user_id, video=media_id, caption=caption, reply_markup=kb)
                elif media_type == "animation":
                    await bot.send_animation(user_id, animation=media_id, caption=caption, reply_markup=kb)
                else:  # photo
                    await bot.send_photo(user_id, photo=media_id, caption=caption, reply_markup=kb)

                notified += 1
                await asyncio.sleep(0.05)  # Защита от флуда
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    
    return notified





@dp.callback_query(F.data == "cancel_post")
async def cancel_post(call: CallbackQuery, state: FSMContext):
    """Отмена создания поста"""
    data = await state.get_data()
    post_id = data.get("post_id")
    # Если это черновик — удаляем только черновик
    if post_id and post_id in drafts:
        preview_msgs = drafts[post_id].get('preview_messages', [])
        for chat_id, msg_id in preview_msgs:
            try:
                await bot.delete_message(chat_id, msg_id)
            except:
                pass
        del drafts[post_id]

    # Если же пост уже опубликован — удаляем его из публикаций
    elif post_id and post_id in posts:
        preview_msgs = posts[post_id].get('preview_messages', [])
        for chat_id, msg_id in preview_msgs:
            try:
                await bot.delete_message(chat_id, msg_id)
            except:
                pass
        del posts[post_id]
        try:
            save_posts()
        except Exception:
            pass
    
    await state.clear()
    await call.message.answer("❌ Создание поста отменено", reply_markup=admin_menu())
    await call.answer()


# =====================
# РЕДАКТИРОВАНИЕ МОДОВ
# =====================

@dp.callback_query(F.data.startswith("edit_mod_"))
async def show_mod_edit_menu(call: CallbackQuery):
    """Показывает меню редактирования мода"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    post_id = call.data.replace("edit_mod_", "")
    
    if post_id not in posts:
        return await call.answer("❌ Мод не найден", show_alert=True)
    
    post = posts[post_id]
    
    title = post.get('title', 'N/A')
    file_type = 'Файл' if 'file' in post else 'Ссылка' if 'link' in post else 'N/A'
    channels = ', '.join(post.get('selected_channels', []))
    
    info = f"""
📋 <b>Редактирование мода</b>

📝 Название: <code>{title}</code>
📦 Тип: {file_type}
📢 Каналы: {channels}
⬇️ Скачиваний: {post.get('downloads', 0)}

Выберите что редактировать:
""".strip()
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_title_{post_id}")],
        [InlineKeyboardButton(text="📦 Файл/Ссылка", callback_data=f"edit_file_{post_id}")],
        [InlineKeyboardButton(text="📸 Фото/Видео", callback_data=f"edit_media_{post_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="manage_mods")]
    ]
    
    try:
        await call.message.edit_text(info, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except:
        await call.message.answer(info, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    
    await call.answer()


@dp.callback_query(F.data.startswith("edit_title_"))
async def edit_title_start(call: CallbackQuery, state: FSMContext):
    """Начало редактирования названия модов"""
    post_id = call.data.replace("edit_title_", "")
    
    if post_id not in posts:
        return await call.answer("❌ Мод не найден", show_alert=True)
    
    await state.set_state(AddPost.title)
    await state.update_data(edit_post_id=post_id, edit_field="title")
    
    try:
        await call.message.delete()
    except:
        pass
    
    await call.message.answer(
        "📝 Введите новое название для мода:\n\n"
        "(максимум 200 символов)",
        reply_markup=cancel_inline_kb()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("edit_file_"))
async def edit_file_start(call: CallbackQuery, state: FSMContext):
    """Начало редактирования файла мода"""
    post_id = call.data.replace("edit_file_", "")
    
    if post_id not in posts:
        return await call.answer("❌ Мод не найден", show_alert=True)
    
    await state.set_state(AddPost.file)
    await state.update_data(edit_post_id=post_id, edit_field="file")
    
    try:
        await call.message.delete()
    except:
        pass
    
    await call.message.answer(
        "📦 Отправьте новый файл или ссылку для скачивания:",
        reply_markup=cancel_inline_kb()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("edit_media_"))
async def edit_media_start(call: CallbackQuery, state: FSMContext):
    """Начало редактирования медиа мода"""
    post_id = call.data.replace("edit_media_", "")
    
    if post_id not in posts:
        return await call.answer("❌ Мод не найден", show_alert=True)
    
    await state.set_state(AddPost.media)
    await state.update_data(edit_post_id=post_id, edit_field="media")
    
    try:
        await call.message.delete()
    except:
        pass
    
    await call.message.answer(
        "📸 Отправьте новое фото, видео или гифку:",
        reply_markup=cancel_inline_kb()
    )
    await call.answer()


async def sync_mod_to_channels(post_id: str, post_data: dict):
    """Синхронизирует изменения мода в все каналы где он был опубликован"""
    bot_username = (await bot.get_me()).username
    kb = download_keyboard(bot_username, post_id)
    
    caption = f"🔥 <b>{post_data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"
    
    if "file" in post_data:
        file_size_mb = post_data['file_size'] / (1024 * 1024)
        caption += f"\n\n📦 Файл: {post_data['file_name']}\n💾 Размер: {file_size_mb:.2f} МБ"
    
    # Получаем список каналов где был опубликован
    published = post_data.get('published', {})
    
    for channel_id, message_id in published.items():
        try:
            media_id = post_data.get("media")
            media_type = post_data.get("media_type", "photo")
            
            # Пытаемся обновить существующее сообщение
            if media_type == "video":
                await bot.edit_message_media(
                    chat_id=channel_id,
                    message_id=message_id,
                    media=InputMediaVideo(media=media_id, caption=caption, parse_mode=ParseMode.HTML),
                    reply_markup=kb
                )
            elif media_type == "animation":
                await bot.edit_message_media(
                    chat_id=channel_id,
                    message_id=message_id,
                    media=InputMediaAnimation(media=media_id, caption=caption, parse_mode=ParseMode.HTML),
                    reply_markup=kb
                )
            else:  # photo
                await bot.edit_message_media(
                    chat_id=channel_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=media_id, caption=caption, parse_mode=ParseMode.HTML),
                    reply_markup=kb
                )
        except Exception as e:
            logger.error(f"Ошибка обновления поста в канале {channel_id}: {e}")


# =====================
# УПРАВЛЕНИЕ МОДАМИ
# =====================


@dp.callback_query(F.data == "manage_mods")
async def manage_mods(call: CallbackQuery):
    """Управление модами"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    if not posts:
        try:
            await call.message.delete()
        except:
            pass
        
        await call.message.answer(
            "📂 <b>Управление модами</b>\n\n"
            "Нет доступных модов для управления.",
            reply_markup=admin_menu()
        )
        return await call.answer()
    
    # Показываем список модов с опциями
    buttons = []
    for post_id, post_data in list(posts.items())[:10]:  # Первые 10
        title = post_data.get('title', 'Без названия')[:20]  # Обрезаем название
        buttons.append([
            InlineKeyboardButton(text=f"📄 {title}", callback_data=f"get_mod_{post_id}"),
            InlineKeyboardButton(text="✏️", callback_data=f"edit_mod_{post_id}"),
            InlineKeyboardButton(text="🗑️", callback_data=f"delete_mod_{post_id}")
        ])
    
    buttons.append([InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    total = len(posts)
    
    try:
        await call.message.edit_text(
            f"📂 <b>Управление модами</b>\n\n"
            f"Всего модов: {total}\n\n"
            "Нажмите на кнопки для редактирования или удаления:",
            reply_markup=kb
        )
    except:
        await call.message.answer(
            f"📂 <b>Управление модами</b>\n\n"
            f"Всего модов: {total}\n\n"
            "Нажмите на кнопки для редактирования или удаления:",
            reply_markup=kb
        )
    
    await call.answer()


@dp.callback_query(F.data.startswith("delete_mod_"))
async def delete_mod(call: CallbackQuery):
    """Удаление мода"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    post_id = call.data.replace("delete_mod_", "")
    
    if post_id not in posts:
        return await call.answer("❌ Мод не найден", show_alert=True)
    
    post_title = posts[post_id].get('title', 'Неизвестный мод')
    del posts[post_id]
    try:
        save_posts()
    except Exception:
        pass
    
    try:
        await call.message.delete()
    except:
        pass
    
    await call.message.answer(
        f"✅ <b>Мод удален!</b>\n\n"
        f"Название: <code>{post_title}</code>\n\n"
        f"Всего модов осталось: {len(posts)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 К управлению", callback_data="manage_mods")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")]
        ])
    )
    await call.answer("🗑️ Мод успешно удален!")














@dp.message(AddPost.title)
async def process_edit_title(message: Message, state: FSMContext):
    """Сохранение названия для нового поста или редактирование существующего"""
    data = await state.get_data()
    
    # Режим редактирования
    if data.get('edit_post_id'):
        post_id = data['edit_post_id']
        
        if post_id not in posts:
            await state.clear()
            return await message.answer("❌ Мод не найден", reply_markup=admin_menu())
        
        # Обновляем название в посте
        posts[post_id]['title'] = message.text
        
        # Синхронизируем с каналами
        await sync_mod_to_channels(post_id, posts[post_id])
        
        # Сохраняем
        try:
            save_posts()
        except Exception:
            pass
        
        await state.clear()
        await message.answer(
            f"✅ <b>Название обновлено!</b>\n\n"
            f"Новое название: <code>{message.text}</code>",
            reply_markup=admin_menu()
        )
    else:
        # Режим создания нового поста
        await state.update_data(title=message.text)
        await state.set_state(AddPost.file)
        await message.answer(
            "📦 Отправьте файл (документ) или ссылку для скачивания:\n\n"
            "💡 Совет: Для ссылок используйте прямые ссылки на файлы",
            reply_markup=cancel_inline_kb()
        )


@dp.message(AddPost.file)
async def process_edit_file(message: Message, state: FSMContext):
    """Сохранение файла/ссылки для нового поста или редактирование существующего"""
    data = await state.get_data()
    
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
    
    # Режим редактирования
    if data.get('edit_post_id'):
        post_id = data['edit_post_id']
        
        if post_id not in posts:
            await state.clear()
            return await message.answer("❌ Мод не найден", reply_markup=admin_menu())
        
        # Обновляем файл/ссылку в посте
        posts[post_id].update(data)
        
        # Синхронизируем с каналами
        await sync_mod_to_channels(post_id, posts[post_id])
        
        # Сохраняем
        try:
            save_posts()
        except Exception:
            pass
        
        await state.clear()
        await message.answer(
            f"✅ <b>Файл обновлен!</b>",
            reply_markup=admin_menu()
        )
    else:
        # Режим создания нового поста
        await state.update_data(**data)
        await state.set_state(AddPost.channels)
        
        await message.answer(
            "📢 <b>Укажите каналы для публикации</b>\n\n"
            "Напишите названия каналов через пробел.\n"
            "Можно указывать с @ или без:\n"
            "Пример: @YAKMODS \n"
            "или: YAKMODS\n\n"
            "Или напишите 'все' для публикации во все стандартные каналы.",
            reply_markup=cancel_inline_kb()
        )


@dp.message(AddPost.channels)
async def process_edit_channels(message: Message, state: FSMContext):
    """Сохранение каналов для нового поста"""
    data = await state.get_data()
    text = message.text.strip()

    # Проверяем нажата ли кнопка отмены
    if text == "❌ Отмена":
        await state.clear()
        return await message.answer("❌ Действие отменено", reply_markup=admin_menu() if is_admin(message.from_user.id) else main_menu())

    selected_channels = []

    # Проверяем "все" для стандартных каналов
    if text.lower() == "все":
        selected_channels = list(CHANNELS.values())
    else:
        # Парсим введённые каналы
        channel_names = text.split()
        for channel_name in channel_names:
            # Убираем @ если есть и приводим к правильному формату
            channel_name = channel_name.strip()
            if not channel_name.startswith("@"):
                channel_name = "@" + channel_name

            # Проверяем что это похоже на валидный канал
            if len(channel_name) < 2 or not channel_name[1:].replace("_", "").isalnum():
                return await message.answer(
                    f"❌ Некорректный формат канала: <code>{channel_name}</code>\n\n"
                    "Канал должен содержать буквы, цифры и подчеркивания.\n"
                    "Пример: @my_channel или my_channel"
                )

            selected_channels.append(channel_name)

    if not selected_channels:
        return await message.answer(
            "❌ Вы не указали ни одного канала!\n\n"
            "Напишите названия каналов через пробел, например:\n"
            "@YAKMODS"
        )

    await state.update_data(selected_channels=selected_channels, required_channels=selected_channels)
    await state.set_state(AddPost.notify)

    await message.answer(
        f"✅ <b>Выбранные каналы:</b>\n{', '.join(selected_channels)}\n\n"
        "📬 <b>Уведомить всех пользователей о новом посте?</b>",
        reply_markup=notify_menu()
    )


@dp.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery):
    """Показывает статистику бота"""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Доступ запрещен", show_alert=True)
    
    total_downloads = sum(post.get('downloads', 0) for post in posts.values())
    
    # Топ 5 модов по скачиваниям
    top_mods = sorted(posts.items(), key=lambda x: x[1].get('downloads', 0), reverse=True)[:5]
    top_text = "\n".join([f"{i+1}. {post['title']}: {post.get('downloads', 0)} ⬇️" 
                          for i, (_, post) in enumerate(top_mods)])
    
    stats_text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"📝 Всего постов: {len(posts)}\n"
        f"👥 Всего пользователей: {len(users)}\n"
        f"⬇️ Всего скачиваний: {total_downloads}\n"
        f"🚫 Заблокировано: {len(banned_users)}\n\n"
        f"🏆 <b>Топ 5 модов:</b>\n{top_text if top_text else 'Нет данных'}\n\n"
        f"⚡️ Статус: Активен"
    )
    
    await call.message.answer(stats_text, reply_markup=admin_menu())
    await call.answer()


# ====================
# УПРАВЛЕНИЕ АДМИНАМИ
# =====================

@dp.callback_query(F.data == "manage_admins")
async def manage_admins(call: CallbackQuery):
    """Управление админами (доступно только для создателя)"""
    if not is_owner(call.from_user.id):
        return await call.answer("❌ Только создатель может управлять админами", show_alert=True)
    
    # Формируем список текущих админов
    admins_list = ", ".join([f"ID: {admin_id}" for admin_id in admins])
    
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="list_admins")],
        [InlineKeyboardButton(text="❌ Удалить админа", callback_data="remove_admin")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")]
    ]
    
    await call.message.answer(
        "👥 <b>Управление админами</b>\n\n"
        f"Текущих админов: {len(admins)}\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@dp.callback_query(F.data == "add_admin")
async def add_admin_start(call: CallbackQuery, state: FSMContext):
    """Начало процесса добавления админа"""
    if not is_owner(call.from_user.id):
        return await call.answer("❌ Только создатель может управлять админами", show_alert=True)
    
    await state.set_state(AddAdmin.waiting_admin_id)
    await call.message.answer(
        "👤 <b>Добавление админа</b>\n\n"
        "Отправьте Telegram ID пользователя, которого хотите сделать админом.\n\n"
        "💡 Пример: <code>123456789</code>\n\n"
        "или напишите /отмена для отмены"
    )
    await call.answer()


@dp.message(AddAdmin.waiting_admin_id)
async def process_add_admin(message: Message, state: FSMContext):
    """Обработка добавления админа"""
    if not is_owner(message.from_user.id):
        return await message.answer("❌ Только создатель может управлять админами")
    
    # Проверка на отмену
    if message.text.lower() in ["/отмена", "отмена"]:
        await state.clear()
        return await message.answer(
            "❌ Добавление отменено",
            reply_markup=admin_menu()
        )
    
    try:
        admin_id = int(message.text.strip())
        
        # Проверяем, не админ ли уже
        if admin_id in admins:
            await message.answer(
                f"⚠️ <b>Уже админ</b>\n\n"
                f"ID: {admin_id} уже является администратором"
            )
        else:
            # Добавляем админа
            admins.add(admin_id)
            # Пытаемся получить username
            try:
                user = await bot.get_chat(admin_id)
                username = getattr(user, 'username', None)
            except Exception:
                username = None
            admins_info[admin_id] = username

            await message.answer(
                f"✅ <b>Админ добавлен!</b>\n\n"
                f"ID: {admin_id} {'('+username+')' if username else ''}\n"
                f"Всего админов: {len(admins)}",
                reply_markup=admin_menu()
            )
        
        await state.clear()
        
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка!</b>\n\n"
            "ID должен быть числом.\n\n"
            "Попробуйте еще раз или напишите /отмена"
        )


@dp.callback_query(F.data == "list_admins")
async def list_admins(call: CallbackQuery):
    """Показать список администраторов"""
    if not is_owner(call.from_user.id):
        return await call.answer("❌ Только создатель может просматривать список админов", show_alert=True)
    
    admins_lines = []
    for admin_id in sorted(admins):
        name = admins_info.get(admin_id)
        if not name:
            try:
                user = await bot.get_chat(admin_id)
                name = getattr(user, 'username', None)
                admins_info[admin_id] = name
            except Exception:
                name = None
        if name:
            admins_lines.append(f"👤 ID: <code>{admin_id}</code> — @{name}")
        else:
            admins_lines.append(f"👤 ID: <code>{admin_id}</code>")
    admins_text = "\n".join(admins_lines)
    
    await call.message.answer(
        f"👥 <b>Список администраторов</b>\n\n"
        f"{admins_text}\n\n"
        f"Всего админов: {len(admins)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Управление админами", callback_data="manage_admins")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")]
        ])
    )
    await call.answer()


@dp.callback_query(F.data == "remove_admin")
async def remove_admin_start(call: CallbackQuery, state: FSMContext):
    """Начало процесса удаления админа"""
    if not is_owner(call.from_user.id):
        return await call.answer("❌ Только создатель может управлять админами", show_alert=True)
    
    # Проверяем, есть ли админы помимо создателя
    other_admins = admins - {OWNER_ID}
    
    if not other_admins:
        await call.message.answer(
            "⚠️ <b>Нет админов для удаления</b>\n\n"
            "У вас только вы как создатель.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Управление админами", callback_data="manage_admins")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")]
            ])
        )
        return await call.answer()
    
    # Показываем список для удаления
    buttons = []
    for admin_id in sorted(other_admins):
        buttons.append([InlineKeyboardButton(
            text=f"❌ {admin_id}",
            callback_data=f"confirm_remove_{admin_id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🏠 Отмена", callback_data="manage_admins")])
    
    await call.message.answer(
        "❌ <b>Удаление админа</b>\n\n"
        "Выберите админа для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@dp.callback_query(F.data.startswith("confirm_remove_"))
async def confirm_remove_admin(call: CallbackQuery):
    """Подтверждение удаления админа"""
    if not is_owner(call.from_user.id):
        return await call.answer("❌ Только создатель может управлять админами", show_alert=True)
    
    admin_id = int(call.data.replace("confirm_remove_", ""))
    
    if admin_id not in admins or admin_id == OWNER_ID:
        return await call.answer("❌ Админ не найден", show_alert=True)
    
    # Удаляем админа
    admins.discard(admin_id)
    admins_info.pop(admin_id, None)
    
    await call.message.answer(
        f"✅ <b>Админ удален!</b>\n\n"
        f"ID: {admin_id}\n"
        f"Всего админов: {len(admins)}",
        reply_markup=admin_menu()
    )
    await call.answer("✅ Админ успешно удален!")


# =====================
# ПРЕДЛОЖЕНИЯ
# =====================

@dp.callback_query(F.data == "suggest_idea")
async def suggest_idea_start(call: CallbackQuery, state: FSMContext):
    """Начало процесса предложения идеи"""
    user_id = call.from_user.id
    
    if is_banned(user_id):
        return await call.answer("🚫 Вы заблокированы за спам предложениями", show_alert=True)
    
    # Проверка кулдауна
    can_suggest, remaining = check_suggestion_cooldown(user_id)
    
    if not can_suggest:
        minutes = remaining // 60
        seconds = remaining % 60
        return await call.answer(
            f"⏳ Подождите {minutes}м {seconds}с перед следующим предложением",
            show_alert=True
        )
    
    await state.set_state(Suggestion.waiting_text)
    await call.message.answer(
        "💡 <b>Предложить идею</b>\n\n"
        "Опишите вашу идею или предложение.\n"
        "Можете прикрепить фото.\n\n"
        "⚠️ Не спамьте! Кулдаун: 5 минут"
    )
    await call.answer()


@dp.message(Suggestion.waiting_text)
async def process_suggestion(message: Message, state: FSMContext):
    """Обработка предложения"""
    user_id = message.from_user.id
    
    # Проверка кулдауна еще раз
    can_suggest, remaining = check_suggestion_cooldown(user_id)
    
    if not can_suggest:
        is_banned_now = add_suggestion_violation(user_id)
        
        if is_banned_now:
            await state.clear()
            return await message.answer(
                "🚫 <b>Вы заблокированы!</b>\n\n"
                "Причина: спам предложениями\n"
                "Обратитесь к администратору."
            )
        
        minutes = remaining // 60
        seconds = remaining % 60
        return await message.answer(
            f"⏳ Слишком быстро! Подождите {minutes}м {seconds}с"
        )
    
    # Сохраняем время последнего предложения
    suggestion_cooldowns[user_id] = time.time()
    
    suggestion_id = str(uuid.uuid4())
    
    # Формируем сообщение админу
    user_mention = message.from_user.mention_html()
    suggestion_text = (
        f"💡 <b>Новое предложение #{suggestion_id[:8]}</b>\n\n"
        f"👤 От: {user_mention} (ID: {user_id})\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📝 <b>Текст:</b>\n{message.text or message.caption or 'Нет текста'}"
    )
    
    # Отправляем админу
    try:
        if message.photo:
            await bot.send_photo(
                OWNER_ID,
                photo=message.photo[-1].file_id,
                caption=suggestion_text,
                reply_markup=suggestion_review_menu(suggestion_id)
            )
        else:
            await bot.send_message(
                OWNER_ID,
                text=suggestion_text,
                reply_markup=suggestion_review_menu(suggestion_id)
            )
        
        # Сохраняем предложение
        await state.update_data(
            suggestion_id=suggestion_id,
            user_id=user_id,
            text=message.text or message.caption,
            photo=message.photo[-1].file_id if message.photo else None
        )
        
        await message.answer(
            "✅ <b>Предложение отправлено!</b>\n\n"
            "Администратор рассмотрит его в ближайшее время.\n"
            "Вы получите уведомление о решении."
        )
        
    except Exception as e:
        logger.error(f"Ошибка отправки предложения: {e}")
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")
    
    await state.clear()


@dp.callback_query(F.data.startswith("approve_"))
async def approve_suggestion(call: CallbackQuery, state: FSMContext):
    """Одобрение предложения"""
    suggestion_id = call.data.replace("approve_", "")
    
    await state.update_data(
        suggestion_id=suggestion_id,
        action="approve",
        original_message_id=call.message.message_id
    )
    await state.set_state(ReviewSuggestion.waiting_comment)
    
    await call.message.answer(
        "✅ <b>Одобрение предложения</b>\n\n"
        "Напишите комментарий для пользователя:"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("reject_"))
async def reject_suggestion(call: CallbackQuery, state: FSMContext):
    """Отклонение предложения"""
    suggestion_id = call.data.replace("reject_", "")
    
    await state.update_data(
        suggestion_id=suggestion_id,
        action="reject",
        original_message_id=call.message.message_id
    )
    await state.set_state(ReviewSuggestion.waiting_comment)
    
    await call.message.answer(
        "❌ <b>Отклонение предложения</b>\n\n"
        "Напишите комментарий для пользователя:"
    )
    await call.answer()


@dp.message(ReviewSuggestion.waiting_comment)
async def process_review_comment(message: Message, state: FSMContext):
    """Обработка комментария к решению"""
    data = await state.get_data()
    suggestion_id = data['suggestion_id']
    action = data['action']
    comment = message.text
    
    # Ищем пользователя из оригинального сообщения
    # В реальном боте нужно сохранять данные в БД
    # Для примера извлечем из текста сообщения
    try:
        original_msg = await bot.edit_message_reply_markup(
            chat_id=OWNER_ID,
            message_id=data['original_message_id'],
            reply_markup=None
        )
        
        # Извлекаем user_id из текста
        text = original_msg.caption or original_msg.text
        user_id = int(text.split("ID: ")[1].split(")")[0])
        
        if action == "approve":
            result_text = (
                "✅ <b>Ваше предложение одобрено!</b>\n\n"
                f"💬 Комментарий администратора:\n{comment}"
            )
            admin_text = f"✅ Предложение #{suggestion_id[:8]} одобрено"
        else:
            result_text = (
                "❌ <b>Ваше предложение отклонено</b>\n\n"
                f"💬 Комментарий администратора:\n{comment}"
            )
            admin_text = f"❌ Предложение #{suggestion_id[:8]} отклонено"
        
        # Отправляем пользователю
        await bot.send_message(user_id, result_text)
        
        # Подтверждаем админу
        await message.answer(admin_text, reply_markup=admin_menu())
        
    except Exception as e:
        logger.error(f"Ошибка обработки решения: {e}")
        await message.answer("❌ Ошибка отправки ответа пользователю")
    
    await state.clear()


# =====================
# СКАЧИВАНИЕ
# =====================

async def handle_download(message: Message, args: str):
    """Обработка запроса на скачивание"""
    if is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы")
    
    post_id = args.replace("download_", "")
    post = posts.get(post_id)
    
    if not post:
        return await message.answer(
            "❌ <b>Файл не найден</b>\n\n"
            "Возможно, пост был удален или ссылка устарела."
        )
    
    # Проверка подписки
    required_channels = post.get('required_channels', ['main'])
    is_subscribed, missing = await check_subscription(message.from_user.id, required_channels)
    
    if not is_subscribed:
        return await message.answer(
            "⚠️ <b>Требуется подписка</b>\n\n"
            "Для скачивания подпишитесь на указанные каналы:",
            reply_markup=subscribe_keyboard(post_id, missing)
        )
    
    # Увеличиваем счетчик скачиваний
    post['downloads'] = post.get('downloads', 0) + 1
    try:
        save_posts()
    except Exception as e:
        logger.error(f"Ошибка сохранения счетчика скачиваний: {e}")
    
    await send_file_to_user(message, post)


@dp.callback_query(F.data.startswith("check_"))
async def recheck_subscription(call: CallbackQuery):
    """Повторная проверка подписки"""
    if is_banned(call.from_user.id):
        return await call.answer("🚫 Вы заблокированы", show_alert=True)
    
    post_id = call.data.replace("check_", "")
    post = posts.get(post_id)
    
    if not post:
        return await call.answer("❌ Файл не найден", show_alert=True)
    
    required_channels = post.get('required_channels', ['main'])
    is_subscribed, missing = await check_subscription(call.from_user.id, required_channels)
    
    if is_subscribed:
        # Увеличиваем счетчик скачиваний
        post['downloads'] = post.get('downloads', 0) + 1
        
        await send_file_to_user(call.message, post)
        await call.answer("✅ Подписка подтверждена!")
    else:
        await call.answer(
            "❌ Вы еще не подписаны на все требуемые каналы!\n"
            "Подпишитесь и нажмите кнопку еще раз.",
            show_alert=True
        )


@dp.callback_query(F.data.startswith("download_"))
async def download_mod(call: CallbackQuery):
    """Обработка нажатия на кнопку скачивания"""
    if is_banned(call.from_user.id):
        return await call.answer("🚫 Вы заблокированы", show_alert=True)
    
    post_id = call.data.replace("download_", "")
    post = posts.get(post_id)
    
    if not post:
        return await call.answer("❌ Файл не найден", show_alert=True)
    
    # Проверка подписки
    required_channels = post.get('required_channels', ['main'])
    is_subscribed, missing = await check_subscription(call.from_user.id, required_channels)
    
    if not is_subscribed:
        await call.message.answer(
            "⚠️ <b>Требуется подписка</b>\n\n"
            "Для скачивания подпишитесь на указанные каналы:",
            reply_markup=subscribe_keyboard(post_id, missing)
        )
        return await call.answer()
    
    # Увеличиваем счетчик скачиваний
    post['downloads'] = post.get('downloads', 0) + 1
    try:
        save_posts()
    except Exception as e:
        logger.error(f"Ошибка сохранения счетчика скачиваний: {e}")
    
    await send_file_to_user(call.message, post)
    await call.answer("✅ Готово!")


async def send_media_with_caption(message: Message, post: dict):
    """Отправка медиа (фото/видео/гифка) с подписью"""
    try:
        caption = f"🔥 <b>{post['title']}</b>\n\n📥 Нажмите кнопку для скачивания"
        
        if "file" in post:
            file_size_mb = post['file_size'] / (1024 * 1024)
            caption += f"\n\n📦 Файл: {post['file_name']}\n💾 Размер: {file_size_mb:.2f} МБ"
        elif "link" in post:
            caption += f"\n\n🔗 Ссылка: {post['link']}"
        
        media_id = post.get("media")
        media_type = post.get("media_type", "photo")
        
        if media_type == "video":
            await message.answer_video(media_id, caption=caption)
        elif media_type == "animation":
            await message.answer_animation(media_id, caption=caption)
        else:  # photo
            await message.answer_photo(media_id, caption=caption)
    except Exception as e:
        logger.error(f"Ошибка отправки медиа: {e}")
        await message.answer(
            "❌ Произошла ошибка при отправке медиа.\n"
            "Попробуйте позже или обратитесь к администратору."
        )


async def send_file_to_user(message: Message, post: dict):
    """Отправка файла пользователю"""
    try:
        if "file" in post:
            # Отправляем сообщение о загрузке и сохраняем его ID
            loading_msg = await message.answer(
                f"📦 <b>{post['title']}</b>\n\n"
                "⬇️ Загрузка файла..."
            )
            
            # Отправляем файл
            await message.answer_document(
                post["file"],
                caption=f"✅ <b>{post['title']}</b>\n\n💎 Спасибо за использование YAKMODS!"
            )
            
            # Удаляем сообщение о загрузке
            try:
                await loading_msg.delete()
            except:
                pass
        else:
            await message.answer(
                f"📦 <b>{post['title']}</b>\n\n"
                f"🔗 Ссылка для скачивания:\n{post['link']}\n\n"
                "💎 Спасибо за использование YAKMODS!"
            )
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
    # Игнорировать все сообщения, кроме команды /start в приватном чате.
    # Каналы и посты не должны взаимодействовать с ботом напрямую.
    try:
        if message.chat.type != "private":
            return
    except Exception:
        return

    # В приватном чате не реагируем на произвольный текст — используйте /start
    return


# =====================
# ЗАПУСК БОТА
# =====================

async def on_startup():
    """Действия при запуске бота"""
    logger.info("🚀 Бот запущен!")
    # Загружаем сохраненные посты
    try:
        load_posts()
    except Exception as e:
        logger.error(f"Ошибка при загрузке постов: {e}")
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

