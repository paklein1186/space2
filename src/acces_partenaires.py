"""Accès partenaires à une campagne prioritaire (page ?partenaire=<code>).

Un partenaire territorial ne voit une campagne que si un admin a inscrit
au préalable son email pour CETTE campagne (table campagne_acces_partenaires,
service_role uniquement), et seulement après s'être connecté avec un code à
usage unique reçu sur cet email (Supabase Auth) — l'email comparé est donc
celui vérifié par la connexion, jamais une saisie libre.

Logique pure (sans Streamlit), testée dans tests/test_acces_partenaires.py.
"""

from __future__ import annotations

import re
from typing import Optional

from src.db.store import normaliser_emails

_EMAIL_VALIDE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")


def parser_emails(texte: str) -> tuple:
    """Découpe une saisie admin (un email par ligne, ou séparés par virgules/
    points-virgules/espaces) en (valides, invalides). Les valides sont
    normalisés (minuscules, dédoublonnés, triés) ; les invalides sont
    renvoyés tels que saisis pour être signalés, jamais enregistrés."""
    morceaux = [m for m in re.split(r"[\s,;]+", texte or "") if m]
    valides, invalides = [], []
    for m in morceaux:
        (valides if _EMAIL_VALIDE.match(m.strip().lower()) else invalides).append(m)
    return normaliser_emails(valides), invalides


def campagnes_visibles(store, email: Optional[str], est_admin: bool) -> list:
    """Campagnes que la personne connectée peut consulter sur la page
    partenaire : toutes pour un admin, sinon uniquement celles pour
    lesquelles son email a été inscrit. Toutes fenêtres confondues (un
    partenaire doit pouvoir relire une campagne close)."""
    campagnes = store.list_campagnes_prioritaires()
    if est_admin:
        return campagnes
    if not email:
        return []
    autorisees = set(store.campagne_ids_pour_partenaire(email))
    return [c for c in campagnes if c.id in autorisees]


def campagne_demandee(campagnes: list, code_ou_id: Optional[str]):
    """Résout ?campagne=<code ou uuid> parmi les campagnes VISIBLES — None
    si absent de la liste (inconnue ou non autorisée : on ne distingue pas
    les deux, pour ne pas révéler l'existence d'une campagne)."""
    if not code_ou_id:
        return None
    for c in campagnes:
        if c.id == code_ou_id or (c.code and c.code == code_ou_id):
            return c
    return None
