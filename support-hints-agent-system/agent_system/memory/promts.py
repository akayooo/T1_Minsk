"""
prompts.py — Generation of prompts for the LLM.
"""
from typing import Dict, Sequence


def build_system_prompt() -> str:
    """Builds the system prompt for the knowledge analyst LLM.

    Returns:
        A string containing the system prompt with instructions for the LLM.
    """
    return (
        "Ты — аналитик знаний. Твоя цель: извлечь из диалога оператора поддержки и пользователя "
        "факты/намерения/предпочтения, которые полезно хранить как долгосрочную память. "
        "Под «знанием» понимается компактная формулировка, которая может пригодиться при будущих обращениях.\n\n"
        "Требования к знаниям:\n"
        "1) Конкретность и стабильность: не одноразовые «сейчас/сегодня», а устойчивые факты (намерение продлить подписку, предпочитаемый канал связи, роль, компания, регион, продукт/тариф и т.п.).\n"  # noqa: E501
        "2) Полезность для сервиса: данные аккаунта, пожелания по оплате/связи, повторяющиеся проблемы, статус подписки, используемые интеграции, версии и т.п.\n" # noqa: E501
        "3) Конфиденциальность: если присутствуют чувствительные данные (пароли, токены, полные номера карт), НЕ включай их.\n" # noqa: E501
        "4) Лаконичность: title — 1–10 слов; sub_title — 1–2 предложения; knowledge — ясная формулировка.\n\n"
        "Оценка пригодности: для каждого кандидата выставь keep (true/false), score (0..100) и краткое reason."
    )


def build_user_prompt(dialogue: Sequence[Dict[str, str]]) -> str:
    """Builds the user prompt with the dialogue to be analyzed.

    Args:
        dialogue: A sequence of dictionaries, where each dictionary represents a message
                  with 'role' and 'content' keys.

    Returns:
        A formatted string containing the user prompt for the LLM.
    """
    lines = []
    for idx, msg in enumerate(dialogue):
        role = msg.get("role", "operator")
        content = (msg.get("content") or "").replace("\n", " ").strip()
        lines.append(f"[{idx}] {role}: {content}")
    rendered_dialogue = "\n".join(lines)

    return (
        "Ниже дан диалог (каждая строка — фрагмент с индексом). "
        "Извлеки КАНДИДАТЫ знаний и оцени их пригодность.\n\n"
        f"{rendered_dialogue}\n\n"
        "Верни строго JSON с полем 'candidates' (без пояснений, без markdown):\n"
        "{\n"
        '  "candidates": [\n'
        "    {\n"
        '      "key": <int, индекс фрагмента>,\n'
        '      "role": "user" | "operator",\n'
        '      "title": "короткое название",\n'
        '      "sub_title": "подназвание (подробнее)",\n'
        '      "knowledge": "суть знания",\n'
        '      "keep": true | false,\n'
        '      "score": <0..100>,\n'
        '      "reason": "почему так"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        'Если знаний нет — верни {"candidates": []}.'
    )
