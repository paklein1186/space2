"""Mémoire de l'API Render (instance limitée à 512 Mo), sans réseau :
- ProfilSearch reprend les vecteurs déjà stockés quand le texte est identique,
  recalcule les autres (texte différent : profil confidentiel), par lots, en float32 ;
- un jeu de données demandé par plusieurs outils en parallèle n'est construit qu'une fois ;
- le cache de l'observatoire ne garde que les colonnes et questions agrégées.

Usage : python3 -m tests.test_api_memoire
"""

import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.rag_tools import RagToolHandler
from src.api import observatoire as obs
from src.api.ask_agent import OutilsComplets
from src.api.profil_search import ProfilSearch
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class Embedder:
    def __init__(self):
        self.lots = []

    def embed_documents(self, textes):
        self.lots.append(len(textes))
        return [[1.0, float(len(t)), 0.5] for t in textes]

    def embed_query(self, texte):
        return [1.0, 0.0, 0.0]


class Requete:
    def __init__(self, lignes):
        self.lignes, self.ids = lignes, None

    def select(self, _colonnes):
        return self

    def in_(self, _colonne, ids):
        self.ids = set(ids)
        return self

    def execute(self):
        return type("R", (), {"data": [l for l in self.lignes if l["id"] in self.ids]})()


class Magasin:
    TABLE = "documents_vectoriels"

    def __init__(self, lignes, casse=False):
        self.lignes, self.casse = lignes, casse
        self.client = self

    def table(self, _nom):
        if self.casse:
            raise RuntimeError("Supabase injoignable")
        return Requete(self.lignes)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "m.sqlite3"))
        ids = []
        for i in range(70):
            lieu = store.get_or_create_tiers_lieu("u", f"Lieu {i}")
            store.save_lieu_derive(LieuDerive(tiers_lieu_id=lieu.id, donnees={"resume": f"r{i}"},
                                              profil_semantique_texte=f"Profil du lieu numéro {i}",
                                              prompt_version="t", model="t", source_hash=str(i)))
            ids.append(lieu.id)
        profils = ProfilSearch(store, embedder=Embedder(), ttl=3600)
        docs = profils._collecter()
        stockes = [{"id": doc_id, "contenu": texte, "embedding": "[0.0,3.0,4.0]"}
                   for doc_id, (_, _, texte) in list(docs.items())[:60]]
        stockes[0]["contenu"] = "texte complet, confidentiel"   # stocké ≠ version partageable

        profils = ProfilSearch(store, embedder=Embedder(), ttl=3600, magasin=Magasin(stockes))
        profils.rafraichir()
        check("59 vecteurs repris, 11 calculés (texte différent ou absent du magasin)",
              sum(profils._embedder.lots) == 11)
        repris = profils._vecteurs[stockes[1]["id"]][1]
        check("vecteur repris : chaîne pgvector décodée, normalisée, en float32",
              repris.dtype == np.float32 and np.allclose(repris, [0, 0.6, 0.8]))
        check("profil au texte différent : recalculé, pas repris",
              not np.allclose(profils._vecteurs[stockes[0]["id"]][1], [0, 0.6, 0.8]))
        check("tous les vecteurs en float32", all(v.dtype == np.float32 for _, v in profils._vecteurs.values()))
        check("recherche toujours servie", len(profils.search("x", top_k=3)) == 3)

        sans = ProfilSearch(store, embedder=Embedder(), ttl=3600)
        sans.rafraichir()
        check("sans magasin : tout calculé, par lots de 64 au plus", sans._embedder.lots == [64, 6])
        panne = ProfilSearch(store, embedder=Embedder(), ttl=3600, magasin=Magasin(stockes, casse=True))
        panne.rafraichir()
        check("magasin en panne : calcul complet, pas d'erreur", sum(panne._embedder.lots) == 70)

        # Un seul chargement par jeu, même demandé en parallèle.
        for classe in (OutilsComplets, RagToolHandler):
            outils = classe.__new__(classe)
            if classe is OutilsComplets:
                OutilsComplets.__init__(outils, store, sans, ttl=300)
            else:
                outils.store = store
            appels = []

            def construire(nom, appels=appels):
                appels.append(nom)
                time.sleep(0.2)
                return pd.DataFrame({"a": [1]})
            outils._construire_dataframe = construire
            fils = [threading.Thread(target=outils._load_dataframe, args=("bonnes_pratiques",)) for _ in range(4)]
            [f.start() for f in fils]
            [f.join() for f in fils]
            check(f"{classe.__name__} : 4 outils en parallèle, 1 seul chargement", appels == ["bonnes_pratiques"])

    # Observatoire : cache allégé, agrégats inchangés.
    lieux = pd.DataFrame({"tiers_lieu": ["A", "B", "C"], "pays": ["Belgique", "France", "France"],
                          "region": ["Namur", "Bretagne", "Bretagne"],
                          "categories": [["Culturel"], ["Alimentaire"], ["Culturel"]], "mots_cles": [["x"], ["y"], ["x"]],
                          "resume": ["long texte " * 500] * 3})
    reponses = pd.DataFrame({"tiers_lieu": ["A", "A", "B"], "pays": ["Belgique", "Belgique", "France"],
                             "region": ["Namur", "Namur", "Bretagne"], "contributeur_id": ["c", "c", "d"],
                             "champ": ["Milieu", "Pitch", "Milieu"], "champ_id": ["milieu", "pitch", "milieu"],
                             "valeur": ["Rural", "texte", "Urbain"]})
    legers = obs._alleger(lieux, reponses)
    check("observatoire : textes des fiches et questions non agrégées écartés",
          "resume" not in legers[0].columns and set(legers[1]["champ_id"]) == {"milieu"})
    check("observatoire : agrégats identiques avec le cache allégé (répartitions calculées)",
          obs.agregats(*legers) == obs.agregats(lieux, reponses)
          and obs.agregats(*legers)["repartitions"]["milieu"] != [])
    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
