"""Magasins de vecteurs pour le corpus documentaire (profils de lieux,
interviews, rapports, connaissances...).

- SupabaseVectorStore (pgvector, table documents_vectoriels) : PERSISTANT, à
  utiliser en production — le disque de Streamlit Cloud/Render est éphémère,
  donc un Chroma local y repart vide à chaque redéploiement (vécu : la
  recherche sémantique ne retrouvait plus que quelques lieux).
- ChromaStore : développement local sans Supabase.

`get_vectorstore()` choisit automatiquement ; tous les appelants passent par lui.
"""

from __future__ import annotations

import os

COLLECTION_NAME = "lieux_hybrides"
BATCH = 50


def get_vectorstore():
    """Supabase (clé service_role) si configuré, sinon Chroma local."""
    url, cle = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if url and cle:
        return SupabaseVectorStore(url, cle)
    return ChromaStore()


class SupabaseVectorStore:
    TABLE = "documents_vectoriels"

    def __init__(self, url: str, key: str, client=None):
        if client is None:
            from ..db.supabase_store import creer_client
            client = creer_client(url, key)
        self.client = client

    @staticmethod
    def _filtre_doc_type(where: dict | None):
        if not where:
            return None
        if set(where) != {"doc_type"}:
            raise ValueError("SupabaseVectorStore ne filtre que sur doc_type")
        return where["doc_type"]

    def upsert(self, ids: list, embeddings: list, documents: list, metadatas: list) -> None:
        lignes = []
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            lignes.append({
                "id": i, "doc_type": m.get("doc_type") or "inconnu",
                "tiers_lieu_id": m.get("tiers_lieu_id"), "source_file": m.get("source_file"),
                "contenu": d, "metadata": m, "embedding": [float(x) for x in e],
            })
        for debut in range(0, len(lignes), BATCH):
            self.client.table(self.TABLE).upsert(lignes[debut:debut + BATCH], on_conflict="id").execute()

    def query(self, embedding: list, top_k: int = 6, where: dict | None = None) -> list:
        rows = self.client.rpc("match_documents", {
            "query_embedding": [float(x) for x in embedding], "match_count": top_k,
            "filter_doc_type": self._filtre_doc_type(where)}).execute().data
        return [{"text": r["contenu"], "metadata": r["metadata"], "distance": 1 - float(r["similarity"])}
                for r in rows]

    def count(self) -> int:
        return self.client.table(self.TABLE).select("id", count="exact").limit(1).execute().count or 0

    def get_metadatas(self, where: dict) -> list:
        doc_type = self._filtre_doc_type(where)
        return [r["metadata"] for r in
                self.client.table(self.TABLE).select("metadata").eq("doc_type", doc_type).execute().data]

    def supprimer_absents(self, doc_type: str, ids_a_garder: set) -> int:
        """Supprime les documents de ce type dont l'id n'est pas dans
        `ids_a_garder` (ex. profils de lieux qui n'existent plus)."""
        existants = {r["id"] for r in
                     self.client.table(self.TABLE).select("id").eq("doc_type", doc_type).execute().data}
        a_supprimer = sorted(existants - set(ids_a_garder))
        for debut in range(0, len(a_supprimer), BATCH):
            self.client.table(self.TABLE).delete().in_("id", a_supprimer[debut:debut + BATCH]).execute()
        return len(a_supprimer)


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

    def get_metadatas(self, where: dict) -> list:
        """Métadonnées de tous les documents correspondant à `where`, sans
        recherche par similarité (pas de embedding à fournir) — utilisé pour
        des besoins d'introspection (ex. date du dernier document ajouté
        pour un doc_type donné), pas pour retrouver du contenu pertinent."""
        result = self.collection.get(where=where, include=["metadatas"])
        return result.get("metadatas") or []
