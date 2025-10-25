from transformers import pipeline, AutoTokenizer 
import torch
import gc
import logging

logger = logging.getLogger(__name__)

_pipe = None
_tokenizer = None
_device = -1


def load_model(model_id='urukhan/t5-russian-summarization'):
    """
    Загружает модель один раз при старте сервиса.
    """
    global _pipe, _tokenizer, _device
    
    if _pipe is not None:
        logger.info("Модель уже загружена")
        return True
    
    try:
        _device = -1
        if torch.backends.mps.is_available(): 
            logger.info("MPS device detected.")
        elif torch.cuda.is_available(): 
            _device = 0
            logger.info("CUDA device detected.")
        else: 
            logger.info("Using CPU.")

        if _device != -1:
             if torch.cuda.is_available(): torch.cuda.empty_cache()
             elif torch.backends.mps.is_available(): torch.mps.empty_cache()
        gc.collect()

        logger.info(f"Загрузка токенизатора: {model_id}")
        _tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)
        logger.info("Токенизатор загружен")

        logger.info(f"Загрузка модели: {model_id}")
        _pipe = pipeline(
            'text2text-generation',
             model=model_id,
             tokenizer=_tokenizer, 
        )
        logger.info("Модель загружена успешно")
        return True

    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {e}")
        return False


def generate_chat_title(first_message):
    """
    Генерирует заголовок для тикета, используя загруженную модель ruT5.
    """
    global _pipe
    
    if _pipe is None:
        return "Ошибка: Модель не загружена"
    
    try:
        max_input_length = 1000
        if len(first_message) > max_input_length:
            first_message = first_message[:max_input_length]
        
        # Более простой промпт для T5
        prompt = f'Создай короткий заголовок для: {first_message}'

        logger.info("Генерация заголовка...")
        with torch.inference_mode():
            outputs = _pipe(
                prompt,
                max_length=25, 
                min_length=3, 
                num_beams=2,  
                early_stopping=True
            )

        if outputs and isinstance(outputs, list):
            title = outputs[0]['generated_text'].strip()
            
            # Очищаем заголовок от артефактов промпта
            title = title.replace('Заголовок:', '').strip()
            title = title.replace('Запрос:', '').strip()
            title = title.strip('"').strip("'").strip()
            
            if len(title) > 100:
                title = title[:100].strip()
            
            if len(title) < 3:
                title = first_message[:50].strip()
            
            logger.info(f"Заголовок сгенерирован: '{title}'")
            return title
        else:
            return "Ошибка: Не удалось сгенерировать заголовок"

    except Exception as e:
        logger.error(f"Ошибка генерации заголовка: {e}")
        if "out of memory" in str(e).lower():
             return "Ошибка нехватки памяти"
        return f"Ошибка: {str(e)[:100]}"