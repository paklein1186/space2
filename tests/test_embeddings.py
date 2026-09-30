"""VoyageEmbedder.embed_documents : les lots respectent la limite de tokens de
Voyage (120 000/batch), pas seulement un nombre de textes — vécu : un PDF long
découpé en chunks dépassait la limite dans un seul lot de 128 textes. Sans
réseau (faux client voyageai).

Usage : python3 -m tests.test_embeddings
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.embeddings import BATCH_SIZE, MAX_TOKENS_PAR_LOT, VoyageEmbedder


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FauxClientVoyage:
    """1 mot = 1 token (simplification de test) ; enregistre chaque lot
    réellement envoyé à .embed() pour vérifier son gabarit."""

    def __init__(self):
        self.lots_envoyes = []

    def count_tokens(self, texts, model=None):
        return sum(len(t.split()) for t in texts)

    def embed(self, texts, model=None, input_type=None):
        self.lots_envoyes.append(list(texts))
        import types
        return types.SimpleNamespace(embeddings=[[float(len(t.split()))] for t in texts])


def main():
    embedder = VoyageEmbedder(api_key="x")
    faux = FauxClientVoyage()
    embedder.client = faux

    # --- un lot dépassant la limite de tokens est scindé, même sous BATCH_SIZE textes ---
    gros_texte = " ".join(["mot"] * 900)  # ~900 tokens
    textes = [gros_texte] * 150           # 150 * 900 = 135 000 tokens, 150 < BATCH_SIZE (128)... non : 150 > 128
    textes = [gros_texte] * 115           # 115 < BATCH_SIZE, 115*900 = 103 500 > MAX_TOKENS_PAR_LOT (100 000)
    resultats = embedder.embed_documents(textes)
    check("un embedding par texte, dans l'ordre", len(resultats) == len(textes))
    check("aucun lot envoyé à Voyage ne dépasse la limite de tokens",
          all(faux.count_tokens(lot) <= MAX_TOKENS_PAR_LOT for lot in faux.lots_envoyes))
    check("scindé en au moins 2 lots (115 textes tiendrait dans un seul lot par le seul critère de compte)",
          len(faux.lots_envoyes) >= 2)
    check("le total des textes envoyés correspond à l'entrée",
          sum(len(lot) for lot in faux.lots_envoyes) == len(textes))

    # --- toujours borné par BATCH_SIZE textes, même avec des textes courts ---
    faux.lots_envoyes = []
    embedder.embed_documents(["un mot"] * (BATCH_SIZE * 2 + 5))
    check("aucun lot ne dépasse BATCH_SIZE textes", all(len(lot) <= BATCH_SIZE for lot in faux.lots_envoyes))
    check("3 lots pour 2*BATCH_SIZE+5 textes courts", len(faux.lots_envoyes) == 3)

    # --- cas limites ---
    faux.lots_envoyes = []
    check("liste vide : aucun appel, aucun résultat", embedder.embed_documents([]) == [] and not faux.lots_envoyes)
    faux.lots_envoyes = []
    resultat = embedder.embed_documents([gros_texte])
    check("un seul texte, même énorme, part dans son propre lot",
          len(resultat) == 1 and len(faux.lots_envoyes) == 1)

    # --- reproduction du cas réel signalé (PDF long) ---
    faux.lots_envoyes = []
    from src.ingest.chunking import chunk_text
    texte_pdf = "\n\n".join(f"Paragraphe {i} du guide, avec un contenu assez long pour peser des tokens." * 6
                            for i in range(220))
    chunks = chunk_text(texte_pdf, metadata={"doc_type": "connaissance_bibliotheque", "source_file": "guide.pdf"})
    embeddings = embedder.embed_documents([c.text for c in chunks])
    check("PDF long : un embedding par chunk, aucun lot au-dessus de la limite",
          len(embeddings) == len(chunks) and all(faux.count_tokens(lot) <= MAX_TOKENS_PAR_LOT for lot in faux.lots_envoyes))
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
