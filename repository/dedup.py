import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.8
SUSPECT_WINDOW_DAYS = 90


def normalize_description(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def compute_fingerprint(valor: float, tipo: str, descricao_normalizada: str) -> str:
    raw = f"{valor:.2f}|{tipo}|{descricao_normalizada}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD
