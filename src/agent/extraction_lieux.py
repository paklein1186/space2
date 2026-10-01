"""Extraction assistée de lieux candidats depuis un document de la base de
connaissances (guide, rapport...) : un appel LLM (Haiku 4.5) propose des
lieux nommés mentionnés dans le texte, avec une citation à l'appui. Ne crée
JAMAIS de lieu directement — chaque candidat reste au statut "propose"
(CandidatLieu, voir db/store.py) jusqu'à ce qu'un admin l'accepte ou le
rejette depuis le panneau d'administration (accepter_candidat/rejeter_candidat
ci-dessous).

Un nom qui correspond à un lieu déjà recensé (une fois la casse, les accents
et la ponctuation normalisés) n'est jamais reproposé comme nouveau lieu : le
candidat pointe directement vers ce lieu (tiers_lieu_id), et sa validation
compile une note plutôt que de créer un doublon — vécu : "Quatre-Quarts"
(trait d'union) et "Quatre Quarts" (espace, déjà recensé) sont la même
adresse. Un nom qui RESSEMBLE fortement à un lieu déjà recensé, sans être une
correspondance certaine (ex. "La PILE - Pépinière d'Initiatives..." pour le
lieu déjà recensé "La PILE"), n'est PAS fusionné automatiquement — le risque
de rapprocher deux lieux réellement distincts qui partagent un mot est trop
réel pour une fusion silencieuse — mais signalé (suggerer_lieu_proche) pour
qu'un admin tranche en connaissance de cause plutôt que de créer un doublon
sans le savoir."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
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

Voici les lieux DÉJÀ recensés sur la plateforme (nom — commune, pays) :
{lieux_existants}

Pour chacun des lieux que tu repères dans le texte, donne :
- nom : le nom exact du lieu tel qu'il apparaît dans le texte
- description : 1 à 3 phrases résumant ce que le texte en dit (activité, spécificité, ce qui le rend
  pertinent) — uniquement à partir du texte, n'invente rien
- commune : la commune ou localité mentionnée pour ce lieu, si le texte la précise (sinon null)
- pays : le pays, si mentionné ou clairement déductible du contexte (sinon null)
- citation : une courte citation exacte du texte (une phrase) qui justifie l'existence de ce lieu
- lieu_existant : si ce lieu est en réalité LE MÊME que l'un de ceux déjà recensés listés ci-dessus — même
  sous un autre nom, une abréviation, une ancienne dénomination, une graphie différente ou formulé
  autrement —, le nom EXACT de ce lieu existant, copié caractère pour caractère depuis la liste fournie.
  Base-toi sur le sens et le contexte (même commune, même activité, même historique), pas seulement sur
  une ressemblance textuelle superficielle : un nom partagé par coïncidence entre deux lieux bien distincts
  ne doit PAS être rapproché. Si tu as un doute raisonnable, mets null plutôt que de rapprocher à tort —
  dans le doute, un nouveau lieu proposé par erreur est sans conséquence (un humain le validera), alors
  qu'un rapprochement erroné pourrait associer l'information d'un lieu à la fiche d'un autre.

N'invente aucun lieu, aucun nom, aucune donnée absente du texte. S'il n'y a aucun lieu nommé identifiable,
réponds avec une liste vide. Réponds UNIQUEMENT avec un objet JSON {{"lieux": [...]}} au format ci-dessus,
sans texte autour.

TEXTE :
{texte}
"""


DOC_TYPES_CONNAISSANCE_LONGUE = ("connaissance_bibliotheque", "connaissance_trois_tiers")
PREFIXE_ID_LONGUE = "connaissance_longue_"


def lister_documents_ingeres() -> list:
    """Documents déjà ajoutés à la base de connaissances via « Ajouter une
    connaissance depuis un lien/fichier » (ajouter_connaissance_longue),
    regroupés par source : [{"source_label", "n_passages", "date_ajout"}],
    du plus récemment ajouté au plus ancien — pour relancer l'extraction sur
    un document déjà en place sans devoir le re-uploader. N'inclut pas les
    connaissances courtes (bouton 🧠 de la Bibliothèque, scan Trois-Tiers) :
    un seul extrait chacune, sans intérêt pour repérer des lieux nommés."""
    from .vectorstore import get_vectorstore

    vectorstore = get_vectorstore()
    par_source: dict = {}
    for doc_type in DOC_TYPES_CONNAISSANCE_LONGUE:
        for doc in vectorstore.lister_documents({"doc_type": doc_type}):
            if not doc["id"].startswith(PREFIXE_ID_LONGUE):
                continue
            source = doc["metadata"].get("source_file") or "(source inconnue)"
            entree = par_source.setdefault(source, {"source_label": source, "n_passages": 0, "date_ajout": None})
            entree["n_passages"] += 1
            date = doc["metadata"].get("date_ajout")
            if date and (entree["date_ajout"] is None or date > entree["date_ajout"]):
                entree["date_ajout"] = date
    return sorted(par_source.values(), key=lambda e: e["date_ajout"] or "", reverse=True)


def recomposer_texte_document(source_label: str) -> str:
    """Reconstitue le texte d'un document déjà ingéré, à partir de ses
    passages triés selon leur position d'origine (chunk_index). Les passages
    se recouvrent légèrement (voir ingest/chunking.py) : la reconstitution
    n'est donc pas caractère pour caractère l'original, mais fidèle pour une
    relecture par le LLM d'extraction."""
    from .vectorstore import get_vectorstore

    vectorstore = get_vectorstore()
    documents = []
    for doc_type in DOC_TYPES_CONNAISSANCE_LONGUE:
        documents += vectorstore.lister_documents({"doc_type": doc_type, "source_file": source_label})
    documents = [d for d in documents if d["id"].startswith(PREFIXE_ID_LONGUE)]
    documents.sort(key=lambda d: d["metadata"].get("chunk_index", 0))
    return "\n\n".join(d["text"] for d in documents)


SEUIL_RATIO_RESSEMBLANCE = 0.72
LONGUEUR_MIN_COEUR = 6  # sous ce seuil, un cœur de nom est trop générique pour signaler une ressemblance


def _normaliser_nom(nom: str) -> str:
    """Sans accents, sans distinction trait d'union/espace/apostrophe : deux
    noms qui ne diffèrent QUE sur ces points sont la même adresse, pas deux
    lieux différents (ex. "Quatre-Quarts" / "Quatre Quarts")."""
    nom = unicodedata.normalize("NFKD", nom or "")
    nom = "".join(c for c in nom if not unicodedata.combining(c))
    nom = re.sub(r"[-–—'’]", " ", nom.casefold())
    return re.sub(r"\s+", " ", nom).strip()


def _coeur_nom(nom: str) -> str:
    """Partie avant un sous-titre explicatif (parenthèse, deux-points, tiret
    isolé) — ex. « La PILE - Pépinière d'Initiatives... » -> « La PILE »."""
    return re.split(r"\s+[-–—:]\s+|\s*\(", nom or "", maxsplit=1)[0].strip()


def suggerer_lieu_proche(nom: str, lieux_existants: list):
    """Lieu déjà recensé dont le nom RESSEMBLE fortement à `nom`, sans que la
    correspondance soit certaine (celle-ci est déjà traitée en amont, voir
    extraire_candidats) — une simple suggestion pour qu'un admin vérifie
    avant de créer un nouveau lieu, jamais une fusion automatique : un nom
    court peut être partagé par deux lieux bien distincts. Renvoie le
    TiersLieu le plus proche, ou None."""
    cle, coeur = _normaliser_nom(nom), _normaliser_nom(_coeur_nom(nom))
    meilleur, meilleur_score = None, 0.0
    for lieu in lieux_existants:
        cle_lieu, coeur_lieu = _normaliser_nom(lieu.nom), _normaliser_nom(_coeur_nom(lieu.nom))
        contient = (len(coeur) >= LONGUEUR_MIN_COEUR and coeur in cle_lieu) or \
                   (len(coeur_lieu) >= LONGUEUR_MIN_COEUR and coeur_lieu in cle)
        ratio = SequenceMatcher(None, cle, cle_lieu).ratio()
        if not (contient or ratio >= SEUIL_RATIO_RESSEMBLANCE):
            continue
        score = 1.0 if contient else ratio
        if score > meilleur_score:
            meilleur, meilleur_score = lieu, score
    return meilleur


MAX_TOKENS_REPONSE = 8000


def _degainer_balises_markdown(texte_reponse: str) -> str:
    texte_reponse = texte_reponse.strip()
    if texte_reponse.startswith("```"):
        texte_reponse = texte_reponse.split("```")[1]
        if texte_reponse.startswith("json"):
            texte_reponse = texte_reponse[4:]
    return texte_reponse.strip()


def _parser_json(texte_reponse: str, tolerant: bool = False) -> dict:
    """`tolerant=True` (réponse coupée à max_tokens, en plein milieu d'un
    objet ou d'une chaîne) : récupère les lieux dont l'objet JSON est
    complet, abandonne seulement le dernier, entamé mais coupé — plutôt que
    de perdre toute l'analyse pour un document qui en propose simplement
    plus que ce qu'un seul appel peut écrire."""
    texte_reponse = _degainer_balises_markdown(texte_reponse)
    try:
        return json.loads(texte_reponse)
    except json.JSONDecodeError:
        if not tolerant:
            raise
    for fin in reversed([m.end() for m in re.finditer(r"\}", texte_reponse)]):
        try:
            return json.loads(texte_reponse[:fin] + "]}")
        except json.JSONDecodeError:
            continue
    return {"lieux": []}  # coupé avant le moindre objet complet : rien à récupérer


def _lister_lieux_pour_prompt(lieux: list) -> str:
    if not lieux:
        return "(aucun lieu recensé pour l'instant)"
    lignes = []
    for l in sorted(lieux, key=lambda x: x.nom.lower()):
        localisation = ", ".join(x for x in (l.commune, l.pays) if x)
        lignes.append(f"- {l.nom}" + (f" — {localisation}" if localisation else ""))
    return "\n".join(lignes)


def extraire_candidats(store: Store, texte: str, source_label: str, client: Optional[Anthropic] = None) -> dict:
    """Analyse `texte` et enregistre les lieux candidats retenus (statut
    "propose") : un nouveau lieu (tiers_lieu_id encore vide) si le lieu ne
    correspond à aucun lieu recensé, sinon une info complémentaire pour le
    lieu déjà recensé (tiers_lieu_id posé dès la proposition, PAS un
    doublon écarté) — voir accepter_candidat pour ce que chacun devient une
    fois validé.

    Le rapprochement avec un lieu déjà recensé s'appuie sur la compréhension
    du modèle (la liste des lieux déjà recensés lui est fournie dans le
    prompt, avec consigne de se fonder sur le sens — un ancien nom, une
    abréviation, une autre graphie — pas sur une simple ressemblance de
    surface) plutôt que sur une comparaison de chaînes de caractères : un nom
    de lieu peut être reformulé de bien des façons dans un document, qu'une
    comparaison textuelle ne peut pas toutes anticiper. Le nom renvoyé par le
    modèle n'est accepté que s'il correspond EXACTEMENT (après normalisation)
    à un lieu de la liste fournie — jamais de confiance aveugle dans un
    identifiant halluciné.

    Renvoie {"proposes": n, "infos_existantes": n, "doublons_ecartes": n,
    "tronque"?: True, "reponse_tronquee"?: True, "erreur"?: str}.
    `doublons_ecartes` ne compte que les répétitions du même nom AU SEIN de
    cette réponse."""
    texte = (texte or "").strip()
    if not texte:
        return {"proposes": 0, "infos_existantes": 0, "doublons_ecartes": 0}

    lieux_actuels = store.list_tiers_lieux()
    tronque = len(texte) > MAX_CARACTERES_SOURCE
    prompt = PROMPT_TEMPLATE.format(source_label=source_label, texte=texte[:MAX_CARACTERES_SOURCE],
                                    lieux_existants=_lister_lieux_pour_prompt(lieux_actuels))
    client = client or Anthropic(timeout=120.0)
    try:
        response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS_REPONSE,
                                          messages=[{"role": "user", "content": prompt}])
    except Exception as exc:
        return {"erreur": f"{type(exc).__name__}: {exc}"}
    log_usage(store, "extraction_lieux", MODEL, response.usage)

    reponse_tronquee = getattr(response, "stop_reason", None) == "max_tokens"
    texte_reponse = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = _parser_json(texte_reponse, tolerant=reponse_tronquee)
    except (json.JSONDecodeError, IndexError) as exc:
        return {"erreur": f"Réponse du modèle illisible : {exc}"}

    lieux_par_nom = {_normaliser_nom(l.nom): l for l in lieux_actuels}
    noms_traites: set = set()
    proposes, infos_existantes, doublons = 0, 0, 0
    for item in data.get("lieux") or []:
        nom = (item.get("nom") or "").strip()
        if not nom:
            continue
        cle = _normaliser_nom(nom)
        if cle in noms_traites:
            doublons += 1
            continue
        noms_traites.add(cle)
        # Rapprochement choisi par le modèle, résolu UNIQUEMENT par correspondance
        # exacte contre les vrais lieux fournis dans le prompt (jamais de confiance
        # aveugle dans un nom halluciné) ; à défaut, repli sur une correspondance
        # exacte du nom du lieu lui-même (ex. le modèle a oublié de renseigner
        # lieu_existant alors que le nom repéré est déjà, tel quel, un lieu recensé).
        nom_rapproche = (item.get("lieu_existant") or "").strip()
        lieu_existant = lieux_par_nom.get(_normaliser_nom(nom_rapproche)) if nom_rapproche else None
        if lieu_existant is None:
            lieu_existant = lieux_par_nom.get(cle)
        store.save_candidat_lieu(CandidatLieu(
            nom=nom, description=(item.get("description") or "").strip(), source_label=source_label,
            commune=item.get("commune") or None, pays=item.get("pays") or None,
            citation=(item.get("citation") or "").strip() or None,
            tiers_lieu_id=lieu_existant.id if lieu_existant else None,
        ))
        if lieu_existant:
            infos_existantes += 1
        else:
            proposes += 1

    resultat = {"proposes": proposes, "infos_existantes": infos_existantes, "doublons_ecartes": doublons}
    if tronque:
        resultat["tronque"] = True
    if reponse_tronquee:
        resultat["reponse_tronquee"] = True
    return resultat


def _lieu_par_id(store: Store, tiers_lieu_id: str):
    return next((l for l in store.list_tiers_lieux() if l.id == tiers_lieu_id), None)


def compiler_info_lieu_existant(store: Store, candidat: CandidatLieu, admin_user_id: str,
                                tiers_lieu_id: Optional[str] = None):
    """Un candidat dont le nom correspond à un lieu déjà recensé : n'écrit
    JAMAIS ses données (résumé, coordonnées...), qui appartiennent au lieu
    concerné — se contente d'ajouter une note citant ce que le document en
    dit, pour que le lieu/steward la reprenne s'il le juge pertinent.

    `tiers_lieu_id` cible explicitement un lieu — utilisé par le panneau
    admin quand il diffère du rapprochement fait à l'extraction (candidat.
    tiers_lieu_id, utilisé par défaut si non fourni) : un admin peut choisir
    un autre lieu que celui suggéré, y compris pour un candidat proposé comme
    nouveau lieu (tiers_lieu_id alors vide à l'origine).

    Renvoie le TiersLieu, ou None si ce lieu n'existe plus (supprimé
    entre-temps) ou si aucun lieu cible n'est connu."""
    lieu = _lieu_par_id(store, tiers_lieu_id or candidat.tiers_lieu_id)
    if lieu is None:
        return None
    contributeur = store.get_or_create_contributeur(admin_user_id, lieu.id, "steward")
    citation = f" Citation : « {candidat.citation} »." if candidat.citation else ""
    store.save_free_text_note(
        lieu.id, contributeur.id, "extraction_connaissance",
        f"Information complémentaire trouvée dans « {candidat.source_label} » : {candidat.description}{citation}",
    )
    store.traiter_candidat_lieu(candidat.id, "accepte", lieu.id, admin_user_id)
    return lieu


def creer_lieu_depuis_candidat(store: Store, candidat: CandidatLieu, admin_user_id: str):
    """Crée (ou rattache si le nom existe déjà — un lieu créé entre
    l'extraction et cette validation, par exemple) le lieu Space2
    correspondant à un candidat validé par un admin : synthèse minimale
    issue du document source, indexée pour la recherche sémantique, note de
    provenance pour que le lieu concerné puisse la compléter. Jamais publié
    au Portfolio automatiquement — à la discrétion de l'admin, comme pour
    tout autre lieu. Renvoie le TiersLieu créé ou rattaché."""
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


def accepter_candidat(store: Store, candidat: CandidatLieu, admin_user_id: str):
    """Point d'entrée unique pour valider un candidat, quel que soit son
    type : compile une note sur le lieu déjà recensé s'il y en a un
    (tiers_lieu_id déjà posé à la proposition), sinon crée un nouveau lieu."""
    if candidat.tiers_lieu_id:
        return compiler_info_lieu_existant(store, candidat, admin_user_id)
    return creer_lieu_depuis_candidat(store, candidat, admin_user_id)


def rejeter_candidat(store: Store, candidat_id: str, admin_user_id: str) -> None:
    store.traiter_candidat_lieu(candidat_id, "rejete", None, admin_user_id)
