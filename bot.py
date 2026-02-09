import asyncio
import uuid
import logging
import time
import os
from datetime import datetime, timedelta
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

# Получаем данные из переменных окружения

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv(“ADMIN_ID”, “0”))

# Каналы из переменных окружения

CHANNELS = {
“main”: os.getenv(“CHANNEL_MAIN”, “@YAKMODS”),
“updates”: os.getenv(“CHANNEL_UPDATES”, “@YAKMODS_UPDATES”),
“news”: os.getenv(“CHANNEL_NEWS”, “@YAKMODS_NEWS”)
}

START_IMAGE = os.getenv(“START_IMAGE”, “https://cdn.discordapp.com/attachments/1044207552512135229/1470085336360026308/5D53110C-27D1-420C-BC26-0D4F7779F784.png”)

SUGGESTION_COOLDOWN = int(os.getenv(“SUGGESTION_COOLDOWN”, “300”))
MAX_SUGGESTIONS_PER_USER = int(os.getenv(“MAX_SUGGESTIONS_PER_USER”, “3”))

# Настройка логирования

logging.basicConfig(
level=logging.INFO,
format=’%(asctime)s - %(name)s - %(levelname)s - %(message)s’
)
logger = logging.getLogger(**name**)

# =====================

# Проверка наличия обязательных переменных

if not BOT_TOKEN:
logger.error(“❌ BOT_TOKEN не установлен!”)
raise ValueError(“BOT_TOKEN обязателен для запуска бота”)

if ADMIN_ID == 0:
logger.error(“❌ ADMIN_ID не установлен!”)
raise ValueError(“ADMIN_ID обязателен для запуска бота”)

bot = Bot(
token=BOT_TOKEN,
default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# Хранилища данных

posts = {}
users = set()
banned_users = set()
suggestion_cooldowns = {}
suggestion_violations = {}

# =====================

# FSM States

# =====================

class AddPost(StatesGroup):
photo = State()
title = State()
file = State()
channels = State()
notify = State()

class Suggestion(StatesGroup):
waiting_text = State()

class ReviewSuggestion(StatesGroup):
waiting_comment = State()

# =====================

# КНОПКИ

# =====================

def main_menu():
return InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(text=“📂 Список модов”, callback_data=“mods_list”)],
[InlineKeyboardButton(text=“💡 Предложить идею”, callback_data=“suggest_idea”)],
[
InlineKeyboardButton(text=“💬 Discord”, url=“https://discord.gg/yakfamq”),
InlineKeyboardButton(text=“📢 Telegram”, url=“https://t.me/YAKMODS”)
]
])

def admin_menu():
return InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(text=“➕ Добавить пост”, callback_data=“add_post”)],
[InlineKeyboardButton(text=“📊 Статистика”, callback_data=“stats”)],
[InlineKeyboardButton(text=“📂 Список модов”, callback_data=“mods_list”)],
[InlineKeyboardButton(text=“💡 Предложить идею”, callback_data=“suggest_idea”)]
])

def channels_selection_menu():
buttons = []
for channel_key, channel_name in CHANNELS.items():
buttons.append([InlineKeyboardButton(
text=f”✅ {channel_name}”,
callback_data=f”channel_{channel_key}”
)])
buttons.append([InlineKeyboardButton(text=“✅ Продолжить”, callback_data=“channels_done”)])
buttons.append([InlineKeyboardButton(text=“❌ Отмена”, callback_data=“cancel_post”)])
return InlineKeyboardMarkup(inline_keyboard=buttons)

def notify_menu():
return InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(text=“✅ Да, уведомить всех”, callback_data=“notify_yes”)],
[InlineKeyboardButton(text=“❌ Нет, не уведомлять”, callback_data=“notify_no”)]
])

def confirm_menu():
return InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(text=“✅ Опубликовать”, callback_data=“confirm_post”)],
[InlineKeyboardButton(text=“🔄 Изменить”, callback_data=“edit_post”)],
[InlineKeyboardButton(text=“❌ Отмена”, callback_data=“cancel_post”)]
])

def subscribe_keyboard(post_id, required_channels):
buttons = []
for channel in required_channels:
channel_name = CHANNELS.get(channel, channel)
buttons.append([InlineKeyboardButton(
text=f”📢 Подписаться на {channel_name}”,
url=f”https://t.me/{channel_name[1:]}”
)])
buttons.append([InlineKeyboardButton(
text=“✅ Проверить подписку”,
callback_data=f”check_{post_id}”
)])
return InlineKeyboardMarkup(inline_keyboard=buttons)

def download_keyboard(bot_username, post_id):
return InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(
text=“⬇️ Скачать”,
url=f”https://t.me/{bot_username}?start=download_{post_id}”
)]
])

def suggestion_review_menu(suggestion_id):
return InlineKeyboardMarkup(inline_keyboard=[
[InlineKeyboardButton(text=“✅ Одобрить”, callback_data=f”approve_{suggestion_id}”)],
[InlineKeyboardButton(text=“❌ Отклонить”, callback_data=f”reject_{suggestion_id}”)]
])

# =====================

# Проверка подписки

# =====================

async def check_subscription(user_id: int, required_channels: list = None) -> tuple:
if required_channels is None:
required_channels = [“main”]

```
not_subscribed = []

for channel_key in required_channels:
    channel_id = CHANNELS.get(channel_key, CHANNELS["main"])
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        if member.status not in ["member", "creator", "administrator"]:
            not_subscribed.append(channel_key)
    except TelegramBadRequest as e:
        logger.error(f"Ошибка проверки подписки на {channel_id}: {e}")
        not_subscribed.append(channel_key)

return len(not_subscribed) == 0, not_subscribed
```

# =====================

# Вспомогательные функции

# =====================

def is_banned(user_id: int) -> bool:
return user_id in banned_users

def check_suggestion_cooldown(user_id: int) -> tuple:
if user_id in suggestion_cooldowns:
last_time = suggestion_cooldowns[user_id]
time_passed = time.time() - last_time

```
    if time_passed < SUGGESTION_COOLDOWN:
        remaining = int(SUGGESTION_COOLDOWN - time_passed)
        return False, remaining

return True, 0
```

def add_suggestion_violation(user_id: int):
if user_id not in suggestion_violations:
suggestion_violations[user_id] = 0

```
suggestion_violations[user_id] += 1

if suggestion_violations[user_id] >= MAX_SUGGESTIONS_PER_USER:
    banned_users.add(user_id)
    return True

return False
```

def is_admin(user_id: int) -> bool:
return user_id == ADMIN_ID

# =====================

# START

# =====================

@dp.message(Command(“start”))
async def start_handler(message: Message):
user_id = message.from_user.id
users.add(user_id)

```
if is_banned(user_id):
    return await message.answer(
        "🚫 <b>Вы заблокированы</b>\n\n"
        "Причина: спам предложениями\n"
        "Обратитесь к администратору для разблокировки."
    )

if len(message.text.split()) > 1:
    args = message.text.split()[1]
    if args.startswith("download_"):
        return await handle_download(message, args)

text = (
    "🔥 <b>YAKMODS</b>\n\n"
    "🔗 Discord: <a href='https://discord.gg/yakfamq'>YAKFAMQ</a>\n"
    "📢 Telegram: <a href='https://t.me/YAKMODS'>YAKMODS</a>"
)

try:
    if is_admin(user_id):
        await message.answer_photo(START_IMAGE, caption=text, reply_markup=admin_menu())
    else:
        await message.answer_photo(START_IMAGE, caption=text, reply_markup=main_menu())
except Exception as e:
    logger.error(f"Ошибка отправки стартового сообщения: {e}")
    if is_admin(user_id):
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=main_menu())
```

@dp.callback_query(F.data == “back_to_menu”)
async def back_to_menu(call: CallbackQuery):
text = (
“🔥 <b>YAKMODS</b>\n\n”
“🔗 Discord: <a href='https://discord.gg/yakfamq'>YAKFAMQ</a>\n”
“📢 Telegram: <a href='https://t.me/YAKMODS'>YAKMODS</a>”
)

```
try:
    if is_admin(call.from_user.id):
        await call.message.edit_caption(caption=text, reply_markup=admin_menu())
    else:
        await call.message.edit_caption(caption=text, reply_markup=main_menu())
except:
    if is_admin(call.from_user.id):
        await call.message.answer(text, reply_markup=admin_menu())
    else:
        await call.message.answer(text, reply_markup=main_menu())

await call.answer()
```

# =====================

# СПИСОК МОДОВ

# =====================

@dp.callback_query(F.data == “mods_list”)
async def show_mods_list(call: CallbackQuery):
if is_banned(call.from_user.id):
return await call.answer(“🚫 Вы заблокированы”, show_alert=True)

```
if not posts:
    await call.answer("📂 Пока нет доступных модов", show_alert=True)
    return

await show_mods_page(call.message, 0)
await call.answer()
```

@dp.callback_query(F.data.startswith(“page_”))
async def page_navigation(call: CallbackQuery):
if call.data == “page_info”:
return await call.answer()

```
page = int(call.data.split("_")[1])
await show_mods_page(call.message, page, edit=True)
await call.answer()
```

async def show_mods_page(message: Message, page: int, edit: bool = False):
posts_list = list(posts.items())
posts_per_page = 5
total_pages = (len(posts_list) + posts_per_page - 1) // posts_per_page

```
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
```

@dp.callback_query(F.data.startswith(“get_mod_”))
async def get_mod_details(call: CallbackQuery):
if is_banned(call.from_user.id):
return await call.answer(“🚫 Вы заблокированы”, show_alert=True)

```
post_id = call.data.replace("get_mod_", "")
post = posts.get(post_id)

if not post:
    return await call.answer("❌ Мод не найден", show_alert=True)

required_channels = post.get('required_channels', ['main'])
is_subscribed, missing = await check_subscription(call.from_user.id, required_channels)

if not is_subscribed:
    await call.message.answer(
        "⚠️ <b>Требуется подписка</b>\n\n"
        "Для скачивания этого мода подпишитесь на указанные каналы:",
        reply_markup=subscribe_keyboard(post_id, missing)
    )
    return await call.answer()

post['downloads'] = post.get('downloads', 0) + 1
await send_file_to_user(call.message, post)
await call.answer("✅ Мод отправлен!")
```

# =====================

# АДМИН: Добавление поста

# =====================

@dp.callback_query(F.data == “add_post”)
async def add_post_start(call: CallbackQuery, state: FSMContext):
if not is_admin(call.from_user.id):
return await call.answer(“❌ Доступ запрещен”, show_alert=True)

```
await state.set_state(AddPost.photo)
await call.message.answer("📸 Отправьте фото для поста")
await call.answer()
```

@dp.message(AddPost.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
photo_id = message.photo[-1].file_id
await state.update_data(photo=photo_id)
await state.set_state(AddPost.title)
await message.answer(“📝 Введите название поста:”)

@dp.message(AddPost.photo)
async def invalid_photo(message: Message):
await message.answer(“❌ Пожалуйста, отправьте фото!”)

@dp.message(AddPost.title)
async def process_title(message: Message, state: FSMContext):
if len(message.text) > 200:
return await message.answer(“❌ Название слишком длинное (макс. 200 символов)”)

```
await state.update_data(title=message.text)
await state.set_state(AddPost.file)
await message.answer(
    "📦 Отправьте файл (документ) или ссылку для скачивания:\n\n"
    "💡 Совет: Для ссылок используйте прямые ссылки на файлы"
)
```

@dp.message(AddPost.file)
async def process_file(message: Message, state: FSMContext):
data = await state.get_data()

```
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
await state.set_state(AddPost.channels)

await message.answer(
    "📢 <b>Выберите каналы для публикации:</b>\n\n"
    "Нажмите на каналы, в которые хотите опубликовать пост.\n"
    "После выбора нажмите 'Продолжить'.",
    reply_markup=channels_selection_menu()
)

await state.update_data(selected_channels=[], required_channels=['main'])
```

@dp.callback_query(F.data.startswith(“channel_”), AddPost.channels)
async def toggle_channel(call: CallbackQuery, state: FSMContext):
channel_key = call.data.replace(“channel_”, “”)
data = await state.get_data()

```
selected = data.get('selected_channels', [])
required = data.get('required_channels', ['main'])

if channel_key in selected:
    selected.remove(channel_key)
else:
    selected.append(channel_key)

if channel_key in required:
    if len(required) > 1:
        required.remove(channel_key)
else:
    required.append(channel_key)

await state.update_data(selected_channels=selected, required_channels=required)

buttons = []
for ch_key, ch_name in CHANNELS.items():
    emoji = "✅" if ch_key in selected else "☑️"
    buttons.append([InlineKeyboardButton(
        text=f"{emoji} {ch_name}",
        callback_data=f"channel_{ch_key}"
    )])
buttons.append([InlineKeyboardButton(text="✅ Продолжить", callback_data="channels_done")])
buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_post")])

kb = InlineKeyboardMarkup(inline_keyboard=buttons)

try:
    await call.message.edit_reply_markup(reply_markup=kb)
except:
    pass

await call.answer()
```

@dp.callback_query(F.data == “channels_done”, AddPost.channels)
async def channels_done(call: CallbackQuery, state: FSMContext):
data = await state.get_data()
selected = data.get(‘selected_channels’, [])

```
if not selected:
    return await call.answer("❌ Выберите хотя бы один канал!", show_alert=True)

await state.set_state(AddPost.notify)

channel_names = [CHANNELS[ch] for ch in selected]
await call.message.answer(
    f"📢 <b>Выбранные каналы:</b>\n{', '.join(channel_names)}\n\n"
    "📬 <b>Уведомить всех пользователей о новом посте?</b>",
    reply_markup=notify_menu()
)
await call.answer()
```

@dp.callback_query(F.data.startswith(“notify_”), AddPost.notify)
async def process_notify(call: CallbackQuery, state: FSMContext):
notify = call.data == “notify_yes”
await state.update_data(notify_users=notify)

```
data = await state.get_data()
post_id = str(uuid.uuid4())
data["post_id"] = post_id
data["downloads"] = 0

posts[post_id] = data
await state.update_data(**data)

bot_username = (await bot.get_me()).username
preview_kb = download_keyboard(bot_username, post_id)

caption = f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"

if "file" in data:
    file_size_mb = data['file_size'] / (1024 * 1024)
    caption += f"\n\n📦 Файл: {data['file_name']}\n💾 Размер: {file_size_mb:.2f} МБ"

selected_channels = data.get('selected_channels', [])
channel_names = [CHANNELS[ch] for ch in selected_channels]

await call.message.answer_photo(data["photo"], caption=caption, reply_markup=preview_kb)

notify_text = "✅ Да" if notify else "❌ Нет"

await call.message.answer(
    "📋 <b>Предпросмотр поста</b>\n\n"
    f"📢 Каналы: {', '.join(channel_names)}\n"
    f"📬 Уведомления: {notify_text}\n\n"
    "Проверьте все данные и выберите действие:",
    reply_markup=confirm_menu()
)

await call.answer()
```

@dp.callback_query(F.data == “confirm_post”)
async def confirm_publication(call: CallbackQuery, state: FSMContext):
if not is_admin(call.from_user.id):
return await call.answer(“❌ Доступ запрещен”, show_alert=True)

```
data = await state.get_data()
post_id = data["post_id"]

bot_username = (await bot.get_me()).username
kb = download_keyboard(bot_username, post_id)

caption = f"🔥 <b>{data['title']}</b>\n\n📥 Нажмите кнопку для скачивания"

selected_channels = data.get('selected_channels', [])
published_count = 0

for channel_key in selected_channels:
    channel_id = CHANNELS.get(channel_key)
    if channel_id:
        try:
            await bot.send_photo(channel_id, photo=data["photo"], caption=caption, reply_markup=kb)
            published_count += 1
            logger.info(f"Пост {post_id} опубликован в {channel_id}")
        except Exception as e:
            logger.error(f"Ошибка публикации в {channel_id}: {e}")

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
await call.answer()
```

async def notify_all_users(post_data, post_id):
bot_username = (await bot.get_me()).username
kb = download_keyboard(bot_username, post_id)

```
caption = f"🆕 <b>Новый мод!</b>\n\n🔥 {post_data['title']}\n\n📥 Нажмите кнопку для скачивания"

notified = 0
for user_id in users:
    if user_id != ADMIN_ID and not is_banned(user_id):
        try:
            await bot.send_photo(user_id, photo=post_data["photo"], caption=caption, reply_markup=kb)
            notified += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

return notified
```

@dp.callback_query(F.data == “edit_post”)
async def edit_post(call: CallbackQuery, state: FSMContext):
data = await state.get_data()
post_id = data.get(“post_id”)

```
if post_id and post_id in posts:
    del posts[post_id]

await state.clear()
await call.message.answer("🔄 Начните создание поста заново:", reply_markup=admin_menu())
await call.answer()
```

@dp.callback_query(F.data == “cancel_post”)
async def cancel_post(call: CallbackQuery, state: FSMContext):
data = await state.get_data()
post_id = data.get(“post_id”)

```
if post_id and post_id in posts:
    del posts[post_id]

await state.clear()
await call.message.answer("❌ Создание поста отменено", reply_markup=admin_menu())
await call.answer()
```

# =====================

# СТАТИСТИКА

# =====================

@dp.callback_query(F.data == “stats”)
async def show_stats(call: CallbackQuery):
if not is_admin(call.from_user.id):
return await call.answer(“❌ Доступ запрещен”, show_alert=True)

```
total_downloads = sum(post.get('downloads', 0) for post in posts.values())

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
```

# =====================

# ПРЕДЛОЖЕНИЯ

# =====================

@dp.callback_query(F.data == “suggest_idea”)
async def suggest_idea_start(call: CallbackQuery, state: FSMContext):
user_id = call.from_user.id

```
if is_banned(user_id):
    return await call.answer("🚫 Вы заблокированы за спам предложениями", show_alert=True)

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
```

@dp.message(Suggestion.waiting_text)
async def process_suggestion(message: Message, state: FSMContext):
user_id = message.from_user.id

```
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
    return await message.answer(f"⏳ Слишком быстро! Подождите {minutes}м {seconds}с")

suggestion_cooldowns[user_id] = time.time()
suggestion_id = str(uuid.uuid4())

user_mention = message.from_user.mention_html()
suggestion_text = (
    f"💡 <b>Новое предложение #{suggestion_id[:8]}</b>\n\n"
    f"👤 От: {user_mention} (ID: {user_id})\n"
    f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    f"📝 <b>Текст:</b>\n{message.text or message.caption or 'Нет текста'}"
)

try:
    if message.photo:
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=suggestion_text,
            reply_markup=suggestion_review_menu(suggestion_id)
        )
    else:
        await bot.send_message(
            ADMIN_ID,
            text=suggestion_text,
            reply_markup=suggestion_review_menu(suggestion_id)
        )
    
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
    
    logger.info(f"Предложение {suggestion_id} от пользователя {user_id}")
    
except Exception as e:
    logger.error(f"Ошибка отправки предложения: {e}")
    await message.answer("❌ Ошибка отправки. Попробуйте позже.")

await state.clear()
```

@dp.callback_query(F.data.startswith(“approve_”))
async def approve_suggestion(call: CallbackQuery, state: FSMContext):
suggestion_id = call.data.replace(“approve_”, “”)

```
await state.update_data(
    suggestion_id=suggestion_id,
    action="approve",
    original_message_id=call.message.message_id
)
await state.set_state(ReviewSuggestion.waiting_comment)

await call.message.answer("✅ <b>Одобрение предложения</b>\n\nНапишите комментарий для пользователя:")
await call.answer()
```

@dp.callback_query(F.data.startswith(“reject_”))
async def reject_suggestion(call: CallbackQuery, state: FSMContext):
suggestion_id = call.data.replace(“reject_”, “”)

```
await state.update_data(
    suggestion_id=suggestion_id,
    action="reject",
    original_message_id=call.message.message_id
)
await state.set_state(ReviewSuggestion.waiting_comment)

await call.message.answer("❌ <b>Отклонение предложения</b>\n\nНапишите комментарий для пользователя:")
await call.answer()
```

@dp.message(ReviewSuggestion.waiting_comment)
async def process_review_comment(message: Message, state: FSMContext):
data = await state.get_data()
suggestion_id = data[‘suggestion_id’]
action = data[‘action’]
comment = message.text

```
try:
    original_msg = await bot.edit_message_reply_markup(
        chat_id=ADMIN_ID,
        message_id=data['original_message_id'],
        reply_markup=None
    )
    
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
    
    await bot.send_message(user_id, result_text)
    await message.answer(admin_text, reply_markup=admin_menu())
    
    logger.info(f"Предложение {suggestion_id} {action} администратором")
    
except Exception as e:
    logger.error(f"Ошибка обработки решения: {e}")
    await message.answer("❌ Ошибка отправки ответа пользователю")

await state.clear()
```

# =====================

# СКАЧИВАНИЕ

# =====================

async def handle_download(message: Message, args: str):
if is_banned(message.from_user.id):
return await message.answer(“🚫 Вы заблокированы”)

```
post_id = args.replace("download_", "")
post = posts.get(post_id)

if not post:
    return await message.answer(
        "❌ <b>Файл не найден</b>\n\n"
        "Возможно, пост был удален или ссылка устарела."
    )

required_channels = post.get('required_channels', ['main'])
is_subscribed, missing = await check_subscription(message.from_user.id, required_channels)

if not is_subscribed:
    return await message.answer(
        "⚠️ <b>Требуется подписка</b>\n\n"
        "Для скачивания подпишитесь на указанные каналы:",
        reply_markup=subscribe_keyboard(post_id, missing)
    )

post['downloads'] = post.get('downloads', 0) + 1
await send_file_to_user(message, post)
```

@dp.callback_query(F.data.startswith(“check_”))
async def recheck_subscription(call: CallbackQuery):
if is_banned(call.from_user.id):
return await call.answer(“🚫 Вы заблокированы”, show_alert=True)

```
post_id = call.data.replace("check_", "")
post = posts.get(post_id)

if not post:
    return await call.answer("❌ Файл не найден", show_alert=True)

required_channels = post.get('required_channels', ['main'])
is_subscribed, missing = await check_subscription(call.from_user.id, required_channels)

if is_subscribed:
    post['downloads'] = post.get('downloads', 0) + 1
    await send_file_to_user(call.message, post)
    await call.answer("✅ Подписка подтверждена!")
else:
    await call.answer(
        "❌ Вы еще не подписаны на все требуемые каналы!\n"
        "Подпишитесь и нажмите кнопку еще раз.",
        show_alert=True
    )
```

async def send_file_to_user(message: Message, post: dict):
try:
if “file” in post:
await message.answer(f”📦 <b>{post[‘title’]}</b>\n\n⬇️ Загрузка файла…”)
await message.answer_document(
post[“file”],
caption=f”✅ <b>{post[‘title’]}</b>\n\n💎 Спасибо за использование YAKMODS!”
)
logger.info(f”Файл отправлен пользователю {message.from_user.id}”)
else:
await message.answer(
f”📦 <b>{post[‘title’]}</b>\n\n”
f”🔗 Ссылка для скачивания:\n{post[‘link’]}\n\n”
“💎 Спасибо за использование YAKMODS!”
)
logger.info(f”Ссылка отправлена пользователю {message.from_user.id}”)
except Exception as e:
logger.error(f”Ошибка отправки файла: {e}”)
await message.answer(
“❌ Произошла ошибка при отправке файла.\n”
“Попробуйте позже или обратитесь к администратору.”
)

# =====================

# ОБРАБОТКА ОШИБОК

# =====================

@dp.message()
async def unknown_message(message: Message):
if is_banned(message.from_user.id):
return await message.answer(“🚫 Вы заблокированы”)

```
if is_admin(message.from_user.id):
    await message.answer("ℹ️ Используйте команду /start для доступа к меню", reply_markup=admin_menu())
else:
    await message.answer(
        "ℹ️ Используйте команду /start\n\n💎 YAKMODS - лучшие моды для ваших игр!",
        reply_markup=main_menu()
    )
```

# =====================

# ЗАПУСК БОТА

# =====================

async def on_startup():
logger.info(“🚀 Бот запущен!”)
try:
bot_info = await bot.get_me()
logger.info(f”Бот @{bot_info.username} готов к работе”)
logger.info(f”Admin ID: {ADMIN_ID}”)
except Exception as e:
logger.error(f”Ошибка при запуске: {e}”)

async def on_shutdown():
logger.info(“⛔️ Бот остановлен!”)

async def main():
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

```
try:
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
except Exception as e:
    logger.error(f"Критическая ошибка: {e}")
finally:
    await bot.session.close()
```

if **name** == “**main**”:
try:
asyncio.run(main())
except KeyboardInterrupt:
logger.info(“Бот остановлен пользователем”)