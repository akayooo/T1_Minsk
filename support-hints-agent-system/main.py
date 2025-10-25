import json
import logging
import os
import time
from typing import Any, Dict, List

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def call_assist(api_url: str, user_request: str, last_messages: List[Dict[str, str]]) -> Dict[str, Any]:
	payload = {
		"user_request": user_request,
		"last_messages": last_messages[-10:],
	}
	resp = requests.post(f"{api_url.rstrip('/')}/assist", json=payload, timeout=60)
	resp.raise_for_status()
	return resp.json()


def main():
	api_url = os.getenv("SUPPORT_API_URL", "http://localhost:8000")
	logger.info(f"Вызов API /assist по адресу: {api_url}")

	# user_request = (
	# 	"Что такое карта мгновенного выпуска?"
	# )
	user_request = (
		"Не могу войти в Интернет-банк"
	)

	last_messages = [
		{"role": "client", "content": "Здравствуйте"},
		{"role": "operator", "content": "Добрый день, чем могу помочь?"},
		{"role": "client", "content": "Проблемы со входом"},
	]

	try:
		# Замеряем время обработки запроса
		start_time = time.time()
		result = call_assist(api_url, user_request, last_messages)
		end_time = time.time()
		
		processing_time = end_time - start_time
		
		print("\n" + "="*80)
		print("Ответ /assist")
		print("="*80)
		print(f"Время обработки запроса: {processing_time:.2f} секунд")
		print("-" * 80)
		print(json.dumps(result, ensure_ascii=False, indent=2))
	except requests.HTTPError as http_err:
		logger.exception(f"HTTP ошибка: {http_err}")
		print(getattr(http_err.response, "text", ""))
	except Exception as e:
		logger.exception(f"Ошибка вызова /assist: {e}")


if __name__ == "__main__":
	main()
