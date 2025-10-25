import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoModel, AutoTokenizer


# def load_embedder(local_dir: str = "agent_system/models/embedder_old",
#                   device: str | None = None) -> SentenceTransformer:
#     """
#     Загрузка локальной Sentence-Transformers модели из папки.
#     :param local_dir: Путь к локальной папке модели (HF snapshot/репозиторий).
#     :param device: 'cuda', 'cpu' или None для авто-выбора.
#     :return: SentenceTransformer
#     """
#     if device is None:
#         device = "cuda" if torch.cuda.is_available() else "cpu"
#     model = SentenceTransformer(local_dir, device=device)
#     return model


def load_deeppavlov_bert(
    model_name: str = "DeepPavlov/rubert-base-cased",
    local_dir: str = "agent_system/models/finetuned_retriever",
    device: str | None = None
) -> tuple[AutoModel, AutoTokenizer]:
    """
    Загрузка DeepPavlov BERT модели и токенизатора.
    
    :param model_name: Название модели на Hugging Face (по умолчанию DeepPavlov/rubert-base-cased)
    :param local_dir: Путь к локальной папке модели. Если None, загружается из Hugging Face
    :param device: 'cuda', 'cpu' или None для авто-выбора
    :return: Кортеж (model, tokenizer)
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Определяем откуда загружать: локально или из HF
    source = local_dir if local_dir else model_name
    
    print(f"Загрузка DeepPavlov BERT из '{source}' на устройство '{device}'...")
    
    # Загрузка токенизатора и модели
    tokenizer = AutoTokenizer.from_pretrained(source)
    model = AutoModel.from_pretrained(source)
    
    # Перемещаем модель на нужное устройство
    model = model.to(device)
    model.eval()  # Переводим в режим inference
    
    print("Модель успешно загружена.")
    return model, tokenizer
