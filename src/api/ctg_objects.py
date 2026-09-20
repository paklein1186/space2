"""Traitement de PUT /ctg/objects : objets Changethegame (guildes, quêtes,
entreprises, posts...).

- Tous les objets sont enregistrés (upsert par ctg_id) dans `objets_ctg` ;
  ceux qui ne sont pas des lieux ne servent que de connaissance (dataset
  `organisations_ctg`, recherche sémantique) — jamais galerie/portfolio.
- Un objet kind "lieu" avec is_place=true crée le lieu dans la bibliothèque
  s'il n'existe pas (ctg_entity_id = id de la guilde), avec une synthèse
  minimale tirée de ctg, et l'inclut dans la galerie (Annuaire, qui liste tous
  les lieux) et le Portfolio (inclus_portfolio). Un lieu déjà connu — lié, ou
  de même nom et pas encore lié — est rattaché sans que ses données Space2
  soient écrasées ni son statut Portfolio modifié.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from typing import Optional

from ..db.store import LieuDerive, Store

PROMPT_VERSION_CTG = "ctg-import-v1"
PAYS_CONNUS = {"belgique": "Belgique", "belgium": "Belgique", "france": "France"}
_CHAMPS_SYNTHESE = ["resume", "activites", "publics", "territoire", "besoins", "partenaires",
                    "competences", "projets", "enjeux", "mots_cles", "categories"]


def _norm(nom: str) -> str:
    return re.sub(r"\s+", " ", (nom or "").strip()).casefold()


def uuid_de(ctg_id: str) -> str:
    return ctg_id.split(":", 1)[1]


def proprietaire_par_defaut(store: Store, lieux: list) -> Optional[str]:
    """Propriétaire (auth.users) des lieux créés depuis ctg : CTG_OWNER_USER_ID
    s'il est défini ; sinon le propriétaire le plus fréquent des lieux
    existants (toujours un utilisateur valide)."""
    env = os.environ.get("CTG_OWNER_USER_ID", "").strip()
    if env:
        return env
    proprietaires = Counter(l.owner_user_id for l in lieux)
    return proprietaires.most_common(1)[0][0] if proprietaires else None


def synthese_ctg(obj: dict) -> dict:
    """Synthèse minimale d'un lieu créé depuis ctg : la description ctg
    sert de résumé, les thèmes de mots-clés, les territoires d'ancrage."""
    territoire = ", ".join(x for x in [obj.get("commune"), *(obj.get("territories") or [])] if x)
    donnees = {k: None for k in _CHAMPS_SYNTHESE}
    donnees.update({"resume": obj.get("description") or None, "territoire": territoire or None,
                    "mots_cles": list(obj.get("topics") or []), "categories": []})
    return donnees


def _hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(
        [obj.get("name"), obj.get("description"), obj.get("topics"), obj.get("territories"), obj.get("commune")],
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _pays(obj: dict) -> Optional[str]:
    for t in obj.get("territories") or []:
        if _norm(t) in PAYS_CONNUS:
            return PAYS_CONNUS[_norm(t)]
    return None


def _ecrire_synthese_ctg(store: Store, tiers_lieu_id: str, obj: dict) -> None:
    donnees = synthese_ctg(obj)
    h = _hash(obj)
    profil = " ".join(x for x in [obj.get("name"), obj.get("description"),
                                  ", ".join(obj.get("topics") or [])] if x)
    store.save_lieu_derive(LieuDerive(
        tiers_lieu_id=tiers_lieu_id, donnees=donnees, profil_semantique_texte=profil or obj["name"],
        prompt_version=PROMPT_VERSION_CTG, model="ctg", source_hash=h))
    # Synthèse publique : le contenu vient de ctg, déjà public par nature.
    store.update_lieu_derive_publique(tiers_lieu_id, donnees, h)


def appliquer_lieu(store: Store, obj: dict, lieux: list) -> dict:
    """Crée ou rattache le lieu d'un objet kind "lieu"/is_place. Renvoie
    {"tiers_lieu_id", "action": "created"|"linked"|"updated"} ou
    {"error": raison}."""
    if not obj["ctg_id"].startswith("guild:"):
        return {"error": "un lieu doit venir d'une guilde (ctg_id 'guild:<uuid>')"}
    guilde = uuid_de(obj["ctg_id"])

    existant = next((l for l in lieux if l.ctg_entity_id == guilde), None)
    action = "updated"
    if existant is None:
        par_nom = next((l for l in lieux if _norm(l.nom) == _norm(obj["name"])), None)
        if par_nom is not None and par_nom.ctg_entity_id and par_nom.ctg_entity_id != guilde:
            return {"error": f"le nom « {obj['name']} » est déjà utilisé par un lieu lié à une autre guilde"}
        if par_nom is not None:
            existant, action = par_nom, "linked"
            store.update_tiers_lieu(par_nom.id, ctg_entity_id=guilde)
            par_nom.ctg_entity_id = guilde
        else:
            proprio = proprietaire_par_defaut(store, lieux)
            if not proprio:
                return {"error": "aucun propriétaire pour créer le lieu (définir CTG_OWNER_USER_ID)"}
            existant = store.get_or_create_tiers_lieu(proprio, obj["name"])
            existant.ctg_entity_id = guilde
            lieux.append(existant)
            action = "created"
            champs = {"ctg_entity_id": guilde}
            if _pays(obj):
                champs["pays"] = _pays(obj)
            store.update_tiers_lieu(existant.id, **champs)
            existant.pays = champs.get("pays")

    # Complète sans écraser : coordonnées et commune seulement si absentes.
    manque = {}
    if existant.latitude is None and obj.get("latitude") is not None and obj.get("longitude") is not None:
        manque.update(latitude=obj["latitude"], longitude=obj["longitude"])
    if not existant.commune and obj.get("commune"):
        manque["commune"] = obj["commune"]
    if not existant.pays and _pays(obj):
        manque["pays"] = _pays(obj)
    if manque:
        store.update_tiers_lieu(existant.id, **manque)
        for k, v in manque.items():
            setattr(existant, k, v)

    derive = store.get_lieu_derive(existant.id)
    if action == "created":
        _ecrire_synthese_ctg(store, existant.id, obj)
        # Galerie : l'Annuaire liste tous les lieux ; Portfolio : à cocher.
        store.update_portfolio_entry(existant.id, True, None, None, None)
    elif derive is not None and derive.prompt_version == PROMPT_VERSION_CTG:
        # Lieu encore alimenté uniquement par ctg : on rafraîchit sa synthèse.
        _ecrire_synthese_ctg(store, existant.id, obj)
    return {"tiers_lieu_id": existant.id, "action": action}


def traiter_objets(store: Store, objets: list) -> dict:
    """Upsert de tous les objets ; création/rattachement des lieux. Renvoie
    {"received", "lieux_created", "lieux_linked", "rejected": [...]}. Un
    objet lieu en échec est quand même stocké comme connaissance (sans lien
    à un lieu) : rien n'est perdu, l'erreur est signalée dans `rejected`."""
    lieux = store.list_tiers_lieux()
    rejetes, crees, lies, a_stocker = [], 0, 0, []
    recus = len(objets)
    # Un même ctg_id deux fois dans un lot ferait échouer l'upsert : le dernier gagne.
    objets = list({o["ctg_id"]: o for o in objets}.values())
    for obj in objets:
        tiers_lieu_id = None
        if obj["kind"] == "lieu" and obj["is_place"]:
            res = appliquer_lieu(store, obj, lieux)
            if "error" in res:
                rejetes.append({"ctg_id": obj["ctg_id"], "reason": res["error"]})
            else:
                tiers_lieu_id = res["tiers_lieu_id"]
                crees += res["action"] == "created"
                lies += res["action"] == "linked"
        a_stocker.append({**obj, "tiers_lieu_id": tiers_lieu_id})
    store.upsert_objets_ctg(a_stocker)
    return {"received": recus, "lieux_created": crees, "lieux_linked": lies, "rejected": rejetes}
