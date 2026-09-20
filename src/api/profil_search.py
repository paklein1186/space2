"""Recherche sémantique de l'API, sans Chroma : le disque de l'hébergeur est
éphémère et data/chroma_db n'est pas versionné. Deux types de documents :

- "profil_lieu" : `lieu_derive.profil_semantique_texte` (Supabase) — sauf pour
  les lieux ayant des réponses confidentielles, dont le profil est reconstitué
  depuis la synthèse publique ;
- "objet_ctg" : objets Changethegame de connaissance (organisations, quêtes,
  entités, posts ; voir agent/objets_ctg.py).

Les embeddings Voyage sont gardés en mémoire et ne sont recalculés que pour les
documents modifiés. Une fois l'index construit, l'expiration du TTL relance le
rafraîchissement en arrière-plan : les questions continuent d'être servies avec
l'index existant, sans payer le calcul dans leur budget de temps."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Optional

import numpy as np

from ..agent.objets_ctg import est_connaissance, texte_objet
from ..db.store import Store
from .donnees_completes import texte_profil_partageable

TTL_SECONDES = 1800


class ProfilSearch:
    def __init__(self, store: Store, embedder=None, ttl: float = TTL_SECONDES):
        self.store, self.ttl = store, ttl
        self._embedder = embedder
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
            hashes = {i: hashlib.sha256(t.encode("utf-8")).hexdigest() for i, (_, _, t) in docs.items()}
            # Copie puis échange : une recherche en cours continue de lire
            # l'ancien index, jamais un dictionnaire modifié sous ses pieds.
            vecteurs = {i: x for i, x in self._vecteurs.items() if i in docs}
            a_calculer = [i for i in docs if vecteurs.get(i, (None,))[0] != hashes[i]]
            if a_calculer:
                calcules = self.embedder.embed_documents([docs[i][2] for i in a_calculer])
                for i, v in zip(a_calculer, calcules):
                    v = np.asarray(v, dtype=float)
                    vecteurs[i] = (hashes[i], v / (np.linalg.norm(v) or 1.0))
            self._vecteurs, self._docs = vecteurs, docs
            self._charge_a = time.monotonic()

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

    def search(self, query: str, top_k: int = 6, doc_type: Optional[str] = None) -> list:
        if self._charge_a is None:
            self.rafraichir()   # premier appel : pas d'index à servir en attendant
        elif time.monotonic() - self._charge_a >= self.ttl:
            self._rafraichir_en_arriere_plan()
        vecteurs, docs = self._vecteurs, self._docs
        ids = [i for i in vecteurs if doc_type is None or docs[i][0] == doc_type]
        if not ids:
            return []
        q = np.asarray(self.embedder.embed_query(query), dtype=float)
        q = q / (np.linalg.norm(q) or 1.0)
        scores = np.array([float(vecteurs[i][1] @ q) for i in ids])
        hits = []
        for idx in np.argsort(-scores)[:max(1, top_k)]:
            i = ids[idx]
            type_doc, nom, texte = docs[i]
            cle = "tiers_lieu_id" if type_doc == "profil_lieu" else "ctg_id"
            hits.append({"text": texte, "distance": round(1 - float(scores[idx]), 4),
                         "metadata": {"doc_type": type_doc, cle: i.split("::", 1)[1], "source_file": nom}})
        return hits
