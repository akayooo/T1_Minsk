import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv
import asyncio
from aiokafka import AIOKafkaConsumer
import json
from pydantic import BaseModel
from io import BytesIO
import aiohttp

# load_dotenv()


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BACKEND_API_URL = os.getenv('BACKEND_API_URL', 'http://localhost:8000')


FIRST_NAME, LAST_NAME = range(2)



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start"""
    user = update.effective_user
    
    await update.message.reply_sticker(
        sticker="CAACAgIAAxkBAAEBprlo5S4Z72R3bqHtDNCeYYwR9hRFgQACvAwAAocoMEntN5GZWCFoBDYE"
    )
    
    await update.message.chat.send_action("typing")
    
    await update.message.reply_text(
        f"Добрый день, {user.first_name}!\n\n"
        f"Я виртуальный помощник для регистрации обращений в службу технической поддержки. "
        f"Чтобы создать для вас учетную запись, мне потребуется некоторая информация.\n\n"
        f"Доступные команды:\n"
        f"/start - Регистрация в системе\n"
        f"/ticket - Создать новое обращение\n"
        f"/exit - Закрыть обращение и оценить работу\n"
        f"/cancel - Отменить текущее действие"
    )
    
    await update.message.chat.send_action("typing")
    
    await update.message.reply_text(
        "Пожалуйста, введите ваше имя:"
    )
    
    return FIRST_NAME



async def receive_first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает имя пользователя"""
    first_name = update.message.text.strip()
    
    if not first_name:
        await update.message.reply_text("Имя не может быть пустым. Попробуйте снова:")
        return FIRST_NAME
    
    context.user_data['first_name'] = first_name
    
    await update.message.chat.send_action("typing")
    
    await update.message.reply_text(
        f"Отлично, {first_name}!\n\n"
        f"Теперь введите вашу фамилию:"
    )
    
    return LAST_NAME



async def receive_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает фамилию и отправляет данные на backend"""
    last_name = update.message.text.strip()
    
    if not last_name:
        await update.message.reply_text("Фамилия не может быть пустой. Попробуйте снова:")
        return LAST_NAME
    
    user = update.effective_user
    first_name = context.user_data.get('first_name')
    
    await update.message.chat.send_action("typing")
    
    user_data = {
        "telegram_user_id": user.id,
        "telegram_chat_id": update.effective_chat.id,
        "first_name": first_name,
        "last_name": last_name,
        "username": user.username or ""
    }
    
    try:
        response = requests.post(
            f"{BACKEND_API_URL}/api/v1/telegram-auth/register",
            json=user_data,
            timeout=10
        )
        
        if response.status_code == 200:
            await update.message.reply_text(
                f"Регистрация успешно завершена!\n\n"
                f"Теперь вы можете пользоваться системой техподдержки!\n\n"
                f"Просто напишите ваш вопрос или проблему, и тикет будет создан автоматически.\n"
                f"Для завершения обращения используйте /exit"
            )
            logger.info(f"Пользователь {user.id} успешно зарегистрирован")
        else:
            await update.message.reply_text(
                f"Ошибка при регистрации.\n"
                f"Попробуйте позже или обратитесь к администратору."
            )
            logger.error(f"Ошибка регистрации: {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(
            f"Не удалось связаться с сервером.\n"
            f"Проверьте подключение и попробуйте снова позже."
        )
        logger.error(f"Ошибка соединения с backend: {e}")
    
    return ConversationHandler.END



async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет регистрацию"""
    await update.message.reply_text(
        "Регистрация отменена.\n"
        "Чтобы начать заново, используйте команду /start"
    )
    return ConversationHandler.END



async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает обычные сообщения (текст и фото)"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if user.is_bot:
        logger.info(f"Игнорируем сообщение от бота: {user.id}")
        return
    
    # Проверяем наличие активного тикета через API бэкенда
    has_active_ticket = False
    try:
        check_response = requests.get(
            f"{BACKEND_API_URL}/api/v1/chat/check_active/{chat_id}",
            timeout=5
        )
        if check_response.status_code == 200:
            data = check_response.json()
            has_active_ticket = data.get('has_active_chat', False)
            logger.info(f"Проверка активного тикета для {chat_id}: {has_active_ticket}")
    except Exception as e:
        logger.error(f"Ошибка проверки активного тикета: {e}")
        # В случае ошибки проверяем локальный флаг
        has_active_ticket = context.user_data.get('has_active_ticket', False)
    
    # Если нет активного тикета, создаем его автоматически с первым сообщением
    if not has_active_ticket:
        text = update.message.caption if update.message.photo else update.message.text
        
        if not text:
            text = "Фото без описания"
        
        await update.message.chat.send_action("typing")
        
        # Создаем тикет с первым сообщением
        chat_data = {
            "telegram_chat_id": chat_id,
            "user_id": str(user.id),
            "first_message": text
        }
        
        try:
            response = requests.post(
                f"{BACKEND_API_URL}/api/v1/chat/create",
                json=chat_data,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                context.user_data['has_active_ticket'] = True
                context.user_data['telegram_chat_id'] = chat_id
                context.user_data['first_message_sent'] = True
                
                await update.message.reply_text(
                    "Тикет создан!\n\n"
                    "Ваше обращение принято.\n"
                    "Оператор ответит вам в ближайшее время.\n\n"
                    "Вы можете продолжить отправлять сообщения и фотографии.\n"
                    "Для завершения обращения используйте /exit"
                )
                logger.info(f"Создан тикет для пользователя {user.id} с первым сообщением")
                
                # ВАЖНО: Не отправляем фото отдельно, оно уже в первом сообщении!
                # Просто возвращаемся, тикет создан
                return
            else:
                await update.message.reply_text(
                    "Ошибка при создании тикета.\n"
                    "Попробуйте позже."
                )
                logger.error(f"Ошибка создания тикета: {response.status_code}")
                return
                
        except requests.exceptions.RequestException as e:
            await update.message.reply_text(
                "Не удалось связаться с сервером.\n"
                "Попробуйте позже."
            )
            logger.error(f"Ошибка соединения при создании тикета: {e}")
            return
    
    # Если тикет уже есть, отправляем сообщение как обычно
    telegram_chat_id = context.user_data.get('telegram_chat_id')
    text = update.message.caption if update.message.photo else update.message.text
    
    if not text:
        text = "Фото"
    
    try:
        files = {}
        data = {
            'telegram_chat_id': telegram_chat_id,
            'text': text
        }
        
        if update.message.photo:
            photo = update.message.photo[-1] 
            photo_file = await photo.get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            
            files['photo'] = ('photo.jpg', photo_bytes, 'image/jpeg')
        
        response = requests.post(
            f"{BACKEND_API_URL}/api/v1/tickets/add_message",
            data=data,
            files=files if files else None,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Сообщение от {user.id} отправлено")
        else:
            await update.message.reply_text(
                "Ошибка при отправке сообщения.\n"
                "Попробуйте еще раз."
            )
            logger.error(f"Ошибка отправки сообщения: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(
            "Не удалось отправить сообщение.\n"
            "Попробуйте позже."
        )
        logger.error(f"Ошибка при отправке сообщения: {e}")



async def exit_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс закрытия тикета"""
    if not context.user_data.get('has_active_ticket'):
        await update.message.reply_text(
            "У вас нет активного тикета."
        )
        return ConversationHandler.END
    
    await update.message.chat.send_action("typing")
    
    # Создаем inline кнопки для оценки
    keyboard = [
        [InlineKeyboardButton("1", callback_data="rating_1")],
        [InlineKeyboardButton("2", callback_data="rating_2")],
        [InlineKeyboardButton("3", callback_data="rating_3")],
        [InlineKeyboardButton("4", callback_data="rating_4")],
        [InlineKeyboardButton("5", callback_data="rating_5")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Спасибо за обращение!\n\n"
        "Пожалуйста, оцените работу оператора:",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие на inline кнопку с рейтингом"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем рейтинг из callback_data
    rating = int(query.data.split('_')[1])
    
    user = query.from_user
    
    try:
        close_data = CloseChatRequest(rating=rating, comment=f"Оценка от пользователя {user.id}")
        response = requests.post(
            f"{BACKEND_API_URL}/api/v1/chat/close/{user.id}",
            headers={"Content-Type": "application/json"},
            json=close_data.model_dump(),
            timeout=10
        )
        
        if response.status_code == 200:
            context.user_data['has_active_ticket'] = False
            context.user_data['telegram_chat_id'] = None
            context.user_data['first_message_sent'] = False  
            
            # Формируем звездочки для отображения
            stars = '⭐' * rating
            await query.edit_message_text(
                f"Спасибо за оценку {rating}/5! {stars}\n\n"
                f"Ваш тикет закрыт.\n"
                f"Для создания нового обращения используйте /ticket"
            )
            logger.info(f"Тикет пользователя {user.id} закрыт с оценкой {rating}")
        else:
            stars = '⭐' * rating
            await query.edit_message_text(
                f"Спасибо за оценку {rating}/5! {stars}\n\n"
                f"Тикет закрыт локально.\n"
                f"Для создания нового обращения используйте /ticket"
            )
            context.user_data['has_active_ticket'] = False
            context.user_data['telegram_chat_id'] = None
            context.user_data['first_message_sent'] = False  
            logger.warning(f"Не удалось закрыть тикет на сервере: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        stars = '⭐' * rating
        await query.edit_message_text(
            f"Спасибо за оценку {rating}/5! {stars}\n\n"
            f"Тикет закрыт.\n"
            f"Для создания нового обращения используйте /ticket"
        )
        context.user_data['has_active_ticket'] = False
        context.user_data['telegram_chat_id'] = None
        context.user_data['first_message_sent'] = False  
        logger.error(f"Ошибка при закрытии тикета: {e}")

class CloseChatRequest(BaseModel):
    rating: int
    comment: str | None = None



KAFKA_URL = os.getenv('KAFKA_URL', 'localhost:9092')
KAFKA_TOPIC = os.getenv('KAFKA_OPERATOR_REPLIES_TOPIC', 'operator_replies')


async def kafka_consumer_task(application: Application):
    """Фоновая задача, которая слушает Kafka и отправляет сообщения в Telegram."""
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_URL,
        group_id="telegram-bot-group", 
        auto_offset_reset='earliest',
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    await consumer.start()
    logger.info(f"Kafka Consumer запущен и слушает топик '{KAFKA_TOPIC}'")
    try:
        async for msg in consumer:
            try:
                logger.info(f"Получено сырое сообщение из Kafka: {msg}")
                message_data = msg.value
                chat_id = message_data.get("telegram_chat_id")
                message_text = message_data.get("message")
                photo_url = message_data.get("photo")


                if not chat_id or not message_text:
                    logger.warning(f"Получено неполное сообщение из Kafka: {message_data}")
                    continue
                
                logger.info(f"Получено сообщение от оператора для чата {chat_id} из Kafka")


                # Используем application.bot для отправки сообщения
                if photo_url:
                    # Скачиваем изображение и отправляем как файл
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(photo_url) as response:
                                if response.status == 200:
                                    photo_bytes = await response.read()
                                    photo_file = BytesIO(photo_bytes)
                                    photo_file.name = 'photo.jpg'
                                    
                                    await application.bot.send_photo(
                                        chat_id=chat_id, 
                                        photo=photo_file, 
                                        caption=message_text
                                    )
                                    logger.info(f"Фото успешно отправлено в чат {chat_id}")
                                else:
                                    logger.warning(f"Не удалось скачать фото: {photo_url}, статус: {response.status}")
                                    await application.bot.send_message(chat_id=chat_id, text=message_text)
                    except Exception as e:
                        logger.error(f"Ошибка при скачивании фото {photo_url}: {e}")
                        await application.bot.send_message(chat_id=chat_id, text=message_text)
                else:
                    await application.bot.send_message(chat_id=chat_id, text=message_text)
                
                logger.info(f"Сообщение успешно доставлено в чат {chat_id}")


            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения из Kafka: {e}")


    finally:
        await consumer.stop()
        logger.info("Kafka Consumer остановлен.")



async def post_init(application: Application):
    """
    Эта функция будет вызвана после инициализации Application.
    Идеальное место для запуска фоновых задач.
    """
    asyncio.create_task(kafka_consumer_task(application))



def main():
    """Запускает бота и все фоновые задачи."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не установлен в .env файле!")
        return

    application_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    application_builder.post_init(post_init)
    application = application_builder.build()
    
    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_first_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_last_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(registration_handler)
    application.add_handler(CommandHandler("exit", exit_ticket))
    application.add_handler(CallbackQueryHandler(handle_rating_callback, pattern="^rating_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    
    logger.info("Бот запущен и готов к работе!")
    logger.info(f"Backend API: {BACKEND_API_URL}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main() 