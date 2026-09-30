"""Relancer l'extraction de lieux candidats sur un document déjà ingéré
(lister_documents_ingeres / recomposer_texte_document, voir
agent/extraction_lieux.py) : liste groupée par source, exclusion des
connaissances courtes et des profils de lieux, reconstitution ordonnée par
chunk_index. Utilise un vrai ChromaStore (disque local temporaire, sans
réseau) pour exercer la vraie requête multi-conditions.

Usage : python3 -m tests.test_extraction_lieux_documents
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.agent.vectorstore as vectorstore_module
from src.agent.extraction_lieux import lister_documents_ingeres, recomposer_texte_document
from src.agent.vectorstore import ChromaStore


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def chunk(doc_type, source_file, index, texte, date_ajout):
    return {"id": f"connaissance_longue_h_{source_file}_{index}", "doc_type": doc_type,
            "source_file": source_file, "chunk_index": index, "date_ajout": date_ajout, "texte": texte}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = ChromaStore(persist_directory=tmp)

        # Document long A (connaissance_bibliotheque), 3 passages, dans le désordre pour vérifier le tri
        a = [
            chunk("connaissance_bibliotheque", "Guide A", 1, "Deuxième passage du guide.", "2026-09-30T09:00:00+00:00"),
            chunk("connaissance_bibliotheque", "Guide A", 0, "Premier passage du guide.", "2026-09-30T09:00:00+00:00"),
            chunk("connaissance_bibliotheque", "Guide A", 2, "Troisième passage du guide.", "2026-09-30T09:00:00+00:00"),
        ]
        # Document long B (connaissance_trois_tiers), 2 passages, ajouté avant A
        b = [
            chunk("connaissance_trois_tiers", "Article B", 0, "Début de l'article B.", "2026-09-25T10:00:00+00:00"),
            chunk("connaissance_trois_tiers", "Article B", 1, "Suite de l'article B.", "2026-09-25T10:00:00+00:00"),
        ]
        for lot in (a, b):
            store.upsert(
                ids=[c["id"] for c in lot], embeddings=[[float(c["chunk_index"]), 0.0] for c in lot],
                documents=[c["texte"] for c in lot],
                metadatas=[{"doc_type": c["doc_type"], "source_file": c["source_file"],
                           "chunk_index": c["chunk_index"], "date_ajout": c["date_ajout"]} for c in lot])
        # Connaissance courte (bouton 🧠) : un seul extrait, pas de chunk_index/préfixe long
        store.upsert(ids=["connaissance_xyz789"], embeddings=[[9.0, 9.0]], documents=["Un extrait court."],
                    metadatas=[{"doc_type": "connaissance_bibliotheque", "source_file": "Page courte",
                               "date_ajout": "2026-09-29T00:00:00+00:00"}])
        # Profil de lieu : autre doc_type, ne doit jamais apparaître
        store.upsert(ids=["profil_lieu::xyz"], embeddings=[[5.0, 5.0]], documents=["Profil d'un lieu."],
                    metadatas=[{"doc_type": "profil_lieu", "tiers_lieu_id": "xyz", "source_file": "Un Lieu"}])

        reel = vectorstore_module.get_vectorstore
        vectorstore_module.get_vectorstore = lambda: store
        try:
            documents = lister_documents_ingeres()
            check("2 documents listés (A et B), pas la page courte ni le profil",
                  {d["source_label"] for d in documents} == {"Guide A", "Article B"})
            guide_a = next(d for d in documents if d["source_label"] == "Guide A")
            check("n_passages correct", guide_a["n_passages"] == 3)
            check("date_ajout = celle des passages", guide_a["date_ajout"] == "2026-09-30T09:00:00+00:00")
            check("triés du plus récent au plus ancien (A avant B)",
                  [d["source_label"] for d in documents] == ["Guide A", "Article B"])

            texte_a = recomposer_texte_document("Guide A")
            check("reconstitution : passages remis dans l'ordre malgré l'insertion désordonnée",
                  texte_a == "Premier passage du guide.\n\nDeuxième passage du guide.\n\nTroisième passage du guide.")
            texte_b = recomposer_texte_document("Article B")
            check("reconstitution : fonctionne pour connaissance_trois_tiers aussi",
                  texte_b == "Début de l'article B.\n\nSuite de l'article B.")
            check("source inconnue : texte vide, pas d'erreur", recomposer_texte_document("N'existe pas") == "")
            check("la connaissance courte n'est jamais reconstituée comme 'document'",
                  "Un extrait court." not in recomposer_texte_document("Page courte"))
        finally:
            vectorstore_module.get_vectorstore = reel
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
