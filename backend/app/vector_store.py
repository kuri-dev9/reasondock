import pickle
import re
from pathlib import Path
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.tokenizer import tokenize as _tokenize

DATA_DIR = Path(__file__).parent.parent / "knowledge_data"
DATA_DIR.mkdir(exist_ok=True)

INDEX_VERSION = 3


class HybridSearch:
    def __init__(self):
        self.chunks: list[str] = []
        self.doc_ids: list[int] = []
        self.chunk_metadatas: list[dict] = []
        self.bm25: Optional[BM25Okapi] = None
        self.tfidf: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None
        self._load()

    def _save(self):
        data = {
            "chunks": self.chunks,
            "doc_ids": self.doc_ids,
            "chunk_metadatas": self.chunk_metadatas,
            "version": INDEX_VERSION,
        }
        with open(DATA_DIR / "index.pkl", "wb") as f:
            pickle.dump(data, f)

    def _load(self):
        index_path = DATA_DIR / "index.pkl"
        if index_path.exists():
            with open(index_path, "rb") as f:
                data = pickle.load(f)
            self.chunks = data["chunks"]
            self.doc_ids = data["doc_ids"]
            self.chunk_metadatas = data.get("chunk_metadatas") or [{} for _ in self.chunks]
            if len(self.chunk_metadatas) != len(self.chunks):
                self.chunk_metadatas = [{} for _ in self.chunks]
            self._rebuild_index()
            if data.get("version", 1) != INDEX_VERSION:
                self._save()

    def _rebuild_index(self):
        if not self.chunks:
            self.bm25 = None
            self.tfidf = None
            self.tfidf_matrix = None
            return

        tokenized = [_tokenize(c) for c in self.chunks]
        # BM25Okapi requires non-empty token lists; filter out empty ones
        tokenized = [t if t else [""] for t in tokenized]
        self.bm25 = BM25Okapi(tokenized)

        self.tfidf = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None)
        self.tfidf_matrix = self.tfidf.fit_transform(self.chunks)

    def add_chunks(self, doc_id: int, chunks: list[str], metadatas: list[dict] | None = None):
        metadatas = metadatas or [{} for _ in chunks]
        if len(metadatas) != len(chunks):
            metadatas = [{} for _ in chunks]
        self.chunks.extend(chunks)
        self.doc_ids.extend([doc_id] * len(chunks))
        self.chunk_metadatas.extend(metadatas)
        self._rebuild_index()
        self._save()

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        if not self.chunks or not self.bm25 or not self.tfidf:
            return []

        tokenized_query = _tokenize(query)

        # BM25 scores
        bm25_scores = self.bm25.get_scores(tokenized_query)
        bm25_max = bm25_scores.max() if bm25_scores.max() > 0 else 1
        bm25_norm = np.clip(bm25_scores / bm25_max, 0, None)

        # TF-IDF cosine similarity
        query_vec = self.tfidf.transform([query])
        tfidf_scores = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        # Hybrid: weighted combination (BM25 0.5 + TF-IDF 0.5)
        combined = 0.5 * bm25_norm + 0.5 * tfidf_scores

        top_indices = combined.argsort()[::-1][:n_results]

        results = []
        for idx in top_indices:
            score = float(combined[idx])
            if score < 0.05:
                continue
            metadata = self.chunk_metadatas[idx] if idx < len(self.chunk_metadatas) else {}
            results.append({
                "content": self.chunks[idx],
                "doc_id": self.doc_ids[idx],
                "score": score,
                **metadata,
            })
        return results

    def delete_by_doc_id(self, doc_id: int):
        pairs = [
            (c, d, m)
            for c, d, m in zip(self.chunks, self.doc_ids, self.chunk_metadatas)
            if d != doc_id
        ]
        if pairs:
            self.chunks, self.doc_ids, self.chunk_metadatas = list(zip(*pairs))
            self.chunks = list(self.chunks)
            self.doc_ids = list(self.doc_ids)
            self.chunk_metadatas = list(self.chunk_metadatas)
        else:
            self.chunks = []
            self.doc_ids = []
            self.chunk_metadatas = []
        self._rebuild_index()
        self._save()


# Singleton instance
search_engine = HybridSearch()


def add_chunks(doc_id: int, chunks: list[str], embeddings=None, metadatas: list[dict] | None = None):
    search_engine.add_chunks(doc_id, chunks, metadatas=metadatas)


def search(query_embedding=None, n_results: int = 5, query: str = "") -> list[dict]:
    return search_engine.search(query, n_results)


def fallback_search(query: str, n_results: int = 5) -> list[dict]:
    query_tokens = _fallback_tokens(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, int]] = []
    for index, chunk in enumerate(search_engine.chunks):
        chunk_text = chunk.lower()
        score = sum(1.0 for token in query_tokens if token in chunk_text)
        if score:
            scored.append((score / len(query_tokens), index))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, index in scored[:n_results]:
        metadata = (
            search_engine.chunk_metadatas[index]
            if index < len(search_engine.chunk_metadatas)
            else {}
        )
        results.append({
            "content": search_engine.chunks[index],
            "doc_id": search_engine.doc_ids[index],
            "score": score,
            **metadata,
        })
    return results


def _fallback_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9_\-]{1,}", text.lower())
    normalized: list[str] = []
    for token in tokens:
        token = re.sub(r"(의|은|는|이|가|을|를|와|과|로|으로|에|에서|에게|한테|도|만|야|요)$", "", token)
        if len(token) >= 2:
            normalized.append(token)
    return normalized


def delete_by_doc_id(doc_id: int):
    search_engine.delete_by_doc_id(doc_id)


def chunks_by_doc_id(doc_id: int, limit: int = 20) -> list[dict]:
    results = []
    for index, (chunk, chunk_doc_id) in enumerate(zip(search_engine.chunks, search_engine.doc_ids)):
        if chunk_doc_id != doc_id:
            continue
        metadata = (
            search_engine.chunk_metadatas[index]
            if index < len(search_engine.chunk_metadatas)
            else {}
        )
        results.append({
            "content": chunk,
            "doc_id": chunk_doc_id,
            **metadata,
        })
        if len(results) >= limit:
            break
    return results


def text_by_doc_id(doc_id: int) -> str:
    parts = [
        chunk
        for chunk, chunk_doc_id in zip(search_engine.chunks, search_engine.doc_ids)
        if chunk_doc_id == doc_id
    ]
    return "\n\n".join(parts)
