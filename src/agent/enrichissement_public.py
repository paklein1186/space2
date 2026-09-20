"""Synthèse PUBLIQUE d'un lieu — la seule qui sorte vers l'API et Changethegame.

Contrairement à `enrichissement.enrich_lieu` (qui lit toutes les réponses, y
compris confidentielles ou réservées aux rôles internes), celle-ci ne reçoit
que : les réponses non confidentielles, hors contributeurs bloqués, portant
sur des champs publics (voir schema.champ_public). Les notes libres sont
exclues (aucun marqueur de confidentialité). Un appel Haiku par lieu, ignoré
tant que les réponses publiques n'ont pas changé.

Usage en masse : python3 -m src.agent.enrichissement_public [--force]"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Optional

from anthropic import Anthropic

from ..db.store import Store
from ..questionnaire.schema import CATEGORIES_POSSIBLES, champ_public, get_field
from .usage import log_usage

MODEL = "claude-haiku-4-5"

# Sections volontairement absentes : gouvernance, ressources, modele_economique
# reposent surtout sur des champs internes (finances, RH).
CHAMPS_PUBLICS_DERIVES = [
    "resume", "activites", "publics", "territoire", "besoins", "partenaires",
    "competences", "projets", "enjeux", "mots_cles", "categories",
]

PROMPT_TEMPLATE = """Voici des réponses PUBLIQUES collectées pour un tiers-lieu. Chaque réponse est précédée
de son identifiant technique entre crochets :

{reponses_texte}

Produis un JSON avec exactement ces clés :
- resume : 1-2 phrases de synthèse du lieu
- activites : synthèse des activités et services proposés
- publics : synthèse des publics accueillis
- territoire : synthèse de l'ancrage territorial
- besoins : synthèse des besoins exprimés
- partenaires : synthèse des partenariats
- competences : compétences ou savoir-faire distinctifs
- projets : projets en cours ou à venir
- enjeux : enjeux principaux identifiés
- mots_cles : liste de 5-10 mots-clés
- categories : liste (0 à {nb_categories} éléments) parmi EXACTEMENT : {categories_possibles}

Chaque synthèse textuelle fait 1 à 3 phrases. N'invente RIEN qui ne soit pas dans les réponses ci-dessus :
si une section manque d'information, mets une chaîne vide. Réponds UNIQUEMENT avec l'objet JSON.
"""


def reponses_publiques(store: Store, tiers_lieu_id: str) -> dict:
    brutes = store.get_public_answers_batch([tiers_lieu_id]).get(tiers_lieu_id, {})
    return {champ_id: v for champ_id, v in brutes.items() if champ_public(champ_id) and v not in (None, "", [])}


def hash_reponses(reponses: dict) -> str:
    return hashlib.sha256(json.dumps(reponses, sort_keys=True, ensure_ascii=False, default=str)
                          .encode("utf-8")).hexdigest()


def enrichir_public(store: Store, tiers_lieu_id: str, force: bool = False,
                    client: Optional[Anthropic] = None) -> bool:
    """Renvoie True si la synthèse publique a été (re)calculée. Sans réponse
    publique, ou sans ligne lieu_derive, ne fait rien."""
    derive = store.get_lieu_derive(tiers_lieu_id)
    reponses = reponses_publiques(store, tiers_lieu_id)
    if derive is None or not reponses:
        return False
    source_hash = hash_reponses(reponses)
    if derive.donnees_publiques and derive.donnees_publiques_source_hash == source_hash and not force:
        return False

    lignes = [f"[{cid}] {get_field(cid).label}: {valeur}" for cid, valeur in reponses.items()]
    prompt = PROMPT_TEMPLATE.format(
        reponses_texte="\n".join(lignes), nb_categories=len(CATEGORIES_POSSIBLES),
        categories_possibles=", ".join(CATEGORIES_POSSIBLES))
    client = client or Anthropic(timeout=90.0)
    response = client.messages.create(model=MODEL, max_tokens=2500,
                                      messages=[{"role": "user", "content": prompt}])
    log_usage(store, "enrichissement", MODEL, response.usage, tiers_lieu_id)

    texte = "".join(b.text for b in response.content if b.type == "text").strip()
    if texte.startswith("```"):
        texte = texte.split("```")[1]
        if texte.startswith("json"):
            texte = texte[4:]
    data = json.loads(texte)
    donnees = {k: data.get(k) for k in CHAMPS_PUBLICS_DERIVES}
    donnees["categories"] = [c for c in (donnees.get("categories") or []) if c in CATEGORIES_POSSIBLES]
    store.update_lieu_derive_publique(tiers_lieu_id, donnees, source_hash)
    return True


def main(force: bool = False) -> None:
    from dotenv import load_dotenv

    from ..db.factory import get_admin_store

    load_dotenv()
    store = get_admin_store()
    lieux = store.list_tiers_lieux()
    faits = 0
    for lieu in lieux:
        try:
            if enrichir_public(store, lieu.id, force=force):
                faits += 1
                print(f"[ok]   {lieu.nom}")
        except Exception as exc:
            print(f"[fail] {lieu.nom}: {type(exc).__name__}: {exc}")
    print(f"{faits} synthèse(s) publique(s) calculée(s) sur {len(lieux)} lieu(x).")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
