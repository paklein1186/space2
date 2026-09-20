"""Magasin de vecteurs Supabase (pgvector) : upsert/requête/filtre/suppression,
choix automatique Supabase/Chroma, migration depuis Chroma (connaissances
copiées avec leurs embeddings, profils recalculés depuis lieu_derive, profils
obsolètes supprimés). Client Supabase simulé, sans réseau.

Usage : python3 -m tests.test_vectorstore
"""

import os
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import migrate_vectorstore as mig
from src.agent import vectorstore as vs
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class Requete:
    def __init__(self, client):
        self.c, self.filtres, self.op, self.payload, self.compter, self.lim = client, [], "select", None, False, None

    def select(self, _cols, count=None):
        self.compter = bool(count)
        return self

    def eq(self, col, val):
        self.filtres.append(lambda r: r[col] == val)
        return self

    def in_(self, col, vals):
        self.filtres.append(lambda r: r[col] in vals)
        return self

    def limit(self, n):
        self.lim = n
        return self

    def upsert(self, rows, on_conflict=None):
        self.op, self.payload = "upsert", rows
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        table = self.c.lignes
        if self.op == "upsert":
            for r in self.payload:
                table[r["id"]] = dict(r)
            return types.SimpleNamespace(data=self.payload, count=None)
        cibles = [r for r in table.values() if all(f(r) for f in self.filtres)]
        if self.op == "delete":
            for r in cibles:
                del table[r["id"]]
            return types.SimpleNamespace(data=[], count=None)
        return types.SimpleNamespace(data=cibles[: self.lim] if self.lim else cibles,
                                     count=len(cibles) if self.compter else None)


class FauxSupabase:
    def __init__(self):
        self.lignes = {}
        self.appels_rpc = []

    def table(self, nom):
        assert nom == "documents_vectoriels"
        return Requete(self)

    def rpc(self, nom, params):
        assert nom == "match_documents"
        self.appels_rpc.append(params)
        q = np.array(params["query_embedding"])
        q = q / np.linalg.norm(q)
        lignes = [r for r in self.lignes.values()
                  if params["filter_doc_type"] is None or r["doc_type"] == params["filter_doc_type"]]
        scores = sorted(((float(np.array(r["embedding"]) @ q / np.linalg.norm(r["embedding"])), r) for r in lignes),
                        key=lambda x: -x[0])[: params["match_count"]]
        data = [{"id": r["id"], "contenu": r["contenu"], "metadata": r["metadata"], "similarity": s}
                for s, r in scores]
        return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=data))


class FauxChroma:
    """Mime chroma.collection.get(include=[...])."""

    def __init__(self, docs):
        self.docs = docs
        self.collection = self

    def get(self, include=None):
        return {"ids": [d[0] for d in self.docs], "embeddings": [d[1] for d in self.docs],
                "documents": [d[2] for d in self.docs], "metadatas": [d[3] for d in self.docs]}


class FauxEmbedder:
    def embed_documents(self, textes):
        return [[float(t.lower().count(m)) + 0.01 for m in ("gare", "permaculture", "musique")] for t in textes]


def main():
    # --- magasin ---
    client = FauxSupabase()
    magasin = vs.SupabaseVectorStore("u", "k", client=client)
    magasin.upsert(
        ids=["a", "b", "c"], embeddings=[[1, 0, 0], [0, 1, 0], [0.9, 0.1, 0]],
        documents=["doc gare", "doc permaculture", "doc gare bis"],
        metadatas=[{"doc_type": "profil_lieu", "tiers_lieu_id": "L1", "source_file": "Lieu 1"},
                   {"doc_type": "connaissance_bibliotheque", "source_file": "Biblio", "date_ajout": "2026-09-01"},
                   {"doc_type": "connaissance_bibliotheque", "source_file": "Biblio2", "date_ajout": "2026-09-15"}])
    check("upsert : lignes typées (doc_type, tiers_lieu_id, contenu)",
          client.lignes["a"]["doc_type"] == "profil_lieu" and client.lignes["a"]["tiers_lieu_id"] == "L1"
          and client.lignes["b"]["tiers_lieu_id"] is None and client.lignes["a"]["contenu"] == "doc gare")
    hits = magasin.query([1, 0, 0], top_k=2)
    check("query : format identique à Chroma (text, metadata, distance) et tri par proximité",
          [h["text"] for h in hits] == ["doc gare", "doc gare bis"] and hits[0]["distance"] < hits[1]["distance"]
          and set(hits[0]) == {"text", "metadata", "distance"})
    hits = magasin.query([1, 0, 0], top_k=5, where={"doc_type": "connaissance_bibliotheque"})
    check("query : filtre doc_type", {h["metadata"]["doc_type"] for h in hits} == {"connaissance_bibliotheque"})
    check("filtre autre que doc_type refusé", not_ok(lambda: magasin.query([1, 0, 0], where={"source_file": "x"})))
    check("count", magasin.count() == 3)
    check("get_metadatas (dernier scan)",
          max(m["date_ajout"] for m in magasin.get_metadatas({"doc_type": "connaissance_bibliotheque"})) == "2026-09-15")
    magasin.upsert(["a"], [[1, 0, 0]], ["doc gare v2"], [{"doc_type": "profil_lieu", "tiers_lieu_id": "L1"}])
    check("upsert idempotent (pas de doublon, contenu mis à jour)",
          magasin.count() == 3 and client.lignes["a"]["contenu"] == "doc gare v2")
    check("supprimer_absents", magasin.supprimer_absents("profil_lieu", set()) == 1 and magasin.count() == 2)

    # --- choix du magasin ---
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        os.environ.pop(k, None)
    check("sans Supabase → Chroma local", isinstance(vs.get_vectorstore(), vs.ChromaStore))
    os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"] = "http://x", "k"
    orig = vs.SupabaseVectorStore.__init__
    vs.SupabaseVectorStore.__init__ = lambda self, url, key, client=None: setattr(self, "client", FauxSupabase())
    check("avec SUPABASE_URL + SERVICE_KEY → Supabase", isinstance(vs.get_vectorstore(), vs.SupabaseVectorStore))
    vs.SupabaseVectorStore.__init__ = orig
    os.environ.pop("SUPABASE_URL"), os.environ.pop("SUPABASE_SERVICE_KEY")

    # --- migration ---
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "m.sqlite3"))
        gare = store.get_or_create_tiers_lieu("u", "Quatre Quarts")
        autre = store.get_or_create_tiers_lieu("u", "Autre Lieu")
        for lieu, texte in ((gare, "Tiers-lieu dans une ancienne gare"), (autre, "Ferme en permaculture")):
            store.save_lieu_derive(LieuDerive(tiers_lieu_id=lieu.id, donnees={}, profil_semantique_texte=texte,
                                              prompt_version="v", model="m", source_hash="h"))
        cible = vs.SupabaseVectorStore("u", "k", client=FauxSupabase())
        # profil obsolète déjà présent côté Supabase (lieu supprimé depuis)
        cible.upsert(["profil_lieu::disparu"], [[1, 1, 1]], ["vieux"], [{"doc_type": "profil_lieu"}])
        chroma = FauxChroma([
            ("k1", [0.1, 0.2, 0.3], "savoir A", {"doc_type": "connaissance_bibliotheque", "source_file": "S"}),
            ("k2", [0.3, 0.2, 0.1], "savoir B", {"doc_type": "connaissance_trois_tiers", "source_file": "T"}),
            ("p1", [1, 1, 1], "vieux profil local", {"doc_type": "profil_lieu", "tiers_lieu_id": "zzz"}),
        ])
        copies = mig.copier_connaissances(chroma, cible)
        check("connaissances copiées avec leurs embeddings (sans recalcul), profils locaux ignorés",
              dict(copies) == {"connaissance_bibliotheque": 1, "connaissance_trois_tiers": 1}
              and cible.client.lignes["k1"]["embedding"] == [0.1, 0.2, 0.3] and "p1" not in cible.client.lignes)
        ecrits, supprimes = mig.reembarquer_profils(store, FauxEmbedder(), cible)
        check("profils recalculés depuis lieu_derive (tous les lieux), obsolète supprimé",
              (ecrits, supprimes) == (2, 1) and f"profil_lieu::{gare.id}" in cible.client.lignes
              and "profil_lieu::disparu" not in cible.client.lignes)
        hit = cible.query(FauxEmbedder().embed_documents(["gare"])[0], top_k=1, where={"doc_type": "profil_lieu"})[0]
        check("après migration : la requête « gare » retrouve Quatre Quarts",
              hit["metadata"]["source_file"] == "Quatre Quarts" and hit["metadata"]["tiers_lieu_id"] == gare.id)
        check("connaissances préservées après ré-embarquement des profils", "k1" in cible.client.lignes and "k2" in cible.client.lignes)
    print("Tous les tests passent.")


def not_ok(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    main()
