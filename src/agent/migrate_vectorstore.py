"""Migration vers le magasin de vecteurs Supabase (pgvector) :

    python3 -m src.agent.migrate_vectorstore

Prérequis : migration_012_vectorstore_pgvector.sql exécutée, et SUPABASE_URL +
SUPABASE_SERVICE_KEY + VOYAGE_API_KEY dans .env.

1. Connaissances (tout sauf les profils de lieux) : copiées depuis le Chroma
   local avec leurs embeddings existants — pas de nouvel appel Voyage.
2. Profils de lieux : recalculés depuis lieu_derive (source de vérité) en un
   lot Voyage, puis les profils de lieux qui n'existent plus sont supprimés.

Rejouable sans risque (upsert par id)."""

from __future__ import annotations

from collections import Counter

from .vectorstore import BATCH, SupabaseVectorStore, get_vectorstore


def copier_connaissances(chroma, cible) -> Counter:
    """Copie tous les documents non-profil du Chroma local vers `cible`."""
    donnees = chroma.collection.get(include=["embeddings", "documents", "metadatas"])
    compte: Counter = Counter()
    lots = {"ids": [], "embeddings": [], "documents": [], "metadatas": []}

    def vider():
        if lots["ids"]:
            cible.upsert(**lots)
            for k in lots:
                lots[k] = []

    for i, e, d, m in zip(donnees["ids"], donnees["embeddings"], donnees["documents"], donnees["metadatas"]):
        if (m or {}).get("doc_type") == "profil_lieu":
            continue
        lots["ids"].append(i)
        lots["embeddings"].append(list(e))
        lots["documents"].append(d)
        lots["metadatas"].append(m or {})
        compte[(m or {}).get("doc_type")] += 1
        if len(lots["ids"]) >= BATCH:
            vider()
    vider()
    return compte


def reembarquer_profils(store, embedder, cible) -> tuple:
    """Recalcule et écrit le profil de chaque lieu ayant une synthèse ;
    supprime les profils de lieux disparus. Renvoie (écrits, supprimés)."""
    lieux = {l.id: l for l in store.list_tiers_lieux()}
    derives = store.get_lieu_derive_batch(list(lieux))
    ids = [i for i, d in derives.items() if d.profil_semantique_texte]
    if not ids:
        return 0, 0
    embeddings = embedder.embed_documents([derives[i].profil_semantique_texte for i in ids])
    cible.upsert(
        ids=[f"profil_lieu::{i}" for i in ids], embeddings=embeddings,
        documents=[derives[i].profil_semantique_texte for i in ids],
        metadatas=[{"doc_type": "profil_lieu", "tiers_lieu_id": i, "source_file": lieux[i].nom} for i in ids])
    supprimes = cible.supprimer_absents("profil_lieu", {f"profil_lieu::{i}" for i in ids})
    return len(ids), supprimes


def main() -> None:
    from dotenv import load_dotenv

    from ..db.factory import get_admin_store
    from .embeddings import VoyageEmbedder
    from .vectorstore import ChromaStore

    load_dotenv()
    cible = get_vectorstore()
    if not isinstance(cible, SupabaseVectorStore):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY absents de .env : rien à migrer vers.")
    copies = copier_connaissances(ChromaStore(), cible)
    print("Connaissances copiées :", dict(copies) or "aucune")
    ecrits, supprimes = reembarquer_profils(get_admin_store(), VoyageEmbedder(), cible)
    print(f"Profils de lieux : {ecrits} écrits, {supprimes} obsolètes supprimés.")
    print(f"Total dans documents_vectoriels : {cible.count()}")


if __name__ == "__main__":
    main()
