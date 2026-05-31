"""
PhoBERT classifier — load model nếu model_path có trong sentiment.yaml.
Nếu không có model → raise ImportError để classifier.py fallback sang rules.
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_model = None
_tokenizer = None
_loaded_path: str | None = None

LABEL_MAP = {0: "NEU", 1: "POS", 2: "NEG"}


def _load(model_path: str):
    global _model, _tokenizer, _loaded_path
    if _loaded_path == model_path:
        return

    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        _tokenizer = AutoTokenizer.from_pretrained("vinai/phobert-base-v2")
        _model = AutoModelForSequenceClassification.from_pretrained(str(path))
        _model.eval()
        _loaded_path = model_path
        log.info(f"PhoBERT loaded from {model_path}")
    except Exception as e:
        _model = None
        _tokenizer = None
        raise ImportError(f"PhoBERT load failed: {e}") from e


def classify(title: str, summary: str | None, model_path: str) -> tuple[str, float, str]:
    """
    Returns (label, confidence, method_name).
    Raises ImportError nếu model không load được → caller fallback sang rule.
    """
    import torch

    _load(model_path)

    text = f"{title} {summary or ''}"[:512]
    inputs = _tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=256,
        padding=True,
    )
    with torch.no_grad():
        logits = _model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        pred = probs.argmax().item()
        score = probs[pred].item()

    model_name = Path(model_path).stem
    return LABEL_MAP[pred], round(score, 3), model_name
