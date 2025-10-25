FINDER_SYSTEM_PROMPT = """Нормализуй запрос. Верни JSON: {"normalized_query": "поиск в базе знаний", "memory_query": "поиск в памяти пользователя"}."""


FINDER_USER_PROMPT = """Запрос: {user_request}

Верни JSON: {{"normalized_query": "краткий поиск", "memory_query": "поиск в памяти"}}"""


RERANKER_SYSTEM_PROMPT = """Выбери лучшие документы. Верни JSON: {"results": [{"id": "1"}]}."""


RERANKER_USER_PROMPT = """Запрос: {query}

Документы: {docs}

Верни JSON: {{"results": [{{"id": "1"}}, {{"id": "2"}}]}}"""


CONTROLLER_SYSTEM_PROMPT = """Оцени релевантность. Верни JSON: {"is_satisfactory": true, "confidence": 0.8, "reasoning": "текст", "suggestions": "текст"}."""  


CONTROLLER_USER_PROMPT = """Запрос: {original_query}

Документы: {documents}

Верни JSON: {{"is_satisfactory": true, "confidence": 0.8, "reasoning": "текст", "suggestions": "текст"}}""" 


FINDER_REFORMULATE_PROMPT = """Ты получил обратную связь от контроллера качества.

ИСХОДНЫЙ запрос пользователя:
{original_query}

Твоя предыдущая формулировка:
{previous_query}

Предыдущие попытки:
{query_history}

Обратная связь от контроллера:
{feedback}

ЗАДАЧА:
Переформулируй запрос для RAG, учитывая:
1. Исходный запрос пользователя (главное!)
2. Что не сработало в предыдущих попытках
3. Рекомендации контроллера

ТРЕБОВАНИЯ:
- Сохрани исходный смысл запроса пользователя
- Попробуй другие ключевые слова, синонимы
- Измени уровень детализации (более общий или более конкретный)
- НЕ повторяй предыдущие формулировки
- Язык — русский

Верни ТОЛЬКО валидный JSON (без ```json и без пояснений):
{{
  "normalized_query": "переформулированный запрос"
}}"""


HINTS_GENERATOR_SYSTEM_PROMPT = """Создай действия для оператора. Верни JSON: {"suggested_actions": ["действие 1", "действие 2"], "relevant_docs": ["документ 1"]}."""


HINTS_GENERATOR_USER_PROMPT = """Запрос: {user_request}

Документы: {documents}

Верни JSON: {{"suggested_actions": ["действие 1", "действие 2"], "relevant_docs": ["документ 1"]}}"""


VALIDATOR_SYSTEM_PROMPT = """Ты — контроллер качества подсказок.

Проверь: действия конкретные и соответствуют запросу. Минимум 2 шага.

ВАЖНО: Всегда возвращай валидный JSON в точном формате."""


VALIDATOR_USER_PROMPT = """Запрос: {user_request}
Действия: {suggested_actions}

Оцени качество:

ОБЯЗАТЕЛЬНО верни валидный JSON:
{{
  "is_acceptable": true,
  "confidence": 0.9,
  "feedback": "замечания если есть"
}}

Пример:
{{
  "is_acceptable": true,
  "confidence": 0.85,
  "feedback": "действия хорошие"
}}"""


HINTS_REGENERATE_PROMPT = """Запрос: {user_request}
Предыдущие действия: {previous_actions}
Feedback: {validator_feedback}
Документы: {documents}

Улучши подсказки:

{{
  "suggested_actions": [
    "действие 1",
    "действие 2"
  ],
  "relevant_docs": [
    "doc_1: название",
    "doc_2: название"
  ]
}}"""
