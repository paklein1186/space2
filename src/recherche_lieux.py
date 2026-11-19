"""Recherche texte de l'annuaire : nom, commune, code postal, région, pays.

Insensible à la casse et aux accents (« fey » trouve « Feÿ », « liege »
trouve « Liège »), et tolérante aux fautes de frappe : un mot tapé d'au
moins 4 lettres qui ressemble à un mot du lieu (« bruxeles », « Chastr »)
compte comme trouvé. Chaque mot tapé doit être trouvé (« phare andenne »).
Les correspondances approchées ne servent que s'il n'y a aucun résultat
exact : sinon « phare » ramènerait aussi « Le Havre », « namur » « Nature »."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_LIGATURES = str.maketrans({"œ": "oe", "æ": "ae", "Œ": "oe", "Æ": "ae"})
_SEUIL_APPROX = 0.8
_LONGUEUR_MIN_APPROX = 4


def normaliser(texte) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples."""
    texte = unicodedata.normalize("NFKD", str(texte or "").translate(_LIGATURES))
    texte = "".join(c for c in texte if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", texte).split())


def _texte_lieu(lieu) -> str:
    return normaliser(" ".join(str(v) for v in (lieu.nom, getattr(lieu, "commune", None),
                                                 getattr(lieu, "code_postal", None), lieu.region, lieu.pays)
                               if v))


def _mot_approchant(mot: str, mots_lieu: list) -> bool:
    if len(mot) < _LONGUEUR_MIN_APPROX:
        return False
    for m in mots_lieu:
        if abs(len(m) - len(mot)) > 2 and not m.startswith(mot[:2]):
            continue
        # Mot tapé comparé au mot entier et à son début (« chastr » ~ « chastre »,
        # « bruxel » ~ « bruxelles »).
        for cible in (m, m[:len(mot)]):
            s = SequenceMatcher(None, mot, cible)
            if s.real_quick_ratio() >= _SEUIL_APPROX and s.quick_ratio() >= _SEUIL_APPROX \
                    and s.ratio() >= _SEUIL_APPROX:
                return True
    return False


def rechercher_lieux(lieux: list, recherche: str) -> tuple:
    """(lieux trouvés dans leur ordre d'origine, approximatif) : les
    correspondances exactes, ou à défaut les approchées (approximatif=True).
    Recherche vide : tous les lieux."""
    q = normaliser(recherche)
    if not q:
        return list(lieux), False
    mots = q.split()
    textes = [(lieu, _texte_lieu(lieu)) for lieu in lieux]
    exacts = [lieu for lieu, texte in textes if all(m in texte for m in mots)]
    if exacts:
        return exacts, False
    return [lieu for lieu, texte in textes
            if all(m in texte or _mot_approchant(m, texte.split()) for m in mots)], True


def lieu_au_nom_exact(lieux: list, recherche: str):
    """Le lieu dont le nom est exactement celui tapé (accents et casse
    ignorés), s'il est unique."""
    q = normaliser(recherche)
    trouves = [l for l in lieux if q and normaliser(l.nom) == q]
    return trouves[0] if len(trouves) == 1 else None
