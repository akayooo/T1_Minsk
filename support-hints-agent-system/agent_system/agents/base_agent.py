"""Базовые компоненты LLM-агентов.

Содержит общий класс `BaseLLMAgent` с реализацией повторного использования LLM,
ожидания rate limit, ретраев и стандартного вызова модели с парсингом ответов.
"""

import json
import logging
import random
import time
from typing import Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from openai import RateLimitError

from agent_system.source.config import config

logger = logging.getLogger(__name__)


class BaseLLMAgent:
    """Базовый класс LLM-агентов.

    Инкапсулирует инициализацию LLM, ожидание между запросами, обработку rate
    limit с экспоненциальными задержками и стандартный вызов модели с JSON-парсером.
    Наследники реализуют предметную логику и промпты.
    """

    def __init__(self, llm: Optional[ChatOpenAI] = None, model_name: str = None) -> None:
        self.model_name = model_name or config.model
        self.last_request_time = 0

        if llm is not None:
            self.llm = llm
        else:
            self.llm = ChatOpenAI(
                model=self.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.request_timeout_seconds,
                max_retries=config.llm_max_retries,
            )

    def _wait_for_rate_limit(self) -> None:
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        wait_time = max(config.delay_between_requests, 0.5 + random.random())  # noqa: S311

        if time_since_last_request < wait_time:
            delay = wait_time - time_since_last_request
            logger.debug("Задержка перед запросом", extra={"delay_seconds": round(delay, 2)})
            time.sleep(delay)

        self.last_request_time = time.time()

    def _invoke_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        parser: JsonOutputParser,
        agent_name: str = "agent"
    ) -> Dict:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._wait_for_rate_limit()
                response = self.llm.invoke(messages)

                try:
                    result = parser.parse(response.content)
                    logger.debug(
                        f"{agent_name} парсинг успешен",
                        extra={"result_preview": json.dumps(result, ensure_ascii=False)[:200]}
                    )
                    return result

                except Exception as e:
                    raw = getattr(response, "content", "")
                    logger.error(
                        f"Ошибка парсинга JSON в {agent_name}",
                        extra={"error": str(e), "raw_response": raw[:1000]}
                    )

                    try:
                        text_only = raw.strip("```json").strip("```").strip()  # noqa: B005
                        result = parser.parse(text_only)
                        logger.info(f"Успешный парсинг после очистки в {agent_name}")
                        return result

                    except Exception as e2:
                        logger.error(
                            f"Fallback парсинг также не удался в {agent_name}",
                            extra={"error": str(e2), "attempt": attempt + 1, "max_retries": max_retries}
                        )
                        raise

            except RateLimitError:
                if attempt < max_retries - 1:
                    retry_delay = config.retry_delay * (attempt + 1)
                    logger.warning(
                        f"Rate limit в {agent_name}",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "retry_delay_seconds": retry_delay
                        }
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Rate limit превышен после всех попыток в {agent_name}")
                    raise

