import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class AgentSystemConfig:
    model: str = "Qwen2.5-72B-Instruct-AWQ"
    temperature: float = 0.2
    base_url: str = "https://llm.t1v.scibox.tech/v1"
    api_key: str = os.getenv("SCIBOX_API_KEY", "")
    request_timeout_seconds: int = 30  
    llm_max_retries: int = 1  
    max_tokens: int = 1024  
    delay_between_requests: float = 0.1  
    retry_delay: float = 1.0 

    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    knowledge_base_collection: str = "knowledge_base"
    long_term_memory_collection: str = "long_term_memory"

    dense_model_name: str = os.getenv("DENSE_MODEL", "bge-m3")
    sparse_model_name: str = os.getenv("SPARSE_MODEL", "bm25")

    rag_search_limit: int = 7
    memory_search_limit: int = 3
    
    use_controller: bool = True
    use_validator: bool = True

    def validate(self) -> bool:
        if not self.api_key:
            raise ValueError(
                "SCIBOX_API_KEY не найден в переменных окружения. "
                "Пожалуйста, создайте файл .env и добавьте ваш API ключ."
            )
        return True


config = AgentSystemConfig()
config.validate()
