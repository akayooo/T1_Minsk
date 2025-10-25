"""
НЕ ИСПОЛЬЗУЕТСЯ! Используем ocr.py.
"""

import os
import base64
import socks
import socket
import time
from openai import OpenAI
from dotenv import load_dotenv
import logging

# load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
SOCKS5_URL = os.getenv("SOCKS5_URL")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# TODO
def setup_socks5_proxy():
    """
    Глобальный SOCKS5 proxy ломает сервисы, надо использовать прокси на уровне Docker network
    """
    logging.warning("SOCKS5 proxy отключен для предотвращения конфликтов с Kafka/Redis")
    return False

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=API_KEY,
)

def analyze_image_from_url(image_url: str, model: str, use_proxy: bool) -> str:
    """
    Извлекает текст из изображения по URL.
    
    Args:
        image_url: URL изображения
        model: Модель для анализа (по умолчанию google/gemma-3-12b-it:free)
        use_proxy: Использовать ли SOCKS5 прокси (по умолчанию True)
    """
    prompt = "Опиши всё, что видишь на этом изображении."
    
    if use_proxy:
        setup_socks5_proxy()
    
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ],
                }
            ],
            max_tokens=2048 
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Произошла ошибка: {e}"

def analyze_image_from_file(file_path: str, model: str, use_proxy: bool) -> str:
    """
    Извлекает текст из локального файла изображения.
    
    Args:
        file_path: Путь к локальному файлу изображения
        model: Модель для анализа (по умолчанию google/gemma-3-12b-it:free)
        use_proxy: Использовать ли SOCKS5 прокси (по умолчанию True)
    """
    prompt = "Опиши всё, что видишь на этом изображении."

    if use_proxy:
        setup_socks5_proxy()

    try:
        with open(file_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2048
        )
        return completion.choices[0].message.content
    except FileNotFoundError:
        return f"Ошибка: файл не найден по пути {file_path}"
    except Exception as e:
        return f"Произошла ошибка: {e}"


# if __name__ == "__main__":
    
#     model = [
#         "google/gemma-3-12b-it", 
#         "meta-llama/llama-3.2-90b-vision-instruct", 
#         "qwen/qwen2.5-vl-32b-instruct", 
#         "google/gemini-2.5-flash", 
#         "x-ai/grok-4-fast", 
#         "microsoft/phi-4-multimodal-instruct",
#         "openai/gpt-5-nano"
#         ]

#     use_proxy = True
#     path_to_image = "0001.png" 
    
#     start_time = time.time()
#     extracted_text_different_model = analyze_image_from_file(path_to_image, model=model[0], use_proxy=use_proxy)
    
#     end_time = time.time()
#     execution_time = end_time - start_time
    
#     logging.info(extracted_text_different_model)
#     logging.info(f"Время выполнения: {execution_time:.2f} секунд")

    #Таблица с результатами
    #meta-llama/llama-3.2-90b-vision-instruct - 8.78 секунд, Прокси - нет, Цена - 0,000262$
    #google/gemma-3-12b-it - 3.36 секунд, Прокси - нет, Цена - 0,0000261$
    #qwen/qwen2.5-vl-32b-instruct - 15.21 секунд, Прокси - нет, Цена - 0,000294
    #google/gemini-2.5-flash - 3.02 секунд, Прокси - нет, Цена - 0,000961$
    #x-ai/grok-4-fast - 3.34 секунд, Прокси - да, Цена - 0,00022$
    #microsoft/phi-4-multimodal-instruct - 3.34 секунд, Прокси - нет, Цена - 0,0000269$
    #openai/gpt-5-nano - 6.48 секунд, Прокси - нет, Цена - 0,000343$

    #google/gemma-3-12b-it и microsoft/phi-4-multimodal-instruct - бестики
