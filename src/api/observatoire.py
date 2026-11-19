"""Observatoire et enquêtes pour le site Trois-Tiers (lecture seule, clé du site).

- agregats() : les chiffres de la page Observatoire de Space2, en JSON, et
  UNIQUEMENT des agrégats (comptages, sommes, moyennes) — jamais une ligne par
  lieu, ni un texte d'enjeu ou de besoin. Sous SEUIL_MIN_LIEUX lieux dans le
  périmètre demandé, seules les totaux sont renvoyés : une répartition sur 1 ou
  2 lieux permettrait de les reconnaître (ex. le statut juridique du seul lieu
  d'une région).
- campagnes_publiques() : les enquêtes actives (titre, description, code du lien
  direct ?campagne=...), telles qu'on les diffuse déjà par flyer ou QR code.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from typing import Optional

import pandas as pd

from src.questionnaire.schema import BANDE_INTENSITE, CATEGORIES_POSSIBLES

SEUIL_MIN_LIEUX = 3
TTL_SECONDES = 600

_cache: dict = {}
_cache_lock = threading.Lock()


def _norm(t) -> str:
    s = unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode()
    return s.lower().strip()


def _compte(series: pd.Series, ordre: Optional[list] = None, top: Optional[int] = None) -> list:
    """[{valeur, n}] trié par effectif (ou selon `ordre`), sans valeurs vides."""
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    if s.empty:
        return []
    vc = s.astype(str).value_counts()
    if ordre is not None:
        vc = vc.reindex(ordre).dropna()
    if top:
        vc = vc.head(top)
    return [{"valeur": k, "n": int(v)} for k, v in vc.items()]


def _liste_eclatee(col: pd.Series) -> pd.Series:
    return pd.Series([x for xs in col.dropna() for x in (xs if isinstance(xs, list) else [xs])])


def agregats(df_lieux: pd.DataFrame, df_reponses: pd.DataFrame,
             pays: Optional[list] = None, region: Optional[str] = None) -> dict:
    """Agrégats de l'Observatoire, filtrés par pays (liste, sans tenir compte des
    accents ni de la casse) et/ou région."""
    def filtre(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        if pays:
            voulus = {_norm(p) for p in pays}
            df = df[df["pays"].map(_norm).isin(voulus)]
        if region:
            df = df[df["region"].map(_norm) == _norm(region)]
        return df

    lieux, reponses = filtre(df_lieux), filtre(df_reponses)
    # Un lieu ne compte qu'une fois par champ, même si plusieurs contributeurs ont répondu.
    reponses = reponses.drop_duplicates(subset=["tiers_lieu", "champ_id"]) if not reponses.empty else reponses

    def valeurs(champ_id: str) -> pd.Series:
        if reponses.empty:
            return pd.Series(dtype=object)
        return reponses[reponses["champ_id"] == champ_id]["valeur"]

    n = int(len(lieux))
    resultat = {
        "perimetre": {"pays": pays or [], "region": region},
        "seuil_min_lieux": SEUIL_MIN_LIEUX,
        "totaux": {
            "lieux": n,
            "pays": int(lieux["pays"].nunique(dropna=True)) if n else 0,
            "regions": int(lieux["region"].nunique(dropna=True)) if n else 0,
        },
        "repartitions": None,
    }
    if n < SEUIL_MIN_LIEUX:
        return resultat

    surfaces = pd.to_numeric(valeurs("surface_batie_m2"), errors="coerce").dropna()
    etp = pd.to_numeric(valeurs("etp_geres"), errors="coerce").dropna()
    freq = pd.to_numeric(valeurs("frequentation_semaine_type"), errors="coerce").dropna()
    resultat["totaux"].update({
        "surface_batie_m2": {"total": int(surfaces.sum()), "n": int(len(surfaces))} if len(surfaces) else None,
        "etp_geres": {"total": float(etp.sum()), "n": int(len(etp))} if len(etp) else None,
        "frequentation_semaine_moyenne": {"moyenne": round(float(freq.mean())), "n": int(len(freq))} if len(freq) else None,
    })

    dates = valeurs("date_ouverture").dropna().astype(str)
    annees = dates.map(lambda d: (re.search(r"(19|20)\d{2}", d) or [None])[0]).dropna()

    resultat["repartitions"] = {
        "categories": _compte(_liste_eclatee(lieux["categories"]) if "categories" in lieux else pd.Series(dtype=object),
                              ordre=CATEGORIES_POSSIBLES),
        "pays": _compte(lieux["pays"]),
        "regions": _compte(lieux["region"], top=15),
        "milieu": _compte(valeurs("milieu")),
        "annee_ouverture": sorted(_compte(annees), key=lambda x: x["valeur"]),
        "statut_juridique": _compte(valeurs("statut_juridique")),
        "evolution_frequentation_3ans": _compte(valeurs("evolution_frequentation_3ans")),
        "mode_acces": {
            mode: _compte(valeurs(f"usagers_mode_{mode}"), ordre=BANDE_INTENSITE)
            for mode in ("voiture", "velo", "pied", "transport_commun")
        },
        "provenance": {
            p: _compte(valeurs(f"provenance_usagers_{p}"), ordre=BANDE_INTENSITE)
            for p in ("commune", "limitrophe", "plus_loin")
        },
        "mots_cles": _compte(_liste_eclatee(lieux["mots_cles"]) if "mots_cles" in lieux else pd.Series(dtype=object), top=20),
    }
    return resultat


def donnees(store) -> tuple:
    """(df_lieux, df_reponses), gardés TTL_SECONDES en mémoire : la lecture complète est lourde."""
    from src.agent.rag_tools import lieux_enrichis_dataframe, reponses_long_dataframe
    with _cache_lock:
        if _cache.get("quand", 0) + TTL_SECONDES > time.monotonic():
            return _cache["valeur"]
    valeur = (lieux_enrichis_dataframe(store), reponses_long_dataframe(store))
    with _cache_lock:
        _cache.update(quand=time.monotonic(), valeur=valeur)
    return valeur


def campagnes_publiques(store) -> list:
    """Enquêtes actives : de quoi afficher un bouton vers le lien direct ?campagne=<code>."""
    return [
        {
            "code": c.code or c.id,
            "titre": c.titre,
            "description": c.description,
            "date_fin": c.date_fin,
        }
        for c in store.get_active_campagnes_prioritaires()
    ]
