import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Sequence

import dotenv
import pandas as pd
from fastapi import Body, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from agent_system.memory.memory_controller import MemoryController
from agent_system.rag.controller import RetrieverController, SparseEncoder
from agent_system.rag.fragments_creator import process_text_chunks
from agent_system.system import SupportAgentSystem
from agent_system.utils.logger import logger
from agent_system.utils.model_loader import load_deeppavlov_bert
from agent_system.utils.category_predictor import predict_category_and_subcategory

dotenv.load_dotenv()
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# --- Pydantic Models ---
class DialogueMessage(BaseModel):
    """Represents a single message in a dialogue."""
    role: Literal["client", "operator"]
    content: str

class AssistRequest(BaseModel):
    """Request model for the /assist endpoint."""
    user_request: str = Field(..., description="The user's current request")
    last_messages: Optional[List[DialogueMessage]] = Field(default=None,
    description="Up to 10 recent dialogue messages")

class RankedFragment(BaseModel):
    """Represents a ranked document fragment."""
    id: str
    score: Optional[float] = None
    payload: Dict[str, Any]

class AssistResponse(BaseModel):
    """Response model for the /assist endpoint."""
    hints: Dict[str, Any]
    relevant_docs: List[RankedFragment]
    debug: Optional[Dict[str, Any]] = None

class DialogueMessageMemory(BaseModel):
    """Represents a single message in a dialogue."""
    role: str = Field(..., description="The role of the speaker (e.g., 'user', 'operator').")
    content: str = Field(..., description="The content of the message.")


class MemorizeRequest(BaseModel):
    """Defines the structure for the /memorize/ endpoint request."""
    user_id: int = Field(..., description="The unique identifier for the user.")
    dialogue: Sequence[DialogueMessageMemory] = Field(..., description="The sequence of messages in the dialogue.")


class SlicingRequest(BaseModel):
    """Defines the structure for the /slice-document/ endpoint request."""
    text_chunks: Sequence[str] = Field(..., description="A sequence of text chunks from the document.")
    source: str = Field(..., description="The name of the source document.")


class SearchRequest(BaseModel):
    """Defines the structure for the /search endpoint request."""
    query: str = Field(..., description="The search query text.")


class SearchResponse(BaseModel):
    """Response model for the /search endpoint."""
    document: Optional[RankedFragment] = Field(None, description="The most relevant document, if found.")
    message: Optional[str] = Field(None, description="Message if no documents found.")


class CategoryPredictRequest(BaseModel):
    """Request model for the /classifier endpoint."""
    question: str = Field(..., description="The question text to classify.")


class CategoryPredictResponse(BaseModel):
    """Response model for the /classifier endpoint."""
    main_category: str = Field(..., description="Predicted main category.")
    subcategory: str = Field(..., description="Predicted subcategory.")


# --- FastAPI Application Setup ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initializes the SupportAgentSystem during application startup."""
    global _system
    logger.info("Starting up the support agent system...")
    api_key = os.getenv("SCIBOX_API_KEY", "").strip()
    if not api_key:
        logger.error("SCIBOX_API_KEY is not set.")
        raise RuntimeError(
            "SCIBOX_API_KEY is not set. "
            "Please set the environment variable with your OpenRouter API key."
        )

    _system = SupportAgentSystem(api_key=api_key)
    _system.build_workflow()
    logger.info("Support agent system initialized and workflow built.")
    yield


app = FastAPI(
    title="Support Hints Agent API",
    description="API for managing the agent system's memory and other functions.",
    version="1.0.0",
    lifespan=lifespan,
)

# --- Controllers Initialization ---
retriever_controller = None
memory_controller = None
_system: Optional[SupportAgentSystem] = None

try:
    df = pd.read_excel("agent_system/service/smart_support_vtb_belarus_faq_final.xlsx")
    placeholder_corpus = (df["Пример вопроса"] + " " + df["Шаблонный ответ"]).tolist()
    qdrant_client = QdrantClient(host="localhost", port=6333)
    dense_encoder = load_deeppavlov_bert()
    sparse_encoder = SparseEncoder(corpus=placeholder_corpus)
    retriever_controller = RetrieverController(client=qdrant_client,
    dense_encoder=dense_encoder, sparse_encoder=sparse_encoder)

    api_key = os.environ["SCIBOX_API_KEY"]
    memory_controller = MemoryController(api_key=api_key, rag_controller=retriever_controller)

except KeyError:
    print("Warning: SCIBOX_API_KEY environment variable not set. MemoryController is disabled.")
except Exception as e:
    print(f"Error: Failed to initialize controllers: {e}. Endpoints will be disabled.")


# --- API Endpoints ---
@app.post("/memorize")
def memorize_dialogue(request: MemorizeRequest = Body(...)) -> Dict[str, Any]:  # noqa: B008
    """
    Extracts knowledge from a dialogue, handles deduplication, and stores it.
    """
    if memory_controller is None or retriever_controller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controllers are not available. Check server logs for details."
        )

    try:
        dialogue_dicts = [msg.model_dump() for msg in request.dialogue]
        new_knowledge = memory_controller.extract_and_validate(
            dialogue=dialogue_dicts,
            user_id=request.user_id
        )

        if new_knowledge:
            knowledge_to_save = [item.model_dump() for item in new_knowledge]
            retriever_controller.add_to_long_term_memory(knowledge_to_save)
            return {"message": f"{len(new_knowledge)} new knowledge items have been successfully saved."}

        return {"message": "Dialogue processed. No new unique knowledge was found to save."}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during dialogue processing: {e}"
        ) from e


@app.post("/slice-document")
async def slice_document(request: SlicingRequest = Body(...)) -> Dict[str, Any]:  # noqa: B008
    """
    Processes text chunks, creates knowledge fragments, and saves them to the knowledge base.
    """
    if retriever_controller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RetrieverController is not available. Check server logs for details."
        )

    try:
        processed_fragments = await process_text_chunks(
            text_chunks=list(request.text_chunks),
            source=request.source
        )

        if not processed_fragments:
            return {"message": "Document processed, but no valid fragments were created."}

        retriever_controller.add_to_knowledge_base(
            documents=processed_fragments,
            source=request.source
        )

        return {"message": f"{len(processed_fragments)} new knowledge fragments from '{request.source}' saved."}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during document slicing: {e}"
        ) from e


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """Searches the knowledge base and returns the most relevant document.

    This endpoint performs a hybrid search (dense + sparse) in the knowledge base
    and returns only the top-1 most relevant document.

    Args:
        request: The search request containing the query text.

    Returns:
        A SearchResponse with the most relevant document or a message if none found.
    """
    if retriever_controller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RetrieverController is not available. Check server logs for details."
        )

    try:
        logger.info(f"Received search request: '{request.query[:50]}...'")

        search_results = retriever_controller.search_knowledge_base(query=request.query, limit=1)

        if not search_results:
            logger.info("No documents found for the query.")
            return SearchResponse(document=None, message="No relevant documents found.")

        top_result = search_results[0]

        document = RankedFragment(
            id=str(top_result.id),
            score=float(top_result.score) if top_result.score is not None else None,
            payload=top_result.payload or {}
        )

        logger.info(f"Returning top document with ID: {document.id}, score: {document.score}")
        return SearchResponse(document=document, message=None)

    except Exception as e:
        logger.exception("An unexpected error occurred in /search endpoint.")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/assist", response_model=AssistResponse)
async def assist(request: AssistRequest) -> AssistResponse:
    """Handles operator assistance requests.

    This endpoint takes the current user request and up to 10 recent messages,
    and returns hints for the operator and relevant documents.

    Args:
        request: The assistance request containing user input.

    Returns:
        An AssistResponse with hints, documents, and debug info.
    """
    if _system is None:
        logger.error("System not initialized before /assist call.")
        raise HTTPException(status_code=503, detail="System not initialized")

    try:
        logger.info(f"Received assist request for: '{request.user_request[:50]}...'",
        extra={"user_request": request.user_request})

        _ = (request.last_messages or [])[-10:]

        final_state = _system.process_request(user_request=request.user_request)
        hints = _system.get_operator_hints(final_state) or {}

        hints_clean = {k: v for k, v in hints.items() if k != "relevant_docs"}
        meta = final_state.get("metadata", {}) or {}
        reranked = meta.get("rag_docs_reranked", []) or []

        docs_out: List[RankedFragment] = []
        for d in reranked[:3]:
            try:
                score_val = d.get("score")
                docs_out.append(RankedFragment(
                    id=str(d.get("id")),
                    score=float(score_val) if score_val is not None else None,
                    payload=d.get("payload", {}) or {}
                ))
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse document fragment: {d}. Error: {e}")

        debug_info = {
            "iteration_count": meta.get("iteration_count"),
            "controller_satisfactory": (meta.get("controller_evaluation", {}) or {}).get("is_satisfactory"),
        }

        logger.info(f"Returning {len(hints_clean)} hints and {len(docs_out)} relevant documents.")
        return AssistResponse(hints=hints_clean, relevant_docs=docs_out, debug=debug_info)

    except Exception as e:
        logger.exception("An unexpected error occurred in /assist endpoint.")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/classifier", response_model=CategoryPredictResponse)
async def classifier(request: CategoryPredictRequest) -> CategoryPredictResponse:
    """Predicts main category and subcategory for a given question.

    This endpoint uses fine-tuned DeepPavlov BERT models to classify
    the question into a main category and then into a subcategory.

    Args:
        request: The classification request containing the question.

    Returns:
        A CategoryPredictResponse with predicted categories.
    """
    try:
        logger.info(f"Received classification request: '{request.question[:50]}...'")
        
        main_cat, sub_cat = predict_category_and_subcategory(request.question)
        
        logger.info(f"Predicted: main='{main_cat}', sub='{sub_cat}'")
        return CategoryPredictResponse(
            main_category=main_cat,
            subcategory=sub_cat
        )
    
    except ValueError as e:
        logger.warning(f"Validation error in /classifier: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("An unexpected error occurred in /classifier endpoint.")
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server with uvicorn.")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
    except Exception as e:
        logger.exception("An unexpected error occurred while starting the FastAPI server.")
        raise SystemExit(str(e)) from e
