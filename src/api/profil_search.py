"""Recherche sémantique de l'API, sans Chroma : le disque de l'hébergeur est
éphémère et data/chroma_db n'est pas versionné. Deux types de documents :

- "profil_lieu" : `lieu_derive.profil_semantique_texte` (Supabase) — sauf pour
  les lieux ayant des réponses confidentielles, dont le profil est reconstitué
  depuis la synthèse publique ;
- "objet_ctg" : objets Changethegame de connaissance (organisations, quêtes,
  entités, posts ; voir agent/objets_ctg.py).

Les embeddings Voyage sont gardés en mémoire (float32 : ~16 Mo pour 4 000
documents) et ne sont recalculés que pour les documents modifiés. Au démarrage,
un profil dont le texte est identique à celui déjà vectorisé par l'app dans
`documents_vectoriels` (même id, même contenu) reprend ce vecteur au lieu d'un
nouvel appel Voyage : sans ça, chaque redémarrage recalculait ~4 000
embeddings, gardés en listes Python (~130 Mo) — de quoi dépasser les 512 Mo de
l'instance Render. Un profil au texte différent (lieu avec réponses
confidentielles, synthèse publique) est toujours recalculé : le vecteur stocké
encode le texte complet. Une fois l'index construit, l'expiration du TTL relance le
rafraîchissement en arrière-plan : les questions continuent d'être servies avec
l'index existant, sans payer le calcul dans leur budget de temps."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Optional

import numpy as np

from ..agent.objets_ctg import est_connaissance, texte_objet
from ..db.store import Store
from .donnees_completes import texte_profil_partageable

TTL_SECONDES = 1800
LOT_EMBEDDINGS = 64   # textes vectorisés par appel, convertis en float32 aussitôt
LOT_LECTURE = 100     # vecteurs stockés relus par requête Supabase

_log = logging.getLogger("space2.api")


def _vecteur(brut) -> np.ndarray:
    """Vecteur normalisé en float32 ; pgvector arrive par PostgREST sous forme de chaîne « [x,y,...] »."""
    if isinstance(brut, str):
        brut = brut.strip("[] ").split(",")
    v = np.asarray(brut, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def _hash(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


class ProfilSearch:
    def __init__(self, store: Store, embedder=None, ttl: float = TTL_SECONDES, magasin=None):
        """`magasin` : SupabaseVectorStore dont reprendre les vecteurs déjà
        calculés (voir docstring du module) ; None = tout calculer."""
        self.store, self.ttl = store, ttl
        self._embedder = embedder
        self._magasin = magasin
        self._lock = threading.Lock()
        self._vecteurs: dict = {}   # doc_id -> (hash, vecteur normalisé)
        self._docs: dict = {}       # doc_id -> (doc_type, nom, texte)
        self._charge_a: Optional[float] = None
        self._en_cours = False

    @property
    def embedder(self):
        if self._embedder is None:
            from ..agent.embeddings import VoyageEmbedder
            self._embedder = VoyageEmbedder()
        return self._embedder

    def _collecter(self) -> dict:
        lieux = {lieu.id: lieu for lieu in self.store.list_tiers_lieux()}
        derives = self.store.get_lieu_derive_batch(list(lieux))
        confidentiels = self.store.get_lieux_avec_confidentiel(list(lieux))
        docs = {}
        for i, d in derives.items():
            texte = texte_profil_partageable(d, i in confidentiels)
            if texte:
                docs[f"profil_lieu::{i}"] = ("profil_lieu", lieux[i].nom, texte)
        for o in self.store.list_objets_ctg():
            if est_connaissance(o):
                docs[f"objet_ctg::{o['ctg_id']}"] = ("objet_ctg", o["name"], texte_objet(o))
        return docs

    def rafraichir(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._charge_a is not None and time.monotonic() - self._charge_a < self.ttl:
                return
            docs = self._collecter()
            hashes = {i: _hash(t) for i, (_, _, t) in docs.items()}
            # Copie puis échange : une recherche en cours continue de lire
            # l'ancien index, jamais un dictionnaire modifié sous ses pieds.
            vecteurs = {i: x for i, x in self._vecteurs.items() if i in docs}
            a_calculer = [i for i in docs if vecteurs.get(i, (None,))[0] != hashes[i]]
            if a_calculer and self._magasin is not None:
                repris = self._reprendre_stockes(a_calculer, hashes)
                vecteurs.update(repris)
                a_calculer = [i for i in a_calculer if i not in repris]
            for debut in range(0, len(a_calculer), LOT_EMBEDDINGS):
                lot = a_calculer[debut:debut + LOT_EMBEDDINGS]
                for i, v in zip(lot, self.embedder.embed_documents([docs[i][2] for i in lot])):
                    vecteurs[i] = (hashes[i], _vecteur(v))
            self._vecteurs, self._docs = vecteurs, docs
            self._charge_a = time.monotonic()

    def _reprendre_stockes(self, ids: list, hashes: dict) -> dict:
        """Vecteurs déjà stockés pour ces ids, uniquement si le texte stocké est
        exactement celui à vectoriser. En cas d'échec : {} (tout sera calculé)."""
        repris = {}
        try:
            client, table = self._magasin.client, self._magasin.TABLE
            for debut in range(0, len(ids), LOT_LECTURE):
                lignes = (client.table(table).select("id,contenu,embedding")
                          .in_("id", ids[debut:debut + LOT_LECTURE]).execute().data)
                for ligne in lignes:
                    if ligne.get("contenu") is not None and _hash(ligne["contenu"]) == hashes.get(ligne["id"]):
                        repris[ligne["id"]] = (hashes[ligne["id"]], _vecteur(ligne["embedding"]))
        except Exception:
            _log.exception("[profils] reprise des vecteurs stockés impossible, calcul complet")
            return {}
        _log.info("[profils] %d vecteurs repris sur %d à calculer", len(repris), len(ids))
        return repris

    def _rafraichir_en_arriere_plan(self) -> None:
        def _tache():
            try:
                self.rafraichir()
            except Exception:
                pass
            finally:
                self._en_cours = False
        with self._lock:
            if self._en_cours:
                return
            self._en_cours = True
        threading.Thread(target=_tache, daemon=True).start()

    def search(self, query: str, top_k: int = 6, doc_type: Optional[str] = None, embedding=None) -> list:
        if self._charge_a is None:
            self.rafraichir()   # premier appel : pas d'index à servir en attendant
        elif time.monotonic() - self._charge_a >= self.ttl:
            self._rafraichir_en_arriere_plan()
        vecteurs, docs = self._vecteurs, self._docs
        ids = [i for i in vecteurs if doc_type is None or docs[i][0] == doc_type]
        if not ids:
            return []
        q = _vecteur(embedding if embedding is not None else self.embedder.embed_query(query))
        scores = np.array([float(vecteurs[i][1] @ q) for i in ids])
        hits = []
        for idx in np.argsort(-scores)[:max(1, top_k)]:
            i = ids[idx]
            type_doc, nom, texte = docs[i]
            cle = "tiers_lieu_id" if type_doc == "profil_lieu" else "ctg_id"
            hits.append({"text": texte, "distance": round(1 - float(scores[idx]), 4),
                         "metadata": {"doc_type": type_doc, cle: i.split("::", 1)[1], "source_file": nom}})
        return hits
