"""
Controller for interacting with the Qdrant vector database.

Implements hybrid search combining dense and sparse vectors, and manages
knowledge and memory collections.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union, Tuple, Sequence

import spacy
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import PointStruct, SparseVector
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from agent_system.utils.logger import logger

import numpy as np
import torch
from transformers import PreTrainedModel, PreTrainedTokenizerBase

try:
    from tqdm import tqdm as _tqdm
except Exception:
    _tqdm = None


def _mean_pool(hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """
    Mean pooling over token embeddings, considering attention mask.
    
    Args:
        hidden_states: Token embeddings [batch_size, seq_len, hidden_dim]
        attention_mask: Attention mask [batch_size, seq_len]
    
    Returns:
        Pooled embeddings [batch_size, hidden_dim]
    """
    mask_expanded = attention_mask.unsqueeze(-1).expand(hidden_states.size()).float()
    sum_embeddings = torch.sum(hidden_states * mask_expanded, dim=1)
    sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    return sum_embeddings / sum_mask


def _l2_normalize_torch(tensor: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    """
    L2 normalization for torch tensors.
    
    Args:
        tensor: Input tensor to normalize
        eps: Small epsilon to avoid division by zero
    
    Returns:
        L2-normalized tensor
    """
    norm = torch.norm(tensor, p=2, dim=-1, keepdim=True)
    return tensor / torch.clamp(norm, min=eps)


def _nullcontext():
    """Null context manager for compatibility."""
    from contextlib import nullcontext
    return nullcontext()


class BertSentenceEncoder:
    """
    Обёртка над (BERT-модель, токенайзер), совместимая по интерфейсу с SentenceTransformer.encode().

    Поддержка:
      - pooling: "mean" (по токенам с маской) или "cls" (pooler_output при наличии)
      - L2-нормализация
      - батч-инференс, прогресс-бар
      - float16 autocast на CUDA (опционально)

    Пример:
        model, tokenizer = load_deeppavlov_bert(...)
        encoder = BertSentenceEncoder((model, tokenizer), device="cuda", pooling="mean")
        vec = encoder.encode("Привет, мир!")                  # -> np.ndarray (768,)
        vecs = encoder.encode(["a", "b"], batch_size=32)       # -> np.ndarray (2, 768)
    """

    def __init__(
        self,
        model_and_tokenizer: Tuple[PreTrainedModel, PreTrainedTokenizerBase],
        device: Optional[str] = None,
        pooling: str = "mean",
        normalize: bool = True,
        max_length: int = 256,
        default_batch_size: int = 32,
        use_fp16: bool = True,
        pad_to_multiple_of: Optional[int] = 8,
    ) -> None:
        model, tokenizer = model_and_tokenizer
        self.model: PreTrainedModel = model
        self.tokenizer: PreTrainedTokenizerBase = tokenizer

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        self.pooling = pooling.lower()
        assert self.pooling in {"mean", "cls"}, "pooling должен быть 'mean' или 'cls'"

        self.normalize = normalize
        self.max_length = int(max_length)
        self.default_batch_size = int(default_batch_size)
        self.use_fp16 = bool(use_fp16 and self.device.type == "cuda")
        self.pad_to_multiple_of = pad_to_multiple_of

        self.model.to(self.device)
        self.model.eval()

    @torch.no_grad()
    def encode(
        self,
        sentences: Union[str, Sequence[str]],
        batch_size: Optional[int] = None,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        **_: dict,
    ) -> Union[np.ndarray, torch.Tensor]:
        """Вернёт массив эмбеддингов: (N, D) или (D,) для одиночной строки."""
        single_input = isinstance(sentences, str)
        if single_input:
            sentences = [sentences]

        sentences = list(sentences)
        if len(sentences) == 0:
            out = np.zeros((0, self.get_sentence_embedding_dimension()), dtype="float32")
            return out if convert_to_numpy else torch.from_numpy(out)

        bs = batch_size or self.default_batch_size
        rng = range(0, len(sentences), bs)

        if show_progress_bar and _tqdm is not None:
            rng = _tqdm(rng, desc="Encoding (BERT)")

        chunks = []
        amp_ctx = torch.cuda.amp.autocast if self.use_fp16 else _nullcontext

        for i in rng:
            batch = sentences[i : i + bs]
            toks = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
                pad_to_multiple_of=self.pad_to_multiple_of,
            )
            toks = {k: v.to(self.device) for k, v in toks.items()}

            with amp_ctx():
                outputs = self.model(**toks, return_dict=True)
                if self.pooling == "cls" and getattr(outputs, "pooler_output", None) is not None:
                    pooled = outputs.pooler_output  # [B, H]
                else:
                    pooled = _mean_pool(outputs.last_hidden_state, toks["attention_mask"])  # [B, H]

            pooled = pooled.detach().to("cpu", dtype=torch.float32)

            if self.normalize:
                pooled = _l2_normalize_torch(pooled)

            chunks.append(pooled)

        embs = torch.vstack(chunks)

        if single_input:
            embs = embs[0]

        if convert_to_numpy:
            return embs.numpy()
        return embs

    def __call__(self, *args, **kwargs):
        return self.encode(*args, **kwargs)

    def get_sentence_embedding_dimension(self) -> int:
        """Размерность эмбеддинга (обычно hidden_size модели)."""
        hidden = getattr(getattr(self.model, "config", None), "hidden_size", None)
        if hidden:
            return int(hidden)
        v = self.encode("ping", batch_size=1, show_progress_bar=False)
        return int(np.asarray(v).reshape(-1).shape[0])


class SparseEncoder:
    """Encoder for creating sparse vectors based on BM25.

    It is trained on a corpus of documents and transforms text into a vector
    where word weights are calculated using a TF-IDF scheme.
    """

    def __init__(self, corpus: List[str]) -> None:
        """Initializes the encoder based on a document corpus."""
        logger.info(f"Initializing SparseEncoder on a corpus of {len(corpus)} documents.")
        try:
            self.nlp = spacy.load("ru_core_news_sm")
        except OSError:
            logger.error("SpaCy 'ru_core_news_sm' not found. Please run 'python -m spacy download ru_core_news_sm'")
            raise
        tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        self.bm25 = BM25Okapi(tokenized_corpus)
        self.word_to_idx = {word: i for i, word in enumerate(self.bm25.idf.keys())}
        logger.info("SparseEncoder is ready.")

    def _tokenize(self, text: str) -> List[str]:
        """Tokenizes and lemmatizes text, removing stop words and punctuation."""
        return [
            token.lemma_.lower()
            for token in self.nlp(text)
            if not token.is_punct and not token.is_stop
        ]

    def encode(self, text: str) -> SparseVector:
        """Encodes text into a sparse vector for Qdrant.

        Args:
            text: The text to encode.

        Returns:
            A sparse vector with word indices and weights.
        """
        tokenized_text = self._tokenize(text)
        if not tokenized_text:
            return SparseVector(indices=[], values=[])

        tf_counts = Counter(tokenized_text)
        indices, values = [], []
        for word, tf in tf_counts.items():
            if word in self.word_to_idx:
                idf = self.bm25.idf.get(word, 0)
                weight = tf * idf
                indices.append(self.word_to_idx[word])
                values.append(float(weight))

        if not indices:
            return SparseVector(indices=[], values=[])

        # Qdrant requires sorted indices
        sorted_pairs = sorted(zip(indices, values))
        sorted_indices = [p[0] for p in sorted_pairs]
        sorted_values = [p[1] for p in sorted_pairs]

        return SparseVector(indices=sorted_indices, values=sorted_values)


class RetrieverController:
    """Controller for managing search in Qdrant with a hybrid approach.

    Implements a combination of dense and sparse search using Reciprocal
    Rank Fusion to merge the results.
    """

    def __init__(
        self,
        client: QdrantClient,
        dense_encoder: SentenceTransformer,
        sparse_encoder: Optional[SparseEncoder] = None,
    ) -> None:
        """Initializes the search controller.

        Args:
            client: The client for connecting to Qdrant.
            dense_encoder: The model for creating dense vectors.
            sparse_encoder: An optional encoder for sparse vectors.
        """
        self.client = client
        self.dense_encoder = BertSentenceEncoder(dense_encoder)
        self.sparse_encoder = sparse_encoder
        self.kb_collection = "knowledge_base"
        self.ltm_collection = "long_term_memory"
        logger.info("RetrieverController initialized.")

    def add_to_knowledge_base(self, documents: List[Dict[str, str]], source: str) -> None:
        """Adds documents to the knowledge base.

        Args:
            documents: A list of document dictionaries to add.
            source: The source of the knowledge.
        """
        if not self.sparse_encoder:
            logger.error("SparseEncoder is not provided, cannot add to knowledge base.")
            raise ValueError("SparseEncoder must be provided to work with the knowledge base.")

        try:
            initial_count = self.client.count(collection_name=self.kb_collection, exact=True).count
        except Exception:
            initial_count = 0

        points_to_upsert: List[PointStruct] = []
        for i, doc in enumerate(documents):
            doc_id = initial_count + 1 + i
            document_payload = {
                "knowledge": doc["knowledge"],
                "title": doc["title"],
                "sub_title": doc["sub_title"],
                "source": source,
                "id": doc_id,
            }

            dense_vector = self.dense_encoder.encode(document_payload["knowledge"], show_progress_bar=False)
            sparse_vector = self.sparse_encoder.encode(document_payload["knowledge"])

            points_to_upsert.append(PointStruct(
                id=doc_id,
                vector={"default": dense_vector.tolist(), "bm25": sparse_vector},
                payload=document_payload,
            ))

        if points_to_upsert:
            self.client.upsert(collection_name=self.kb_collection, points=points_to_upsert, wait=True)
            logger.info(f"Upserted {len(points_to_upsert)} documents from source '{source}' to knowledge base.")

    def search_knowledge_base(self, query: str, limit: int = 5) -> List[models.ScoredPoint]:
        """Performs a hybrid search in the knowledge base.

        Args:
            query: The search query.
            limit: The maximum number of results to return.

        Returns:
            A sorted list of search results.
        """
        if not self.sparse_encoder:
            logger.error("SparseEncoder is not provided, cannot search knowledge base.")
            raise ValueError("SparseEncoder must be provided for knowledge base search.")

        logger.debug(f"Searching knowledge base for query: '{query[:50]}...' with limit {limit}")
        dense_vector = self.dense_encoder.encode(query).tolist()
        sparse_vector = self.sparse_encoder.encode(query)

        dense_request = models.SearchRequest(
            vector=models.NamedVector(name="default", vector=dense_vector),
            limit=limit, with_payload=True
        )
        sparse_request = models.SearchRequest(
            vector=models.NamedSparseVector(name="bm25", vector=sparse_vector),
            limit=limit, with_payload=True
        )

        dense_results, sparse_results = self.client.search_batch(
            collection_name=self.kb_collection, requests=[dense_request, sparse_request]
        )

        fused_results = self._reciprocal_rank_fusion([dense_results, sparse_results], limit)
        logger.debug(f"Found {len(fused_results)} results after RRF.")
        return fused_results

    def search_knowledge_base_dense(self, query: str, limit: int = 5) -> List[models.ScoredPoint]:
        """Performs a dense-only vector search in the knowledge base.

        Args:
            query: The search query.
            limit: The maximum number of results to return.

        Returns:
            A sorted list of search results.
        """
        logger.debug(f"Performing dense-only search in KB for query: '{query[:50]}...' with limit {limit}")
        dense_vector = self.dense_encoder.encode(query).tolist()

        search_results = self.client.search(
            collection_name=self.kb_collection,
            query_vector=models.NamedVector(name="default", vector=dense_vector),
            limit=limit,
            with_payload=True
        )

        logger.debug(f"Found {len(search_results)} results from dense-only search.")
        return search_results

    def _reciprocal_rank_fusion(
        self, result_lists: List[List[models.ScoredPoint]], limit: int, k: int = 60
    ) -> List[models.ScoredPoint]:
        """Merges search result lists using the RRF algorithm."""
        rrf_scores: Dict[Union[int, str], float] = defaultdict(float)
        point_data: Dict[Union[int, str], models.ScoredPoint] = {}

        for results in result_lists:
            for rank, point in enumerate(results):
                if point.id not in point_data:
                    point_data[point.id] = point
                rrf_scores[point.id] += 1.0 / (k + rank + 1)

        sorted_ids = sorted(rrf_scores.keys(), key=lambda doc_id: rrf_scores[doc_id], reverse=True)

        final_results = []
        for doc_id in sorted_ids[:limit]:
            point = point_data[doc_id]
            point.score = rrf_scores[doc_id]
            final_results.append(point)

        return final_results

    def add_to_long_term_memory(self, memories: List[Dict[str, Any]]) -> None:
        """Adds records to long-term memory.

        Args:
            memories: A list of memory records to save.
        """
        try:
            initial_count = self.client.count(collection_name=self.ltm_collection, exact=True).count
        except Exception:
            initial_count = 0

        for i, memory in enumerate(memories):
            if "timestamp" not in memory:
                memory["timestamp"] = datetime.now(timezone.utc).isoformat()
            if "id" not in memory:
                memory["id"] = initial_count + 1 + i

        texts = [mem["knowledge"] for mem in memories]
        vectors = self.dense_encoder.encode(texts, show_progress_bar=False)

        points = [
            PointStruct(id=mem["id"], vector=vector.tolist(), payload=mem)
            for mem, vector in zip(memories, vectors)
        ]

        if points:
            self.client.upsert(collection_name=self.ltm_collection, points=points, wait=True)
            logger.info(f"Added {len(points)} records to long-term memory.")

    def search_long_term_memory(self, query: str, user_id: Union[str, int], limit: int = 3) -> List[models.ScoredPoint]:
        """Searches long-term memory with a filter for the user.

        Args:
            query: The search query.
            user_id: The user identifier to filter by.
            limit: The maximum number of results.

        Returns:
            A list of search results filtered by user.
        """
        logger.debug(f"Searching LTM for user '{user_id}' with query: '{query[:50]}...'" )
        query_vector = self.dense_encoder.encode(query).tolist()
        user_filter = models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
        )

        search_results, = self.client.search_batch(
            collection_name=self.ltm_collection,
            requests=[
                models.SearchRequest(
                    vector=query_vector,
                    filter=user_filter,
                    limit=limit,
                    with_payload=True,
                )
            ]
        )
        logger.debug(f"Found {len(search_results)} results in LTM for user '{user_id}'.")
        return search_results

    def delete_knowledge_by_id(self, knowledge_id: int) -> bool:
        """Deletes a record from the knowledge base by its ID.

        Args:
            knowledge_id: The ID of the record to delete.

        Returns:
            True if the record was deleted, False otherwise.
        """
        logger.info(f"Attempting to delete knowledge record with ID: {knowledge_id}")
        try:
            result = self.client.delete(
                collection_name=self.kb_collection,
                points_selector=models.PointIdsList(points=[knowledge_id]),
                wait=True
            )

            if result.status == models.UpdateStatus.COMPLETED:
                logger.info(f"Record with ID {knowledge_id} deleted from knowledge base.")
                return True

            logger.warning(f"Failed delete record with ID {knowledge_id} from knowledge base. Status: {result.status}")
            return False

        except Exception as e:
            logger.exception(f"Error deleting record with ID {knowledge_id} from knowledge base: {e}")
            return False

    def delete_memory_by_id(self, memory_id: int) -> bool:
        """Deletes a record from long-term memory by its ID.

        Args:
            memory_id: The ID of the record to delete.

        Returns:
            True if the record was deleted, False otherwise.
        """
        logger.info(f"Attempting to delete memory record with ID: {memory_id}")
        try:
            result = self.client.delete(
                collection_name=self.ltm_collection,
                points_selector=models.PointIdsList(points=[memory_id]),
                wait=True
            )

            if result.status == models.UpdateStatus.COMPLETED:
                logger.info(f"Record with ID {memory_id} deleted from long-term memory.")
                return True

            logger.warning(f"Failed delete record with ID {memory_id} from long-term memory. Status: {result.status}")
            return False

        except Exception as e:
            logger.exception(f"Error deleting record with ID {memory_id} from long-term memory: {e}")
            return False

    def clear_knowledge_base(self) -> None:
        """Clears the entire knowledge base."""
        logger.warning("Clearing the entire knowledge base.")
        try:
            self.client.delete(
                collection_name=self.kb_collection,
                points_selector=models.FilterSelector(filter=models.Filter()),
                wait=True
            )
            logger.info("Knowledge base cleared successfully.")
        except Exception as e:
            logger.exception(f"Error clearing the knowledge base: {e}")

    def clear_long_term_memory(self) -> None:
        """Clears the entire long-term memory."""
        logger.warning("Clearing the entire long-term memory.")
        try:
            self.client.delete(
                collection_name=self.ltm_collection,
                points_selector=models.FilterSelector(filter=models.Filter()),
                wait=True
            )
            logger.info("Long-term memory cleared successfully.")
        except Exception as e:
            logger.exception(f"Error clearing the long-term memory: {e}")
