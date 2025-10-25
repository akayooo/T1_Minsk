"""Системный фасад для мультиагентной обработки запросов поддержки."""

from typing import Any, Dict, Optional

from langchain_openai import ChatOpenAI

from agent_system.source.config import config
from agent_system.state import AgentState, RerankResult
from agent_system.utils.logger import logger
from agent_system.workflow import build_graph
from agent_system.utils.model_loader import load_deeppavlov_bert

try:
	from qdrant_client import QdrantClient
	from openai import OpenAI

	from agent_system.rag.controller import RetrieverController
	RAG_AVAILABLE = True
except ImportError as e:
	logger.warning(f"RAG компоненты недоступны: {e}. Будет использоваться mock-режим.")
	RAG_AVAILABLE = False


class SupportAgentSystem:
	"""Высокоуровневый интерфейс системы агентов поддержки."""

	def __init__(
		self,
		api_key: Optional[str] = None,
		model: Optional[str] = None,
		use_real_rag: bool = True,
		qdrant_client: Optional["QdrantClient"] = None,
		retriever_controller: Optional["RetrieverController"] = None
	) -> None:
		self.api_key = api_key or config.api_key
		self.model = model or config.model

		if not self.api_key:
			raise ValueError(
				"Неверный API ключ. Пожалуйста, укажите корректный ключ SCIBOX_API_KEY."
			)

		try:
			self.llm = ChatOpenAI(
				model=self.model,
				temperature=config.temperature,
				api_key=self.api_key,
				base_url=config.base_url,
				timeout=config.request_timeout_seconds,
				max_retries=config.llm_max_retries,
				max_tokens=config.max_tokens,
			)
			logger.info("LLM инициализирован", extra={"model": self.model})
		except Exception as e:
			logger.exception("Ошибка инициализации LLM", extra={"error": str(e)})
			raise

		self.use_real_rag = use_real_rag and RAG_AVAILABLE
		self.retriever = None

		if retriever_controller:
			self.retriever = retriever_controller
			self.use_real_rag = True
			logger.info("Используется переданный RetrieverController")
		elif self.use_real_rag:
			try:
				self._init_rag_components(qdrant_client)
			except Exception as e:
				logger.warning(f"Не удалось инициализировать RAG: {e}. Используется mock-режим.")
				self.use_real_rag = False

		if not self.use_real_rag:
			logger.warning("RAG работает в mock-режиме (имитация)")

		self.app = None
		logger.info("Система агентов поддержки инициализирована")

	def _init_rag_components(self, qdrant_client: Optional["QdrantClient"] = None) -> None:
		"""Инициализирует компоненты RAG и Memory."""
		if not RAG_AVAILABLE:
			raise ImportError("RAG компоненты не установлены")

		if qdrant_client:
			client = qdrant_client
		else:
			try:
				client = QdrantClient(url=config.qdrant_url)
				client.get_collections()
				logger.info(f"Подключение к Qdrant успешно: {config.qdrant_url}")
			except Exception as e:
				raise RuntimeError(f"Не удалось подключиться к Qdrant по адресу {config.qdrant_url}: {e}") from e

		try:
			# Используем локальную модель SentenceTransformer (finetuned_classifier имеет правильную структуру с Pooling)
			from sentence_transformers import SentenceTransformer
			import torch
			device = "cuda" if torch.cuda.is_available() else "cpu"
			dense_encoder = load_deeppavlov_bert()
			logger.info(f"SentenceTransformer для эмбеддингов инициализирован: {config.dense_model_name} на устройстве {device}")
		except Exception as e:
			raise RuntimeError(f"Не удалось инициализировать SentenceTransformer для эмбеддингов '{config.dense_model_name}': {e}") from e

		try:
			from qdrant_client.http import models as qmodels

			from agent_system.rag.controller import SparseEncoder
			try:
				logger.info("Очистка базы знаний перед загрузкой FAQ XLSX")
				client.delete(
					collection_name=config.knowledge_base_collection,
					points_selector=qmodels.FilterSelector(filter=qmodels.Filter()),
					wait=True
				)
			except Exception:
				logger.warning("Не удалось очистить базу знаний")
				pass

			faq_docs = self._load_kb_from_faq_excel("agent_system/service/smart_support_vtb_belarus_faq_final.xlsx")
			corpus = [d.get("knowledge", "") for d in faq_docs]
			sparse_encoder = SparseEncoder(corpus=corpus)
			tmp_retriever = RetrieverController(
				client=client,
				dense_encoder=dense_encoder,
				sparse_encoder=sparse_encoder
			)
			tmp_retriever.add_to_knowledge_base(faq_docs, source="FAQ XLSX")
			logger.info("FAQ XLSX предзагружен в Qdrant", extra={"count": len(faq_docs)})
		except Exception as e:
			logger.warning(f"Инициализация загрузки FAQ не выполнена: {e}")
			sparse_encoder = None

		self.retriever = RetrieverController(
			client=client,
			dense_encoder=dense_encoder,
			sparse_encoder=sparse_encoder
		)
		logger.info("RetrieverController инициализирован")

	def _finder_node(self, state: AgentState) -> Dict[str, Any]:
		import time
		start_time = time.time()
		
		from agent_system.agents.finder import FinderAgent
		agent = FinderAgent(llm=self.llm, model_name=self.model)

		metadata = state.get("metadata", {})
		iteration = metadata.get("iteration_count", 0)

		try:
			controller_eval = metadata.get("controller_evaluation")

			if controller_eval and not controller_eval.get("is_satisfactory", True):
				logger.info(f"Искатель: переформулирование запроса (итерация {iteration})")

				original_query = state.get("user_request", "")
				previous_finder = metadata.get("finder", {})
				previous_query = previous_finder.get("normalized_query", "")
				feedback = controller_eval.get("suggestions", "")
				query_history = metadata.get("query_history", [])

				result = agent.reformulate_query(
					original_query=original_query,
					previous_query=previous_query,
					feedback=feedback,
					query_history=query_history
				)
			else:
				logger.info("Искатель: первоначальная подготовка запроса")
				result = agent.prepare_query(state.get("user_request", ""))

			query_history = metadata.get("query_history", [])
			query_history.append({
				"iteration": iteration,
				"query": result["normalized_query"],
				"original": result["original_query"]
			})

			new_iteration = iteration + 1

			state["metadata"] = {
				**metadata,
				"finder": result,
				"original_query": state.get("user_request", ""),
				"query_history": query_history,
				"iteration_count": new_iteration
			}
			state["current_step"] = "finder_complete"

			execution_time = time.time() - start_time
			logger.info(
				f"Искатель завершил работу (итерация {new_iteration}) за {execution_time:.2f}с",
				extra={"query": result["normalized_query"][:100], "execution_time": execution_time}
			)

			return state

		except Exception as e:
			execution_time = time.time() - start_time
			logger.exception(
				f"Ошибка работы искателя за {execution_time:.2f}с",
				extra={"error": str(e), "user_request": state.get("user_request", "")[:100], "execution_time": execution_time}
			)
			state["current_step"] = "finder_failed"
			return state

	def _rag_node(self, state: AgentState) -> Dict[str, Any]:
		"""RAG: поиск в базе знаний."""
		import time
		start_time = time.time()
		
		finder = (state.get("metadata") or {}).get("finder", {})
		query = finder.get("normalized_query") or state.get("user_request", "")

		if self.use_real_rag and self.retriever:
			try:
				self._preload_mock_kb_if_empty(force_init_sparse=not bool(self.retriever.sparse_encoder))

				if self.retriever.sparse_encoder:
					results = self.retriever.search_knowledge_base(
						query=query,
						limit=config.rag_search_limit
					)
					logger.info("Используется гибридный поиск (dense + sparse)")
				else:
					query_vector = self.retriever.dense_encoder.encode(query).tolist()
					results = self.retriever.client.search(
						collection_name=self.retriever.kb_collection,
						query_vector=("default", query_vector),
						limit=config.rag_search_limit,
						with_payload=True
					)
					logger.info("Используется только dense поиск")

				docs = [
					{
						"id": str(result.id),
						"score": float(result.score),
						"payload": result.payload or {},
					}
					for result in results
				]

				logger.info(f"RAG вернул {len(docs)} документов из Qdrant")
			except Exception as e:
				logger.error(f"Ошибка поиска в RAG: {e}")
				docs = []
		else:
			# Если retriever не инициализирован, возвращаем пустой список
			if not self.retriever:
				logger.error("RAG не инициализирован: retriever = None")
				docs = []
			else:
				self._preload_mock_kb_if_empty(force_init_sparse=True)
				try:
					results = self.retriever.search_knowledge_base(query=query, limit=config.rag_search_limit)
					docs = [
						{
							"id": str(result.id),
							"score": float(result.score),
							"payload": result.payload or {},
						}
						for result in results
					]
					logger.info(f"RAG (mock) вернул {len(docs)} документов")
				except Exception as e:
					logger.error("Mock режим: ошибка поиска ретривера", extra={"error": str(e)})
					docs = []

		execution_time = time.time() - start_time
		logger.info(f"RAG завершил поиск за {execution_time:.2f}с, найдено {len(docs)} документов")
		
		return {"metadata": {**state.get("metadata", {}), "rag_docs": docs}}

	def _memory_node(self, state: AgentState) -> Dict[str, Any]:
		"""Memory: асинхронное сохранение новых данных в долгосрочную память.

		Извлекает знания из запроса пользователя и сохраняет их в Qdrant в фоновом режиме.
		"""
		import threading
		import time
		start_time = time.time()
		
		user_id = (state.get("metadata", {}) or {}).get("user_id", 0)
		user_request = state.get("user_request", "")

		if self.use_real_rag and self.retriever:
			def save_to_memory():
				try:
					logger.info(
						"Memory: асинхронная запись сообщения пользователя",
						extra={"user_id": user_id, "request_length": len(user_request)}
					)

					memories_to_save = [{
						"knowledge": user_request,
						"title": "User message",
						"sub_title": "",
						"user_id": user_id
					}]

					self.retriever.add_to_long_term_memory(memories_to_save)
					logger.info(f"Memory: сохранено {len(memories_to_save)} записей в Qdrant")

				except Exception as e:
					logger.error("Ошибка асинхронной записи в Memory", extra={"error": str(e)})

			memory_thread = threading.Thread(target=save_to_memory, daemon=True)
			memory_thread.start()
			logger.info("Memory: запущено асинхронное сохранение")
		else:
			logger.info("Memory недоступна (RAG отключен)")

		execution_time = time.time() - start_time
		logger.info(f"Memory узел завершен за {execution_time:.2f}с (асинхронно)")

		return {"metadata": state.get("metadata", {})}

	def _get_mock_kb_documents(self) -> list[dict]:
		return [
			{
				"knowledge": "Для входа в аккаунт используйте зарегистрированный email и пароль. При появлении ошибки 'Invalid credentials' убедитесь в правильности введенных данных. Проверьте раскладку клавиатуры и отсутствие лишних пробелов.", 
				"title": "knowledge_base/auth.md",
				"sub_title": "Инструкция по входу в аккаунт",
				"key": 1
			},
			{
				"knowledge": "Сброс пароля: нажмите 'Забыли пароль?' на странице входа, введите email, указанный при регистрации. Следуйте инструкциям из письма для создания нового пароля. Ссылка действительна 24 часа.", 
				"title": "knowledge_base/password_reset.md",
				"sub_title": "Сброс пароля и ограничения",
				"key": 2
			},
			{
				"knowledge": "Восстановление доступа к аккаунту: если не помните email, обратитесь в службу поддержки с указанием полного имени и приблизительной даты регистрации. Потребуется верификация личности.",  
				"title": "knowledge_base/account_recovery.md",
				"sub_title": "Восстановление доступа без email",
				"key": 3
			},
			{
				"knowledge": "Двухфакторная аутентификация (2FA): настройте дополнительный уровень защиты в разделе 'Безопасность'. Поддерживаются SMS-коды и приложения-аутентификаторы (Google Authenticator, Authy).",  
				"title": "knowledge_base/security.md",
				"sub_title": "Двухфакторная аутентификация",
				"key": 4
			},
			{
				"knowledge": "Изменение контактного email: зайдите в настройки профиля, раздел 'Контактная информация'. Введите новый email и подтвердите изменение через код из письма.",  
				"title": "knowledge_base/profile_settings.md",
				"sub_title": "Изменение контактного email",
				"key": 5
			},
			{
				"knowledge": "Экспорт данных в CSV: откройте меню 'Настройки' → 'Данные и конфиденциальность' → 'Экспорт'. Выберите период выгрузки и формат CSV. Файл будет доступен для скачивания в течение 7 дней.",  
				"title": "knowledge_base/data_export.md",
				"sub_title": "Экспорт данных пользователя",
				"key": 6
			},
			{
				"knowledge": "Рецепт приготовления борща: нарежьте свеклу, морковь, лук и картофель. Обжарьте овощи на сковороде, затем добавьте в кастрюлю с мясным бульоном. Варите 30 минут, добавьте капусту и специи по вкусу.",  
				"title": "cooking/recipes.md",
				"sub_title": "Русская кухня - борщ",
				"key": 7
			},
			{
				"knowledge": "Как выращивать помидоры в теплице: подготовьте почву с pH 6.0-6.5, посадите рассаду на расстоянии 40-50 см друг от друга. Обеспечьте регулярный полив и подкормку минеральными удобрениями каждые 2 недели.",  
				"title": "gardening/tomatoes.md",
				"sub_title": "Садоводство - помидоры",
				"key": 8
			},
			{
				"knowledge": "Основы игры в шахматы: цель игры - поставить мат королю противника. Пешки ходят только вперед, слоны по диагонали, ладьи по горизонтали и вертикали. Король может ходить на одну клетку в любом направлении.",  
				"title": "games/chess.md",
				"sub_title": "Правила игры в шахматы",
				"key": 9
			},
			{
				"knowledge": "Программирование на Python: для создания списка используйте квадратные скобки [], для словаря - фигурные {}. Функции определяются с помощью ключевого слова def, классы - с помощью class. Импорты выполняются через import.",  
				"title": "programming/python.md",
				"sub_title": "Основы Python",
				"key": 10
			},
			{
				"knowledge": "Погода в Москве сегодня: ожидается переменная облачность, температура от +15 до +22 градусов Цельсия. Вероятность осадков 30%. Ветер северо-западный, 3-5 м/с. Рекомендуется легкая куртка.",  
				"title": "weather/moscow.md",
				"sub_title": "Прогноз погоды",
				"key": 11
			},
			{
				"knowledge": "Уход за автомобилем: регулярно проверяйте уровень масла в двигателе, давление в шинах, состояние тормозных колодок. Меняйте масло каждые 10-15 тысяч км, воздушный фильтр - каждые 20 тысяч км пробега.",  
				"title": "automotive/car_maintenance.md",
				"sub_title": "Техобслуживание автомобиля",
				"key": 12
			}
		]

	def _preload_mock_kb_if_empty(self, force_init_sparse: bool = False) -> None:
		"""Если база знаний пуста — загружает документы из FAQ XLSX в Qdrant.

		Также инициализирует SparseEncoder на основе корпуса документов при необходимости.
		"""
		# Проверяем, что retriever инициализирован
		if not self.retriever:
			logger.error("Не могу загрузить FAQ: retriever не инициализирован")
			return
			
		try:
			info = self.retriever.client.get_collection(collection_name=self.retriever.kb_collection)
			points_count = getattr(info, "points_count", 0) or 0
		except Exception:
			points_count = 0

		if points_count > 0 and not force_init_sparse:
			return

		faq_docs = self._load_kb_from_faq_excel("agent_system/service/smart_support_vtb_belarus_faq_final.xlsx")
		corpus = [d.get("knowledge", "") for d in faq_docs]

		try:
			if force_init_sparse or not getattr(self.retriever, "sparse_encoder", None):
				from agent_system.rag.controller import SparseEncoder
				self.retriever.sparse_encoder = SparseEncoder(corpus=corpus)
		except Exception as e:
			logger.warning("Не удалось инициализировать SparseEncoder для FAQ", extra={"error": str(e)})

		try:
			self.retriever.add_to_knowledge_base(faq_docs, source="FAQ XLSX")
			logger.info("FAQ XLSX загружен в Qdrant", extra={"count": len(faq_docs)})
		except Exception as e:
			logger.warning("Не удалось загрузить FAQ XLSX", extra={"error": str(e)})

	def _load_kb_from_faq_excel(self, path: str) -> list[dict]:
		"""Читает FAQ Excel и возвращает документы для KB.

		Ожидаемые столбцы первого листа:
		- "Основная категория"
		- "Подкатегория"
		- "Пример вопроса"
		- "Шаблонный ответ" (контент knowledge)
		"""
		try:
			import pandas as pd
		except Exception as e:
			logger.exception(f"pandas недоступен для чтения Excel: {e}")
			return []

		try:
			df = pd.read_excel(path, sheet_name=0)

			df.columns = [str(c).strip() for c in df.columns]
		except FileNotFoundError:
			logger.warning(f"FAQ Excel не найден: {path}")
			return []
		except Exception as e:
			logger.exception(f"Ошибка чтения Excel '{path}': {e}")
			return []

		def _find_col(expected: str) -> Optional[str]:
			for col in df.columns:
				if col.lower() == expected.lower():
					return col
			return None

		col_main = _find_col("Основная категория")
		col_sub = _find_col("Подкатегория")
		col_question = _find_col("Пример вопроса")
		col_answer = _find_col("Шаблонный ответ")

		missing = [name for name, col in [
			("Основная категория", col_main),
			("Подкатегория", col_sub),
			("Пример вопроса", col_question),
			("Шаблонный ответ", col_answer),
		] if col is None]
		if missing:
			logger.warning(f"В Excel отсутствуют ожидаемые столбцы: {', '.join(missing)}")

		documents: list[dict] = []
		row_id = 1
		for _, row in df.iterrows():
			answer = (str(row[col_answer]).strip() if col_answer in row and pd.notna(row[col_answer]) else "")
			if not answer:
				continue

			main_cat = (str(row[col_main]).strip() if col_main in row and pd.notna(row[col_main]) else "")
			sub_cat = (str(row[col_sub]).strip() if col_sub in row and pd.notna(row[col_sub]) else "")
			question = (str(row[col_question]).strip() if col_question in row and pd.notna(row[col_question]) else "")

			title_parts = [p for p in [main_cat, sub_cat] if p]
			title = " / ".join(title_parts) if title_parts else (question[:80] or "FAQ")
			sub_title = question

			documents.append({
				"knowledge": answer,
				"title": title,
				"sub_title": sub_title,
				"key": row_id,
			})
			row_id += 1

		logger.info("Сформировано документов из FAQ", extra={"count": len(documents)})
		return documents

	def _reranker_node(self, state: AgentState) -> Dict[str, Any]:
		import time
		start_time = time.time()
		
		from agent_system.agents.reranker import ReRankerAgent
		agent = ReRankerAgent(llm=self.llm, model_name=self.model)
		meta = state.get("metadata") or {}
		original_query = state.get("user_request", "")
		docs = meta.get("rag_docs", [])
		ranked: RerankResult = agent.rerank(original_query, docs)

		if not isinstance(ranked, dict) or "results" not in ranked:
			logger.warning("ReRanker вернул неожиданный формат, используем пустой список")
			ranked = {"results": []}

		execution_time = time.time() - start_time
		logger.info(f"ReRanker завершил обработку за {execution_time:.2f}с, обработано {len(ranked.get('results', []))} документов")
		new_meta = {**meta, "rag_docs_reranked": ranked.get("results", [])}

		return {"metadata": new_meta}

	def _controller_node(self, state: AgentState) -> Dict[str, Any]:
		"""Узел контроллера: оценивает результаты RAG и учитывает память из state.
		Возвращает только частичные обновления (metadata/current_step), чтобы избежать конфликтов.
		"""
		import time
		start_time = time.time()
		
		from agent_system.agents.controller import ControllerAgent

		agent = ControllerAgent(llm=self.llm, model_name=self.model, max_iterations=3)

		try:
			meta = state.get("metadata") or {}
			
			incoming_docs = meta.get("rag_docs_reranked", [])
			logger.info(
				"Controller входящие документы",
				extra={
					"count": len(incoming_docs),
					"ids": [d.get("id") for d in incoming_docs[:10]],
					"scores": [d.get("score") for d in incoming_docs[:10]]
				}
			)

			result_state = agent.process_state(state)

			evaluation = result_state["metadata"].get("controller_evaluation", {})
			logger.info(
				"Контроллер принял решение",
				extra={
					"satisfactory": evaluation.get("is_satisfactory", False),
					"should_continue": evaluation.get("should_continue", False),
					"confidence": evaluation.get("confidence", 0),
					"reasoning": evaluation.get("reasoning", "")[:120]
				}
			)

			execution_time = time.time() - start_time
			logger.info(f"Controller завершил оценку за {execution_time:.2f}с")
			return {
				"metadata": result_state.get("metadata", {}),
				"current_step": result_state.get("current_step", "controller_complete"),
			}

		except Exception as e:
			logger.exception("Ошибка работы контроллера", extra={"error": str(e)})
			state["current_step"] = "controller_failed"
			state["metadata"] = {
				**state.get("metadata", {}),
				"controller_evaluation": {
					"is_satisfactory": True,
					"should_continue": False,
					"confidence": 0.0,
					"reasoning": f"Ошибка контроллера: {str(e)}",
					"suggestions": ""
				}
			}
			execution_time = time.time() - start_time
			logger.error(f"Controller завершился с ошибкой за {execution_time:.2f}с")
			return {
				"metadata": state.get("metadata", {}),
				"current_step": "controller_failed",
			}

	def _hints_generator_node(self, state: AgentState) -> Dict[str, Any]:
		"""Узел генератора подсказок для оператора. Возвращает частичные обновления (metadata/current_step)."""
		import time
		start_time = time.time()
		
		from agent_system.agents.hints_generator import HintsGeneratorAgent

		agent = HintsGeneratorAgent(llm=self.llm, model_name=self.model)

		meta = state.get("metadata") or {}
		rag_docs = meta.get("rag_docs_reranked", [])
		if not rag_docs:
			logger.warning("Нет документов для генерации подсказок")

		memory_docs = []
		if self.use_real_rag and self.retriever:
			try:
				user_id = meta.get("user_id", 1)
				finder_result = meta.get("finder", {})
				memory_query = finder_result.get("memory_query", state.get("user_request", ""))
				
				logger.info(f"Поиск в памяти пользователя", extra={"user_id": user_id, "query": memory_query[:50]})
				
				memory_results = self.retriever.search_long_term_memory(
					query=memory_query,
					user_id=user_id,
					limit=config.memory_search_limit
				)
				
				memory_docs = [
					{
						"id": str(result.id),
						"score": float(result.score),
						"payload": result.payload or {},
						"source": "memory"
					}
					for result in memory_results
				]
				
				logger.info(f"Найдено {len(memory_docs)} документов в памяти пользователя")
				
			except Exception as e:
				logger.error(f"Ошибка поиска в памяти: {e}")
				memory_docs = []

		# Обновляем state с результатами поиска в памяти
		updated_meta = {
			**meta,
			"memory_docs": memory_docs
		}
		
		updated_state = {
			**state,
			"metadata": updated_meta
		}

		try:
			result_state = agent.process_state(updated_state)

			hints = result_state["metadata"].get("operator_hints", {})
			logger.info(
				"Подсказки для оператора сгенерированы",
				extra={
					"actions_count": len(hints.get("suggested_actions", [])),
					"has_template": bool(hints.get("response_template"))
				}
			)

			execution_time = time.time() - start_time
			logger.info(f"HintsGenerator завершил генерацию за {execution_time:.2f}с")
			return {
				"metadata": result_state.get("metadata", {}),
				"current_step": result_state.get("current_step", "hints_complete"),
			}

		except Exception as e:
			execution_time = time.time() - start_time
			logger.exception(f"Ошибка генерации подсказок за {execution_time:.2f}с", extra={"error": str(e)})
			return {
				"metadata": state.get("metadata", {}),
				"current_step": "hints_failed",
			}

	def _should_continue_iteration(self, state: AgentState) -> str:
		"""Routing функция: решает, нужно ли переформулировать запрос.

		Returns:
			"finder" - переформулировать запрос
			"hints_generator" - генерировать подсказки для оператора
		"""
		metadata = state.get("metadata", {})
		evaluation = metadata.get("controller_evaluation", {})

		needs_reformulation = evaluation.get("needs_reformulation", False)
		iteration = metadata.get("iteration_count", 0)

		if iteration > 5:
			logger.warning(f"Превышен аварийный лимит итераций ({iteration}), завершаем")
			return "hints_generator"

		if needs_reformulation:
			logger.info(f"Routing: переформулирование запроса (итерация {iteration})")
			return "finder"
		else:
			logger.info(f"Routing: результаты удовлетворительны, генерация подсказок (итераций: {iteration})")
			return "hints_generator"

	def _validator_node(self, state: AgentState) -> Dict[str, Any]:
		"""Узел валидатора: проверяет качество подсказок. Возвращает частичные обновления (metadata/current_step)."""
		import time
		start_time = time.time()
		
		from agent_system.agents.validator import ValidatorAgent

		agent = ValidatorAgent(llm=self.llm, model_name=self.model, max_attempts=2)

		try:
			result_state = agent.process_state(state)

			validation = result_state["metadata"].get("validator_result", {})
			logger.info(
				"Валидатор принял решение",
				extra={
					"acceptable": validation.get("is_acceptable", False),
					"needs_regeneration": validation.get("needs_regeneration", False)
				}
			)

			execution_time = time.time() - start_time
			logger.info(f"Validator завершил проверку за {execution_time:.2f}с")
			return {
				"metadata": result_state.get("metadata", {}),
				"current_step": result_state.get("current_step", "validator_complete"),
			}

		except Exception as e:
			execution_time = time.time() - start_time
			logger.exception(f"Ошибка работы валидатора за {execution_time:.2f}с", extra={"error": str(e)})
			return {
				"metadata": {
					**state.get("metadata", {}),
					"validator_result": {
						"is_acceptable": True,
						"needs_regeneration": False,
						"confidence": 0.0,
						"feedback": f"Ошибка валидатора: {str(e)}"
					}
				},
				"current_step": "validator_failed",
			}

	def _should_regenerate_hints(self, state: AgentState) -> str:
		"""Routing функция: решает, нужно ли регенерировать подсказки.
s
		Returns:
			"hints_generator" - регенерировать подсказки
			"__end__" - завершить обработку
		"""
		metadata = state.get("metadata", {})
		validation = metadata.get("validator_result", {})

		needs_regeneration = validation.get("needs_regeneration", False)
		attempt = metadata.get("hints_generation_attempt", 0)

		if attempt > 3:
			logger.warning(f"Превышен аварийный лимит попыток генерации ({attempt}), завершаем")
			return "__end__"

		if needs_regeneration:
			logger.info(f"Routing validator -> hints_generator: регенерация подсказок (попытка {attempt})")
			return "hints_generator"
		else:
			logger.info(f"Routing validator -> __end__: подсказки приемлемы (попыток: {attempt})")
			return "__end__"

	def build_workflow(self, use_validator: bool = None, use_controller: bool = None) -> None:
		"""Строит граф: Finder → (RAG || Memory) → ReRanker + Memory → [Controller] → HintsGenerator [→ Validator]."""
		
		use_controller = use_controller if use_controller is not None else config.use_controller
		use_validator = use_validator if use_validator is not None else config.use_validator
		
		self.app = build_graph(
			finder_node=self._finder_node,
			rag_node=self._rag_node,
			memory_node=self._memory_node,
			reranker_node=self._reranker_node,
			controller_node=self._controller_node if use_controller else None,
			hints_generator_node=self._hints_generator_node,
			validator_node=self._validator_node if use_validator else None,
			should_continue_after_controller=self._should_continue_iteration if use_controller else None,
			should_continue_after_validation=self._should_regenerate_hints if use_validator else None,
		)
		
		workflow_desc = "Finder → RAG → ReRanker"
		if use_controller:
			workflow_desc += " → Controller"
		workflow_desc += " → HintsGenerator"
		if use_validator:
			workflow_desc += " → Validator"
			
		logger.info(f"Рабочий процесс построен: {workflow_desc}")

	def process_request(self, user_request: str) -> Dict[str, Any]:
		"""Запускает обработку запроса и возвращает финальное состояние графа."""
		if not self.app:
			self.build_workflow()

		initial_state: AgentState = {
			"user_request": user_request,
			"messages": [],
			"current_step": "initial",
			"metadata": {
				"iteration_count": 0,
				"query_history": [],
				"hints_generation_attempt": 0,
				"hints_history": [],
				"validator_feedback_history": [],
				"user_id": 1,
			},
			"iteration_count": 0,
		}

		logger.info("Обработка запроса пользователя")

		config_dict = {"recursion_limit": 25}
		import time
		pipeline_start_time = time.time()
		final_state = self.app.invoke(initial_state, config=config_dict)
		pipeline_execution_time = time.time() - pipeline_start_time

		metadata = final_state.get("metadata", {})
		iterations = metadata.get("iteration_count", 0)
		controller_eval = metadata.get("controller_evaluation", {})

		logger.info(
			f"Обработка запроса завершена за {pipeline_execution_time:.2f}с",
			extra={
				"total_execution_time": pipeline_execution_time,
				"total_iterations": iterations,
				"final_satisfactory": controller_eval.get("is_satisfactory", False),
				"final_confidence": controller_eval.get("confidence", 0)
			}
		)

		return final_state

	def get_operator_hints(self, final_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
		"""Извлекает подсказки для оператора из финального состояния."""
		metadata = final_state.get("metadata", {})
		return metadata.get("operator_hints")
