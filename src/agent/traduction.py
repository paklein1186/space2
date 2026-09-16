"""Traduction anglaise, à la volée, de la synthèse d'un lieu (lieu_derive.
donnees) — 1 appel LLM (Haiku 4.5) par lieu, déclenché seulement quand une
personne en langue anglaise consulte ce lieu, jamais en masse ni par avance.
Le résultat est mis en cache dans lieu_derive.donnees_en (voir
db.store.LieuDerive), invalidé automatiquement quand le contenu français
source change (comparaison à source_hash) — pas de retraduction pour rien.

Distinct de src/agent/enrichissement.py : celui-ci PRODUIT le contenu
français à partir des réponses brutes, celui-ci le TRADUIT sans jamais
retoucher au sens ni relire les réponses sources."""

from __future__ import annotations

import json

from anthropic import Anthropic

from ..db.store import LieuDerive, Store
from .enrichissement import CHAMPS_LONGUEUR_CIBLE
from .usage import log_usage

MODEL = "claude-haiku-4-5"

# resume + les 12 sections de synthèse — PAS mots_cles/categories (déjà
# traduits à l'affichage via i18n.t_categorie, mots_cles reste un indexe de
# recherche interne, jamais montré tel quel comme du texte à lire).
CHAMPS_A_TRADUIRE = ["resume"] + CHAMPS_LONGUEUR_CIBLE

PROMPT_TEMPLATE = """Traduis en anglais le contenu JSON suivant, qui décrit un lieu \
hybride/tiers-lieu (issu d'un questionnaire rempli en français). Chaque clé est une \
section de synthèse ; traduis uniquement les VALEURS, jamais les clés. Garde le même \
ton (factuel, synthétique), la même longueur approximative, et ne rajoute ni \
commentaire ni contenu absent de l'original — une traduction fidèle, pas un résumé.

JSON à traduire :
{donnees_json}

Réponds UNIQUEMENT avec le JSON traduit (mêmes clés, valeurs en anglais), sans texte \
avant ni après, sans bloc de code markdown."""


def traduire_donnees_fiche(store: Store, derive: LieuDerive) -> dict:
    """Renvoie `derive.donnees` traduit en anglais — depuis le cache si
    `donnees_en_source_hash` correspond encore à `source_hash`, sinon via un
    appel LLM dont le résultat est aussitôt mis en cache. Ne lève jamais :
    en cas d'échec (réseau, JSON invalide...), retombe sur le français plutôt
    que de casser l'affichage d'une fiche pour un aléa de traduction."""
    if derive.donnees_en and derive.donnees_en_source_hash == derive.source_hash:
        return derive.donnees_en

    a_traduire = {k: v for k, v in derive.donnees.items() if k in CHAMPS_A_TRADUIRE and v}
    if not a_traduire:
        return derive.donnees

    try:
        client = Anthropic(timeout=30.0)
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(
                donnees_json=json.dumps(a_traduire, ensure_ascii=False, indent=2),
            )}],
        )
        log_usage(store, "traduction_fiche", MODEL, response.usage, derive.tiers_lieu_id)

        texte = "".join(b.text for b in response.content if b.type == "text").strip()
        if texte.startswith("```"):
            texte = texte.split("```")[1]
            if texte.startswith("json"):
                texte = texte[4:]
        traduit = json.loads(texte)
    except Exception:
        return derive.donnees

    # Les clés non traduites (mots_cles, categories...) restent en français —
    # une fiche affichée en anglais montre quand même ses catégories/besoins
    # non textuels correctement (gérés séparément par t_categorie).
    donnees_en = {**derive.donnees, **traduit}
    try:
        store.update_lieu_derive_traduction(derive.tiers_lieu_id, donnees_en, derive.source_hash)
    except Exception:
        # La mise en cache est un pur bonus de performance (évite de
        # retraduire au prochain affichage) — si elle échoue (ex. colonnes
        # donnees_en pas encore migrées), la traduction fraîchement obtenue
        # doit quand même s'afficher MAINTENANT plutôt que planter la fiche.
        pass
    return donnees_en
