from openai import OpenAI
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Получаем API ключ и выбираем провайдера
# api_key = os.getenv("OPENROUTER_API_KEY", "")
api_key = os.getenv("SCIBOX_API_KEY", "")  # для SciBox 


class LLMClient:
    """Клиент для работы с LLM API (OpenRouter или SciBox)"""
    
    def __init__(self, api_key: str):
        self.client = OpenAI(
            api_key=api_key,
            # base_url="https://openrouter.ai/api/v1"
            base_url="https://llm.t1v.scibox.tech/v1"  # для SciBox
            
        )
        # self.model = "qwen/qwen-2.5-72b-instruct"
        self.model = "Qwen2.5-72B-Instruct-AWQ" # для SciBox
        logger.info("Инициализирован LLM клиент")
    
    def get_completion(self, messages: list, temperature: float = 0.3, max_tokens: int = 100) -> str:
        """
        Получить ответ от LLM
        
        Args:
            messages: Список сообщений для чата
            temperature: Температура генерации (0-1)
            max_tokens: Максимальное количество токенов
            
        Returns:
            Текст ответа от модели
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                top_p=0.9,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"Ошибка при обращении к LLM: {str(e)}")


class TitleGenerator:
    """Генератор названий для обращений в техподдержку"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
    
    def generate_title(self, first_message: str) -> str:
        """
        Генерирует краткое название обращения на основе первого сообщения
        
        Args:
            first_message: Первое сообщение пользователя
            
        Returns:
            Название обращения (максимум 50 символов)
        """
        
        system_prompt = """Ты - эксперт по созданию кратких и информативных названий для обращений в службу техподдержки.

Твоя задача: создать короткое название (максимум 50 символов) для обращения на основе первого сообщения пользователя.

Требования к названию:
- Максимум 50 символов
- Отражает суть проблемы или вопроса
- Понятное и конкретное
- На русском языке
- Без кавычек и лишних символов

Примеры:
- "Не могу войти в аккаунт" → "Проблема со входом в аккаунт"
- "Как оплатить заказ картой?" → "Вопрос по оплате картой"
- "Заказ не пришел уже неделю" → "Задержка доставки заказа"
- "Здравствуйте, у меня сломался телефон после обновления" → "Неисправность после обновления"
- "Хочу оформить карту MORE" → "Оформление карты MORE"
- "Какие документы нужны для кредита?" → "Документы для кредита"

ВАЖНО: Верни ТОЛЬКО название, без дополнительного текста, кавычек или объяснений."""

        user_prompt = f"Первое сообщение пользователя:\n\n{first_message}\n\nНазвание обращения:"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            title = self.llm_client.get_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=100
            )
            
            # Очистка и ограничение длины
            title = title.strip()
            title = title.replace('"', '').replace("'", '').replace('«', '').replace('»', '')
            
            if len(title) > 50:
                title = title[:47] + "..."
            
            if not title or len(title) < 3:
                logger.warning(f"Сгенерировано некорректное название: '{title}'")
                return "Новое обращение"
            
            logger.info(f"Сгенерировано название: '{title}'")
            return title
            
        except Exception as e:
            logger.error(f"Ошибка при генерации названия: {e}", exc_info=True)
            return "Новое обращение"


# Глобальная инициализация клиента и генератора
_llm_client = None
_title_generator = None


def init_generator():
    """Инициализация генератора названий"""
    global _llm_client, _title_generator
    
    if not api_key:
        logger.error("API ключ не установлен. Проверьте переменную окружения")
        return False
    
    try:
        _llm_client = LLMClient(api_key=api_key)
        _title_generator = TitleGenerator(llm_client=_llm_client)
        logger.info("Генератор названий успешно инициализирован")
        return True
    except Exception as e:
        logger.error(f"Ошибка инициализации генератора: {e}", exc_info=True)
        return False


async def generate_chat_title(first_message: str) -> str:
    """
    Асинхронная обертка для генерации названия чата
    
    Args:
        first_message: Первое сообщение пользователя
        
    Returns:
        Сгенерированное название чата
    """
    global _title_generator
    
    # Ленивая инициализация при первом вызове
    if _title_generator is None:
        if not init_generator():
            return "Новое обращение"
    
    try:
        # Синхронный вызов в асинхронной функции
        # В будущем можно использовать run_in_executor для истинной асинхронности
        title = _title_generator.generate_title(first_message)
        return title
    except Exception as e:
        logger.error(f"Ошибка при генерации названия: {e}", exc_info=True)
        return "Новое обращение"


# Для тестирования
if __name__ == "__main__":
    import asyncio
    
    async def test():
        test_messages = [
            "Здравствуйте! Не могу войти в личный кабинет, пишет неверный пароль",
            "Хочу оформить кредит на покупку автомобиля. Какие условия?",
            "У меня заблокировалась карта после покупки за границей",
            "Подскажите, пожалуйста, как перевести деньги на счет другого банка?"
        ]
        
        for msg in test_messages:
            title = await generate_chat_title(msg)
            print(f"\nСообщение: {msg[:70]}...")
            print(f"Название:  {title}")
    
    asyncio.run(test())
