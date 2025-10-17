from sentence_transformers import SentenceTransformer, util
import numpy as np

_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def _normalize(vec: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(vec, axis=-1, keepdims=True) + 1e-12
    return vec / denom

def get_embedding(text: str):
    emb = _model.encode(text or "", normalize_embeddings=True)
    return emb.tolist()

def get_embeddings(texts):
    embs = _model.encode([t or "" for t in texts], normalize_embeddings=True)
    return [e.tolist() for e in embs]

def cosine_similarity(vec1, vec2) -> float:
    v1 = np.asarray(vec1, dtype=np.float32)
    v2 = np.asarray(vec2, dtype=np.float32)
    if abs(np.linalg.norm(v1) - 1.0) > 1e-3: v1 = _normalize(v1)
    if abs(np.linalg.norm(v2) - 1.0) > 1e-3: v2 = _normalize(v2)
    return float(np.dot(v1, v2))

def cosine_topk(query_vec, matrix, k):
    q = np.asarray(query_vec, dtype=np.float32)
    M = np.asarray(matrix, dtype=np.float32)
    sims = M @ q
    idx = np.argpartition(-sims, kth=min(k, len(sims)-1))[:k]
    idx = idx[np.argsort(-sims[idx])]
    return idx.tolist(), sims[idx].tolist()
