"""Wrapper ChromaDB : collection persistante pour le corpus documentaire
(interviews, rapports, résumés de datasets et de géodonnées)."""

from __future__ import annotations

COLLECTION_NAME = "lieux_hybrides"


class ChromaStore:
    def __init__(self, persist_directory: str = "data/chroma_db"):
        import chromadb

        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(COLLECTION_NAME)

    def upsert(self, ids: list, embeddings: list, documents: list, metadatas: list) -> None:
        self.collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def query(self, embedding: list, top_k: int = 6, where: dict | None = None) -> list:
        result = self.collection.query(
            query_embeddings=[embedding], n_results=top_k, where=where or None
        )
        hits = []
        for doc, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
            hits.append({"text": doc, "metadata": meta, "distance": dist})
        return hits

    def count(self) -> int:
        return self.collection.count()
