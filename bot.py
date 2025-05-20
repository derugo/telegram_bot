import logging
from datetime import datetime
import random
import string
import yadisk
import os
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токены и пароль
BOT_TOKEN = "7991720922:AAHPQkyL69IR__tJs8btNOrh67M48iNFugQ"
YANDEX_TOKEN = "y0__xCr4L-ZBBjblgMgje-YlhOWdzLSVzL4yFbDo18R9G3OJVchXA"
ADMIN_PASSWORD = "vasiliy.derugo"

# Хранилища
tasks = {}
user_roles = {}
storage = None

# Словарь для читаемых названий полей
readable = {
    "loading_date": "Дата загрузки",
    "departure": "Пункт отправления",
    "destination": "Пункт назначения",
    "route": "Маршрут",
    "customs_departure": "Таможня отправления",
    "customs_destination": "Таможня назначения",
    "cargo_type": "Характер груза",
    "sender_contact": "Контакты отправителя",
    "driver_rate": "Ставка для водителя",
    "client_rate": "Ставка для клиента",
    "additional_info": "Доп. информация"
}


class YandexDiskStorage:
    def __init__(self):
        self.disk = yadisk.YaDisk(token=YANDEX_TOKEN)
        self.ensure_folder_structure()

    def ensure_folder_structure(self):
        try:
            if not self.disk.exists('/Заказы'):
                self.disk.mkdir('/Заказы')
        except Exception as e:
            logging.error(f"Ошибка при создании базовой структуры: {e}")
            raise

    def create_folder_if_not_exists(self, path):
        """Рекурсивно создаёт папки по указанному пути"""
        try:
            if not self.disk.exists(path):
                parent_path = os.path.dirname(path)
                if parent_path and parent_path != '/':
                    self.create_folder_if_not_exists(parent_path)
                self.disk.mkdir(path)
                logging.info(f"Создана директория: {path}")
        except Exception as e:
            logging.error(f"Ошибка при создании директории {path}: {e}")
            raise

    def get_client_id_for_task(self, task_id):
        """Получаем ID клиента для данного заказа"""
        for tid, task_data in tasks.items():
            if (task_data["data"] == tasks[task_id]["data"] and
                    task_data["role"] == "client"):
                return tid
        return task_id

    def save_file(self, file_path: str, task_id: str, file_type: str) -> str:
        try:
            # Получаем ID клиента для организации папок
            client_id = self.get_client_id_for_task(task_id)

            filename = os.path.basename(file_path)

            # Формируем пути для папок
            order_folder = f'/Заказы/{client_id}'
            type_folder = f'{order_folder}/{"Фото груза" if file_type == "photos" else "Документы"}'

            # Создаём структуру папок
            self.create_folder_if_not_exists(order_folder)
            self.create_folder_if_not_exists(type_folder)

            # Формируем путь для файла
            yandex_path = f'{type_folder}/{filename}'

            # Загружаем файл
            self.disk.upload(file_path, yandex_path, overwrite=True)

            logging.info(f"Файл {filename} успешно загружен в {yandex_path}")
            return yandex_path

        except Exception as e:
            logging.error(f"Ошибка при сохранении файла на Яндекс.Диск: {e}")
            raise


def generate_random_id(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_task_id(role):
    date = datetime.now().strftime("%d%m%Y")
    return f"{date}-{generate_random_id(4)}-{role[:3]}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Клиент", "Водитель"], ["Диспетчер"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("👋 Добро пожаловать! Выберите вашу роль:", reply_markup=reply_markup)
    context.user_data["stage"] = "role_selection"


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "upload_photo":
        context.user_data["upload_type"] = "photo"
        await query.message.reply_text("📸 Пожалуйста, отправьте фотографию груза")
        context.user_data["stage"] = "waiting_for_photo"
    elif query.data == "upload_docs":
        context.user_data["upload_type"] = "document"
        await query.message.reply_text("📄 Пожалуйста, отправьте документ")
        context.user_data["stage"] = "waiting_for_document"


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("stage") != "waiting_for_photo":
        return

    task_id = context.user_data.get("current_task")
    if not task_id or task_id not in tasks:
        await update.message.reply_text("❌ Ошибка: задание не найдено")
        return

    try:
        photo = update.message.photo[-1]
        file_id = photo.file_id

        # Скачиваем файл
        photo_file = await photo.get_file()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        os.makedirs("temp", exist_ok=True)
        file_path = os.path.join("temp", filename)
        await photo_file.download_to_drive(file_path)

        # Сохраняем на Яндекс.Диск
        yandex_path = storage.save_file(file_path, task_id, "photos")
        os.remove(file_path)  # Удаляем временный файл

        # Найдем связанный ID клиента
        client_id = None
        for tid, task_data in tasks.items():
            if (task_data["data"] == tasks[task_id]["data"] and
                    task_data["role"] == "client"):
                client_id = tid
                break

        # Сохраняем информацию о фото
        for save_id in [task_id, client_id]:
            if save_id:
                task = tasks[save_id]
                if "media" not in task:
                    task["media"] = {}
                if "photos" not in task["media"]:
                    task["media"]["photos"] = []
                task["media"]["photos"].append(file_id)
                if "yandex_paths" not in task["media"]:
                    task["media"]["yandex_paths"] = []
                task["media"]["yandex_paths"].append(yandex_path)

        await update.message.reply_text("✅ Фотография успешно загружена!")

        keyboard = [
            [InlineKeyboardButton("📸 Загрузить еще фото", callback_data="upload_photo"),
             InlineKeyboardButton("📄 Загрузить документы", callback_data="upload_docs")]
        ]
        await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logging.error(f"Ошибка при обработке фото: {e}")
        await update.message.reply_text("❌ Произошла ошибка при сохранении фото")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("stage") != "waiting_for_document":
        return

    task_id = context.user_data.get("current_task")
    if not task_id or task_id not in tasks:
        await update.message.reply_text("❌ Ошибка: задание не найдено")
        return

    try:
        document = update.message.document
        file_id = document.file_id
        doc_info = {"file_id": file_id, "name": document.file_name}

        # Скачиваем документ
        doc_file = await document.get_file()
        filename = document.file_name
        os.makedirs("temp", exist_ok=True)
        file_path = os.path.join("temp", filename)
        await doc_file.download_to_drive(file_path)

        # Сохраняем на Яндекс.Диск
        yandex_path = storage.save_file(file_path, task_id, "documents")
        os.remove(file_path)  # Удаляем временный файл

        # Найдем связанный ID клиента
        client_id = None
        for tid, task_data in tasks.items():
            if (task_data["data"] == tasks[task_id]["data"] and
                    task_data["role"] == "client"):
                client_id = tid
                break

        # Сохраняем информацию о документе
        for save_id in [task_id, client_id]:
            if save_id:
                task = tasks[save_id]
                if "media" not in task:
                    task["media"] = {}
                if "documents" not in task["media"]:
                    task["media"]["documents"] = []
                task["media"]["documents"].append(doc_info)
                if "yandex_paths" not in task["media"]:
                    task["media"]["yandex_paths"] = []
                task["media"]["yandex_paths"].append(yandex_path)

        await update.message.reply_text("✅ Документ успешно загружен!")

        keyboard = [
            [InlineKeyboardButton("📸 Загрузить фото", callback_data="upload_photo"),
             InlineKeyboardButton("📄 Загрузить еще документы", callback_data="upload_docs")]
        ]
        await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logging.error(f"Ошибка при обработке документа: {e}")
        await update.message.reply_text("❌ Произошла ошибка при сохранении документа")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    stage = context.user_data.get("stage")

    if stage == "role_selection":
        role = text.lower()
        if role not in ["клиент", "водитель", "диспетчер"]:
            await update.message.reply_text("❌ Неверный выбор роли!")
            return

        if role == "диспетчер":
            await update.message.reply_text("🔒 Введите пароль диспетчера:", reply_markup=ReplyKeyboardRemove())
            context.user_data["stage"] = "dispatcher_auth"
            return

        user_roles[user.id] = role
        context.user_data["stage"] = f"{role}_id_input"
        await update.message.reply_text(
            f"📥 Введите ID {'груза' if role == 'клиент' else 'задания'}:", reply_markup=ReplyKeyboardRemove()
        )

    elif stage == "dispatcher_auth":
        if text == ADMIN_PASSWORD:
            user_roles[user.id] = "диспетчер"
            context.user_data["stage"] = "dispatcher_action_choice"
            keyboard = [["Создать заказ", "Посмотреть историю"]]
            await update.message.reply_text("Выберите действие:",
                                            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True,
                                                                             one_time_keyboard=True))
        else:
            await update.message.reply_text("❌ Неверный пароль!")
            context.user_data.clear()

    elif stage == "dispatcher_action_choice":
        if text.lower() == "создать заказ":
            context.user_data["task_data"] = {}
            context.user_data["stage"] = "dispatcher_create_task"
            await update.message.reply_text("📅 Введите дату загрузки (ДД.ММ.ГГГГ):")
        elif text.lower() == "посмотреть историю":
            context.user_data["stage"] = "dispatcher_view_history"
            await update.message.reply_text("🔎 Введите ID водителя или клиента для просмотра:")

    elif stage == "dispatcher_create_task":
        task_data = context.user_data.get("task_data", {})
        steps = [
            ("loading_date", "📍 Пункт отправления:"),
            ("departure", "🏁 Пункт назначения:"),
            ("destination", "🗺️ Маршрут:"),
            ("route", "🛂 Таможня отправления:"),
            ("customs_departure", "🛂 Таможня назначения:"),
            ("customs_destination", "📦 Характер груза:"),
            ("cargo_type", "📞 Контакты отправителя:"),
            ("sender_contact", "💰 Ставка для водителя:"),
            ("driver_rate", "💰 Ставка для клиента:"),
            ("client_rate", "ℹ️ Доп. информация:")
        ]

        current_step = next((s for s in steps if s[0] not in task_data), None)
        if current_step:
            task_data[current_step[0]] = text
            context.user_data["task_data"] = task_data
            await update.message.reply_text(current_step[1])
            return

        driver_id = generate_task_id("driver")
        client_id = generate_task_id("client")

        tasks[driver_id] = {"data": task_data, "media": {}, "role": "driver"}
        tasks[client_id] = {"data": task_data, "media": {}, "role": "client"}

        await update.message.reply_text(
            f"✅ Задание создано!\n🚚 ID для водителя: {driver_id}\n📦 ID для клиента: {client_id}")
        context.user_data.clear()

    elif stage == "водитель_id_input":
        task = tasks.get(text)
        if task and task["role"] == "driver":
            context.user_data["current_task"] = text
            context.user_data["stage"] = "driver_main_menu"
            task_info = task["data"]
            response = [f"📦 Информация по заданию {text}:"]
            for k, v in task_info.items():
                if k in readable and k != "client_rate":  # Пропускаем ставку клиента
                    if k == "driver_rate":
                        response.append(f"• Ставка: {v}")  # Показываем просто как "Ставка"
                    else:
                        response.append(f"• {readable[k]}: {v}")
            await update.message.reply_text("\n".join(response))

            keyboard = [[InlineKeyboardButton("📸 Фото груза", callback_data="upload_photo"),
                         InlineKeyboardButton("📄 Документы", callback_data="upload_docs")]]
            await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("❌ Неверный ID задания!")

    elif stage == "клиент_id_input":
        task = tasks.get(text)
        if task and task["role"] == "client":
            response = [f"📦 Информация по грузу {text}:"]
            for k, v in task["data"].items():
                if k in readable and k != "driver_rate":  # Пропускаем ставку водителя
                    if k == "client_rate":
                        response.append(f"• Ставка: {v}")  # Показываем просто как "Ставка"
                    else:
                        response.append(f"• {readable[k]}: {v}")

            media_info = []
            sent_photos = set()
            if "media" in task:
                if "photos" in task["media"]:
                    photos = task["media"]["photos"]
                    unique_photos = []
                    for photo_id in photos:
                        if photo_id not in sent_photos:
                            sent_photos.add(photo_id)
                            unique_photos.append(photo_id)

                    if unique_photos:
                        media_info.append(f"📸 Количество фото: {len(unique_photos)}")
                        for file_id in unique_photos:
                            await update.message.reply_photo(file_id)

                if "documents" in task["media"]:
                    media_info.append(f"📄 Документы:")
                    for doc in task["media"]["documents"]:
                        await update.message.reply_document(doc["file_id"])
                        media_info.append(f"  • {doc['name']}")

            if media_info:
                response.append("\n📎 Прикрепленные материалы:")
                response.extend(media_info)

            await update.message.reply_text("\n".join(response))
        else:
            await update.message.reply_text("❌ Неверный ID груза!")

    elif stage == "dispatcher_view_history":
        task = tasks.get(text)
        if task:
            response = [f"📦 Информация по ID {text}:"]
            for key, value in task["data"].items():
                response.append(f"• {readable.get(key, key)}: {value}")

            if "media" in task:
                if "photos" in task["media"] and task["media"]["photos"]:
                    response.append("\n📸 Фотографии:")
                    for photo_id in task["media"]["photos"]:
                        await update.message.reply_photo(photo_id)

                if "documents" in task["media"] and task["media"]["documents"]:
                    response.append("\n📄 Документы:")
                    for doc in task["media"]["documents"]:
                        await update.message.reply_document(doc["file_id"])
                        response.append(f"  • {doc['name']}")

            await update.message.reply_text("\n".join(response))
        else:
            await update.message.reply_text("❌ Задание не найдено по этому ID")
        context.user_data.clear()


def main():
    global storage
    storage = YandexDiskStorage()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()