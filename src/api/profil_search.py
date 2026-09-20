"""Recherche sémantique sur les profils de lieux (doc_type "profil_lieu") pour
l'API, sans Chroma : le disque de l'hébergeur est éphémère et data/chroma_db
n'est pas versionné. Les profils viennent de `lieu_derive.profil_semantique_
texte` (Supabase) ; leurs embeddings Voyage sont calculés une fois, gardés en
mémoire et ne sont recalculés que pour les profils modifiés."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Optional

import numpy as np

from ..db.store import Store
from .donnees_completes import texte_profil_partageable

TTL_SECONDES = 1800


class ProfilSearch:
    def __init__(self, store: Store, embedder=None, ttl: float = TTL_SECONDES):
        self.store, self.ttl = store, ttl
        self._embedder = embedder
        self._lock = threading.Lock()
        self._vecteurs: dict = {}   # tiers_lieu_id -> (hash, vecteur normalisé)
        self._profils: dict = {}    # tiers_lieu_id -> (nom, texte)
        self._charge_a: Optional[float] = None

    @property
    def embedder(self):
        if self._embedder is None:
            from ..agent.embeddings import VoyageEmbedder
            self._embedder = VoyageEmbedder()
        return self._embedder

    def rafraichir(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._charge_a is not None and time.monotonic() - self._charge_a < self.ttl:
                return
            lieux = {lieu.id: lieu for lieu in self.store.list_tiers_lieux()}
            derives = self.store.get_lieu_derive_batch(list(lieux))
            confidentiels = self.store.get_lieux_avec_confidentiel(list(lieux))
            textes = {i: texte_profil_partageable(d, i in confidentiels) for i, d in derives.items()}
            profils = {i: (lieux[i].nom, t) for i, t in textes.items() if t}
            hashes = {i: hashlib.sha256(t.encode("utf-8")).hexdigest() for i, (_, t) in profils.items()}
            a_calculer = [i for i in profils if self._vecteurs.get(i, (None,))[0] != hashes[i]]
            if a_calculer:
                vecteurs = self.embedder.embed_documents([profils[i][1] for i in a_calculer])
                for i, v in zip(a_calculer, vecteurs):
                    v = np.asarray(v, dtype=float)
                    self._vecteurs[i] = (hashes[i], v / (np.linalg.norm(v) or 1.0))
            self._vecteurs = {i: x for i, x in self._vecteurs.items() if i in profils}
            self._profils = profils
            self._charge_a = time.monotonic()

    def search(self, query: str, top_k: int = 6) -> list:
        self.rafraichir()
        if not self._vecteurs:
            return []
        q = np.asarray(self.embedder.embed_query(query), dtype=float)
        q = q / (np.linalg.norm(q) or 1.0)
        ids = list(self._vecteurs)
        scores = np.array([float(self._vecteurs[i][1] @ q) for i in ids])
        hits = []
        for idx in np.argsort(-scores)[:max(1, top_k)]:
            i = ids[idx]
            nom, texte = self._profils[i]
            hits.append({"text": texte, "distance": round(1 - float(scores[idx]), 4),
                         "metadata": {"doc_type": "profil_lieu", "tiers_lieu_id": i, "source_file": nom}})
        return hits
