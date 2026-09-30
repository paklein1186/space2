"""Extraction assistée de lieux candidats depuis un document de la base de
connaissances (guide, rapport...) : un appel LLM (Haiku 4.5) propose des
lieux nommés mentionnés dans le texte, avec une citation à l'appui. Ne crée
JAMAIS de lieu directement — chaque candidat reste au statut "propose"
(CandidatLieu, voir db/store.py) jusqu'à ce qu'un admin l'accepte ou le
rejette depuis le panneau d'administration (accepter_candidat/rejeter_candidat
ci-dessous). Un candidat dont le nom ressemble à un lieu déjà recensé est
écarté avant même d'être proposé, pour ne pas alourdir la relecture."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Optional

from anthropic import Anthropic

from ..db.store import CandidatLieu, LieuDerive, Store
from .usage import log_usage

MODEL = "claude-haiku-4-5"
PROMPT_VERSION = "extraction-connaissance-v1"
# ~150 000 tokens en français (marge sous le contexte de Haiku) : au-delà,
# le document est tronqué plutôt que de faire échouer l'appel.
MAX_CARACTERES_SOURCE = 600_000

PROMPT_TEMPLATE = """Voici le texte intégral d'un document ({source_label}). Repère les tiers-lieux, lieux
hybrides ou espaces concrets NOMMÉS explicitement dans ce texte (par leur nom propre), qui pourraient être
ajoutés au recensement de la plateforme "Lieux hybrides et territoires" — pas des lieux génériques ou
hypothétiques donnés en exemple théorique, seulement des lieux réels et identifiés par leur nom.

Pour chacun, donne :
- nom : le nom exact du lieu tel qu'il apparaît dans le texte
- description : 1 à 3 phrases résumant ce que le texte en dit (activité, spécificité, ce qui le rend
  pertinent) — uniquement à partir du texte, n'invente rien
- commune : la commune ou localité mentionnée pour ce lieu, si le texte la précise (sinon null)
- pays : le pays, si mentionné ou clairement déductible du contexte (sinon null)
- citation : une courte citation exacte du texte (une phrase) qui justifie l'existence de ce lieu

N'invente aucun lieu, aucun nom, aucune donnée absente du texte. S'il n'y a aucun lieu nommé identifiable,
réponds avec une liste vide. Réponds UNIQUEMENT avec un objet JSON {{"lieux": [...]}} au format ci-dessus,
sans texte autour.

TEXTE :
{texte}
"""


def _normaliser_nom(nom: str) -> str:
    return re.sub(r"\s+", " ", (nom or "").strip()).casefold()


def _parser_json(texte_reponse: str) -> dict:
    texte_reponse = texte_reponse.strip()
    if texte_reponse.startswith("```"):
        texte_reponse = texte_reponse.split("```")[1]
        if texte_reponse.startswith("json"):
            texte_reponse = texte_reponse[4:]
    return json.loads(texte_reponse)


def extraire_candidats(store: Store, texte: str, source_label: str, client: Optional[Anthropic] = None) -> dict:
    """Analyse `texte` et enregistre les lieux candidats retenus (statut
    "propose"). Renvoie {"proposes": n, "doublons_ecartes": n, "tronque"?:
    True, "erreur"?: str}."""
    texte = (texte or "").strip()
    if not texte:
        return {"proposes": 0, "doublons_ecartes": 0}

    tronque = len(texte) > MAX_CARACTERES_SOURCE
    prompt = PROMPT_TEMPLATE.format(source_label=source_label, texte=texte[:MAX_CARACTERES_SOURCE])
    client = client or Anthropic(timeout=120.0)
    try:
        response = client.messages.create(model=MODEL, max_tokens=4000,
                                          messages=[{"role": "user", "content": prompt}])
    except Exception as exc:
        return {"erreur": f"{type(exc).__name__}: {exc}"}
    log_usage(store, "extraction_lieux", MODEL, response.usage)

    texte_reponse = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = _parser_json(texte_reponse)
    except (json.JSONDecodeError, IndexError) as exc:
        return {"erreur": f"Réponse du modèle illisible : {exc}"}

    noms_existants = {_normaliser_nom(l.nom) for l in store.list_tiers_lieux()}
    proposes, doublons = 0, 0
    for item in data.get("lieux") or []:
        nom = (item.get("nom") or "").strip()
        if not nom:
            continue
        if _normaliser_nom(nom) in noms_existants:
            doublons += 1
            continue
        store.save_candidat_lieu(CandidatLieu(
            nom=nom, description=(item.get("description") or "").strip(), source_label=source_label,
            commune=item.get("commune") or None, pays=item.get("pays") or None,
            citation=(item.get("citation") or "").strip() or None,
        ))
        noms_existants.add(_normaliser_nom(nom))  # écarte les doublons entre eux dans la même réponse
        proposes += 1

    resultat = {"proposes": proposes, "doublons_ecartes": doublons}
    if tronque:
        resultat["tronque"] = True
    return resultat


def accepter_candidat(store: Store, candidat: CandidatLieu, admin_user_id: str):
    """Crée (ou rattache si le nom existe déjà) le lieu Space2 correspondant
    à un candidat validé par un admin : synthèse minimale issue du document
    source, indexée pour la recherche sémantique, note de provenance pour
    que le lieu concerné puisse la compléter. Jamais publié au Portfolio
    automatiquement — à la discrétion de l'admin, comme pour tout autre lieu.
    Renvoie le TiersLieu créé ou rattaché."""
    lieu = store.get_or_create_tiers_lieu(admin_user_id, candidat.nom)
    champs = {}
    if candidat.pays and not lieu.pays:
        champs["pays"] = candidat.pays
    if candidat.commune and not lieu.commune:
        champs["commune"] = candidat.commune
    if champs:
        store.update_tiers_lieu(lieu.id, **champs)
        for cle, valeur in champs.items():
            setattr(lieu, cle, valeur)

    if store.get_lieu_derive(lieu.id) is None:
        donnees = {"resume": candidat.description}
        source_hash = sha256(f"{candidat.id}:{candidat.description}".encode("utf-8")).hexdigest()
        profil_texte = f"{candidat.nom} — {candidat.description}"
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu.id, donnees=donnees, profil_semantique_texte=profil_texte,
            prompt_version=PROMPT_VERSION, model=MODEL, source_hash=source_hash))
        store.update_lieu_derive_publique(lieu.id, donnees, source_hash)
        try:
            # Indexation sémantique immédiate : un bonus, jamais bloquant
            # pour l'acceptation elle-même (VOYAGE_API_KEY peut manquer).
            from .embeddings import VoyageEmbedder
            from .vectorstore import get_vectorstore

            embedding = VoyageEmbedder().embed_documents([profil_texte])[0]
            get_vectorstore().upsert(
                ids=[f"profil_lieu::{lieu.id}"], embeddings=[embedding], documents=[profil_texte],
                metadatas=[{"doc_type": "profil_lieu", "tiers_lieu_id": lieu.id, "source_file": lieu.nom}])
        except Exception:
            pass

    contributeur = store.get_or_create_contributeur(admin_user_id, lieu.id, "steward")
    citation = f" Citation : « {candidat.citation} »." if candidat.citation else ""
    store.save_free_text_note(
        lieu.id, contributeur.id, "extraction_connaissance",
        f"Lieu repéré automatiquement dans « {candidat.source_label} », à vérifier et compléter par le "
        f"lieu concerné.{citation}",
    )
    store.traiter_candidat_lieu(candidat.id, "accepte", lieu.id, admin_user_id)
    return lieu


def rejeter_candidat(store: Store, candidat_id: str, admin_user_id: str) -> None:
    store.traiter_candidat_lieu(candidat_id, "rejete", None, admin_user_id)
