"""
Document processor for creating fragments (chunks) for a RAG system.

Asynchronously processes text documents, breaking them down into semantic
fragments using an LLM and generating individual titles for each chunk.
Returns a data structure ready for loading into a knowledge_base collection,
accounting for the new knowledge source system and independent IDs.
"""

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from tqdm.asyncio import tqdm

from agent_system.utils.logger import logger


def return_system_promt() -> str:
    return """
        Ты - эксперт по обработке юридических документов (офферт) для системы поиска информации.

        Твоя задача:
        1. Улучшить читаемость и структуру текста
        2. Сохранить всю важную информацию из офферты
        3. Добавить контекст для лучшего понимания
        4. Выделить ключевые банковские термины и понятия
        5. Пиши только НА РУССКОМ ЯЗЫКЕ

        Правила:
        - Сохраняй точность финансовых данных
        - Улучшай структуру без потери смысла
        - Используй банковскую терминологию
        - Делай текст понятным для поиска
        - Сохраняй контекстный заголовок в начале текста
    """


def return_chunk_title_prompt() -> str:
    return """Проанализируй предоставленный фрагмент документа и создай для него
    специфические заголовки на русском языке.

        Твоя задача:
        1. Определить основную тему этого конкретного фрагмента.
        2. Создать краткий и точный заголовок (TITLE) для этого фрагмента на русском языке.
        3. Создать дополнительный подзаголовок (SUBTITLE), который должен быть развернутым и детальным.
        4. Все названия и тема должны быть НА РУССКОМ ЯЗЫКЕ

        Требования:
        - TITLE должен отражать именно содержание этого фрагмента, а не всего документа
        - SUBTITLE должен быть подробным и детально описывать содержание фрагмента
        - Используй конкретные термины из фрагмента
        - Заголовки должны быть уникальными для каждого фрагмента
        - Все заголовки должны быть на русском языке
        - Заголовки должны быть информативными и развернутыми

        Примеры хороших заголовков для фрагментов:
        - TITLE: "Определение налоговой базы для акцизов", SUBTITLE: "Расчет налоговой базы по акцизам на маркированные
        товары ЕАЭС при ввозе определяется на дату их принятия на учет"
        - TITLE: "Порядок возврата товаров", SUBTITLE: "Условия и процедура возврата товаров покупателем
        в соответствии с законодательством о защите прав потребителей"
        - TITLE: "Структура комиссионных сборов", SUBTITLE: "Детальное описание размеров комиссионных вознаграждений
        и условий их применения для различных категорий услуг"

        Формат ответа:
        TITLE: заголовок_фрагмента
        SUBTITLE: подробный_подзаголовок_фрагмента
    """


def return_chunk_content_prompt() -> str:
    return """
        Ты - эксперт по структурированию документов
        Твоя задача - разбить предоставленный документ на логические, семантически связанные чанки

        Требования к разбиению:
        1. Каждый чанк должен представлять законченную смысловую единицу
        2. Размер чанка: от 50 до 500 символов
        3. Сохраняй логическую структуру документа
        4. В начале каждого чанка добавь строку с контекстом (к какой главе/разделу/пункту относится текст)
        5. Текст в чанке НА РУССКОМ ЯЗЫКЕ

        Формат ответа:
        CHUNK_START
        КОНТЕКСТ: [Глава/Раздел/Пункт к которому относится текст]
        [Текст чанка]
        CHUNK_END

        CHUNK_START
        КОНТЕКСТ: [Следующий контекст]
        [Следующий текст чанка]
        CHUNK_END

        Пример контекстных заголовков:
        - "Глава 1. Общие положения"
        - "Раздел 2.1. Права и обязанности сторон"
        - "Пункт 3.2. Условия оплаты"
        - "Приложение А. Тарифы"

        Разбей документ на семантически правильные чанки:
    """


@dataclass
class ChunkingParams:
    """Configuration parameters for the document chunking process."""
    max_chunk_size: int = 3000
    min_chunk_size: int = 200
    semantic_chunking: bool = True


class AsyncDocumentProcessor:
    """Asynchronous processor for turning documents into chunks for a RAG system."""

    def __init__(
        self,
        api_key: str,
        model: str = "Qwen2.5-72B-Instruct-AWQ",
        temperature: float = 0.1,
        max_tokens: int = 4000,
        timeout: int = 150,
        chunking_params: Optional[ChunkingParams] = None,
        base_url: str = "https://llm.t1v.scibox.tech/v1",
        source: str = "Processed Document"
    ) -> None:
        """Initializes the AsyncDocumentProcessor.

        Args:
            api_key: The authentication key for the OpenRouter API.
            model: The name of the model for processing.
            temperature: The generation temperature.
            max_tokens: The maximum number of tokens in the response.
            timeout: The request timeout in seconds.
            chunking_params: Chunking configuration parameters.
            base_url: The OpenRouter API endpoint URL.
            source: The knowledge source for all documents.
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.chunking_params = chunking_params or ChunkingParams()
        self.base_url = base_url
        self.source = source

        self.llm = ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

        logger.info(f"AsyncDocumentProcessor initialized with model {self.model}")

    async def _process_single_chunk(
        self,
        chunk_text: str,
        chunk_index: int,
        total_chunks: int,
    ) -> Optional[Dict[str, Any]]:
        """Processes a single text chunk and returns a structure for the knowledge base."""
        if not chunk_text.strip():
            return None

        titles = await self._generate_chunk_titles(chunk_text, chunk_index, total_chunks)
        processing_prompt = f"""
        Process the following text, preserving key information and making it more structured:
        - Remove redundant words and repetitions.
        - Shorten the text while retaining its meaning.
        - Make the text more readable and informative.

        Text to process:
        {chunk_text}
        """

        processed_results = await self._send_llm_request(processing_prompt)

        processed_knowledge = processed_results[0].strip() if processed_results else chunk_text

        return {
            "knowledge": processed_knowledge,
            "title": titles.get("title", f"Section {chunk_index}"),
            "sub_title": titles.get("subtitle", f"Part {chunk_index} of {total_chunks}"),
            "source": self.source,
            "key": chunk_index
        }

    async def process_text_chunks(
        self,
        chunks: List[str],
        max_concurrent_tasks: int = 5
    ) -> List[Dict[str, Any]]:
        """Processes a list of text fragments and returns a structure for the knowledge base.

        Args:
            chunks: A list of text fragments to process.
            max_concurrent_tasks: The maximum number of concurrent tasks.

        Returns:
            A list of dictionaries with processed data for the knowledge base.
        """
        logger.info(f"Processing {len(chunks)} text chunks with {max_concurrent_tasks} concurrent tasks.")
        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        total_chunks = len(chunks)

        async def process_with_semaphore(chunk_text: str, i: int) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    return await self._process_single_chunk(chunk_text, i, total_chunks)
                except Exception as e:
                    logger.error(f"Error processing chunk {i}: {e}", exc_info=True)
                    return None

        tasks = [
            process_with_semaphore(chunk_text, i + 1)
            for i, chunk_text in enumerate(chunks)
            if chunk_text.strip()
        ]

        results = []
        for future in tqdm.as_completed(tasks, total=len(tasks), desc="Processing Chunks", unit="chunk"):
            result = await future
            if result:
                results.append(result)

        logger.info(f"Successfully processed {len(results)} chunks out of {len(chunks)}.")
        return results

    async def _send_llm_request(self, prompt: str) -> Optional[List[str]]:
        """Sends a request to the LLM via ChatOpenAI."""
        try:
            logger.debug(f"Sending LLM request with prompt: {prompt[:100]}...")
            resp = await self.llm.ainvoke([{"role": "user", "content": prompt}])
            raw_text = getattr(resp, "content", "") or (resp if isinstance(resp, str) else "")
            return [raw_text] if raw_text else None
        except Exception as e:
            logger.exception(f"Error during LLM request: {e}")
            return None

    async def _semantic_chunk_document(self, document_text: str) -> List[Dict[str, str]]:
        """Splits a document into semantic chunks using an LLM."""
        logger.debug("Performing semantic document chunking via LLM...")
        return self._fallback_chunking(document_text)

    def _parse_semantic_chunks(self, gpt_response: str) -> List[Dict[str, str]]:
        """Parses the LLM response containing semantic chunks."""
        chunks = []
        chunk_pattern = r"CHUNK_START\s*\n(.*?)\nCHUNK_END"
        matches = re.findall(chunk_pattern, gpt_response, re.DOTALL)

        if not matches:
            logger.warning("CHUNK_START/CHUNK_END markers not found, trying alternative parsing.")
            return self._parse_alternative_format(gpt_response)

        for match in matches:
            lines = match.strip().split("\n")
            context_header = ""
            chunk_text_lines = []
            header_found = False

            for line in lines:
                if line.lower().startswith("контекст:"):
                    context_header = line.split(":", 1)[1].strip()
                    header_found = True
                    break

            content_started = not header_found
            for line in lines:
                if header_found and line.lower().startswith("контекст:"):
                    content_started = True
                    continue
                if content_started:
                    chunk_text_lines.append(line)

            chunk_text = "\n".join(chunk_text_lines).strip()

            if len(chunk_text) >= self.chunking_params.min_chunk_size:
                chunks.append({"context_header": context_header, "text": chunk_text})

        if not chunks:
            logger.warning("Could not extract any valid chunks, using fallback chunking.")
            return self._fallback_chunking_with_context(gpt_response)

        logger.info(f"Extracted {len(chunks)} semantic chunks.")
        return chunks

    def _parse_alternative_format(self, gpt_response: str) -> List[Dict[str, str]]:
        """Alternative parsing if the main format is not found (e.g., numbered lists)."""
        chunks = []
        chunk_parts = re.split(r"\n(?=\d+\.)", gpt_response)

        for part in chunk_parts:
            if not part.strip():
                continue

            lines = part.strip().split("\n")
            context_header = ""
            for line in lines[:3]:
                if any(kw in line.lower() for kw in ["глава", "раздел", "пункт"]):
                    context_header = line.strip()
                    break

            chunk_text = part.strip()
            if len(chunk_text) >= self.chunking_params.min_chunk_size:
                chunks.append({
                    "context_header": context_header or "Document Section",
                    "text": chunk_text
                })

        return chunks

    def _fallback_chunking(self, document_text: str) -> List[Dict[str, str]]:
        """Fallback chunking by paragraph if LLM-based methods fail."""
        logger.info("Using fallback paragraph-based chunking.")
        chunks = []
        paragraphs = document_text.split("\n\n")
        current_chunk = ""
        chunk_index = 1

        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 <= self.chunking_params.max_chunk_size:
                current_chunk += paragraph + "\n\n"
            else:
                if current_chunk.strip():
                    chunks.append({
                        "context_header": f"Section {chunk_index}",
                        "text": current_chunk.strip()
                    })
                    chunk_index += 1
                current_chunk = paragraph + "\n\n"

        if current_chunk.strip():
            chunks.append({
                "context_header": f"Section {chunk_index}",
                "text": current_chunk.strip()
            })

        return chunks

    def _fallback_chunking_with_context(self, text: str) -> List[Dict[str, str]]:
        """Fallback chunking by word count with a simple context attempt."""
        logger.info("Using fallback word-based chunking.")
        chunks = []
        words = text.split()
        current_chunk = ""
        chunk_index = 1

        for word in words:
            if len(current_chunk) + len(word) + 1 <= self.chunking_params.max_chunk_size:
                current_chunk += word + " "
            else:
                if current_chunk.strip():
                    chunks.append({
                        "context_header": f"Document Part {chunk_index}",
                        "text": current_chunk.strip()
                    })
                    chunk_index += 1
                current_chunk = word + " "

        if current_chunk.strip():
            chunks.append({
                "context_header": f"Document Part {chunk_index}",
                "text": current_chunk.strip()
            })

        return chunks

    async def _generate_chunk_titles(self, chunk_text: str, chunk_index: int, total_chunks: int) -> Dict[str, str]:
        """Generates high-quality titles for a chunk using an LLM."""
        title_prompt = f"""
        Analyze the following text and create a concise, informative title (2-7 words).
        The title should reflect the main topic or key information from the text.

        Text: {chunk_text[:500]}...

        RESPONSE FORMAT:
        TITLE: [your title]
        """

        subtitle_prompt = f"""
        Create a brief description (1-2 sentences) for section "{chunk_index}" of a document.
        The description should help understand the section's content and its relation to the rest of the document.

        Context: Section {chunk_index} of {total_chunks} parts of the document.
        Section text: {chunk_text[:300]}...

        RESPONSE FORMAT:
        SUBTITLE: [your description]
        """

        try:
            title_task = self._send_llm_request(title_prompt)
            subtitle_task = self._send_llm_request(subtitle_prompt)

            title_results, subtitle_results = await asyncio.gather(title_task, subtitle_task)

            title = f"Document Section {chunk_index}"
            if title_results:
                title_response = title_results[0].strip()
                match = re.search(r"TITLE:\s*(.*)", title_response, re.IGNORECASE)
                title = match.group(1).strip()[:100] if match else title_response.strip()[:100]

            subtitle = f"Part {chunk_index} of {total_chunks}"
            if subtitle_results:
                subtitle_response = subtitle_results[0].strip()
                match = re.search(r"SUBTITLE:\s*(.*)", subtitle_response, re.IGNORECASE)
                subtitle = match.group(1).strip()[:200] if match else subtitle_response.strip()[:200]

            return {"title": title, "subtitle": subtitle}

        except Exception as e:
            logger.warning(f"Error generating titles via LLM: {e}", exc_info=True)
            return {
                "title": f"Section {chunk_index}",
                "subtitle": f"Part {chunk_index} of {total_chunks}"
            }


async def process_text_chunks(
    text_chunks: List[str],
    source: str = "Processed Document",
    api_key: Optional[str] = None,
    chunking_params: Optional[ChunkingParams] = None
) -> List[Dict[str, Any]]:
    """Processes an array of text chunks and returns data for the knowledge base.

    Args:
        text_chunks: A list of text fragments to process.
        source: The knowledge source for all documents.
        api_key: The API key (if not provided, it's taken from the environment).
        chunking_params: Optional chunking parameters.

    Returns:
        A list of dictionaries with processed data for the knowledge base.
    """
    resolved_api_key = api_key or os.getenv("SCIBOX_API_KEY")
    if not resolved_api_key:
        logger.error("API key not found. Please provide it or set the OPENROUTER_API_KEY environment variable.")
        return []

    params = chunking_params or ChunkingParams(
        max_chunk_size=500,
        min_chunk_size=50,
        semantic_chunking=True
    )

    processor = AsyncDocumentProcessor(
        api_key=resolved_api_key,
        chunking_params=params,
        source=source
    )

    try:
        return await processor.process_text_chunks(chunks=text_chunks)
    except Exception as e:
        logger.exception(f"An error occurred during text chunk processing: {e}")
        return []
