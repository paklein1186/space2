"""Jeux de données agrégés de l'Observatoire, mis en cache partagé entre toutes
les sessions du serveur (10 min) et préchargés en arrière-plan au démarrage
de l'app — sans ça, chaque visite relisait toute la base (~10 s)."""

from __future__ import annotations

import threading

import streamlit as st

from src.agent.rag_tools import lieux_enrichis_dataframe, reponses_long_dataframe
from src.db.factory import get_admin_store, get_store


def _store_pour_agregats():
    """Statistiques publiques : utilise le store admin (service_role) plutôt
    que le store public pour cette page. Raison — pas un choix de facilité :
    reponses_long_dataframe() passe par get_all_answers_by_contributeur(),
    qui filtre d'abord les contributeurs bloqués via une lecture de la table
    `contributeurs` ; or RLS n'y autorise un utilisateur qu'à voir SES
    PROPRES lignes (user_id = auth.uid()) — pour un visiteur anonyme,
    auth.uid() est nul, cette lecture ne renvoie donc jamais aucune ligne, et
    le filtre "contributeur actif" exclut alors TOUTES les réponses par
    excès de prudence. Résultat concret constaté : les graphiques "Milieu",
    "Statut juridique", "Année d'ouverture" restaient vides pour tout
    visiteur non connecté, alors que `reponses` a bien une policy RLS
    publique — seule la vérification de blocage, en amont, coupait tout.
    Seuls des agrégats (comptages, distributions) quittent cette page,
    jamais de donnée nominative, donc contourner RLS ici reste sûr. Repli
    sur le store public si la clé service_role n'est pas configurée, pour ne
    jamais faire planter une page publique pour cette seule raison."""
    try:
        return get_admin_store()
    except RuntimeError:
        return get_store()


@st.cache_data(ttl=600, show_spinner=False)
def donnees_observatoire():
    store = _store_pour_agregats()
    return lieux_enrichis_dataframe(store), reponses_long_dataframe(store)


@st.cache_resource(show_spinner=False)
def prechargement_observatoire() -> threading.Thread:
    """Lancé une seule fois par processus serveur : la première visite de
    l'Observatoire trouve alors les données déjà prêtes au lieu de les lire."""
    fil = threading.Thread(target=donnees_observatoire, daemon=True)
    fil.start()
    return fil
