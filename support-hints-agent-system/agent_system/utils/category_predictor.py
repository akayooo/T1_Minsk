from __future__ import annotations
import os
import pickle
from typing import Dict, Tuple

import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer


MAIN_DIR = "agent_system/models/finetuned_classifier"
SUB_DIR  = "agent_system/models/finetuned_classifier_subcat"
MAIN_STATE = "model.pt"
SUB_STATE  = "model_subcat.pt"
MAIN_MAP   = "label_mapping.pkl"
SUB_MAP    = "label_mapping_subcat.pkl"
MAXLEN_MAIN = 128
MAXLEN_SUB  = 128


class BertClassifier(nn.Module):
    def __init__(self, bert_model, num_labels: int, dropout: float = 0.3):
        super().__init__()
        self.bert = bert_model
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(self.bert.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        out = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        pooled = out.last_hidden_state[:, 0, :]  # [CLS]
        pooled = self.dropout(pooled)
        return self.classifier(pooled)


def _device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")

def _load_maps(path: str) -> Tuple[Dict[str,int], Dict[int,str]]:
    with open(path, "rb") as f:
        m = pickle.load(f)
    return m["label_to_id"], m["id_to_label"]

def _load_model_bundle(model_dir: str, state_name: str, map_name: str):
    label2id, id2label = _load_maps(os.path.join(model_dir, map_name))
    num_labels = len(label2id)
    tok = AutoTokenizer.from_pretrained(model_dir)
    bert = AutoModel.from_pretrained(model_dir)
    clf = BertClassifier(bert, num_labels)
    clf.load_state_dict(torch.load(os.path.join(model_dir, state_name), map_location="cpu"))
    clf.eval().to(_device())
    return tok, clf, label2id, id2label

def _encode(tok, text: str, max_length: int):
    enc = tok(
        text,
        add_special_tokens=True,
        max_length=max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    return enc["input_ids"].to(_device()), enc["attention_mask"].to(_device())

def _build_sub_input(main_cat: str, question: str) -> str:
    return f"{(main_cat or '').strip()} [SEP] {(question or '').strip()}"


_tok_main = _clf_main = _id2label_main = None
_tok_sub  = _clf_sub  = _id2label_sub  = None

def _ensure_loaded():
    global _tok_main, _clf_main, _id2label_main, _tok_sub, _clf_sub, _id2label_sub
    if _tok_main is None:
        tok, clf, _, id2 = _load_model_bundle(MAIN_DIR, MAIN_STATE, MAIN_MAP)
        _tok_main, _clf_main, _id2label_main = tok, clf, id2
    if _tok_sub is None:
        tok, clf, _, id2 = _load_model_bundle(SUB_DIR, SUB_STATE, SUB_MAP)
        _tok_sub, _clf_sub, _id2label_sub = tok, clf, id2


@torch.inference_mode()
def predict_category_and_subcategory(question: str) -> Tuple[str, str]:
    """
    Возвращает (Основная категория, Подкатегория)
    """
    q = (question or "").strip()
    if not q:
        raise ValueError("Пустой вопрос.")

    _ensure_loaded()

    ids, attn = _encode(_tok_main, q, MAXLEN_MAIN)
    logits_main = _clf_main(ids, attn)
    main_idx = int(torch.argmax(logits_main, dim=-1).item())
    main_label = _id2label_main[main_idx]

    sub_text = _build_sub_input(main_label, q)
    s_ids, s_attn = _encode(_tok_sub, sub_text, MAXLEN_SUB)
    logits_sub = _clf_sub(s_ids, s_attn)
    sub_idx = int(torch.argmax(logits_sub, dim=-1).item())
    sub_label = _id2label_sub[sub_idx]

    return main_label, sub_label
