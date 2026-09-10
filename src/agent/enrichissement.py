"""Pipeline d'enrichissement : 1 appel LLM (Haiku 4.5) par lieu, jamais par
réponse individuelle. Lit toutes les réponses de tous les contributeurs
(+ notes libres) d'un lieu et produit :
  (a) un JSON structuré (résumé, activités, publics, territoire, gouvernance,
      ressources, besoins, modèle économique, partenaires, compétences,
      projets, enjeux, mots-clés)
  (b) un texte de "profil sémantique" (2-4 paragraphes), destiné à être
      l'unique embedding vectorisé de ce lieu (voir rag_tools.py / build_index.py)

Ne touche jamais à `reponses` (donnée brute) : tout est écrit dans la table
séparée `lieu_derive`, avec la provenance (version de prompt, modèle, hash des
réponses sources) pour la traçabilité et pour savoir quand ré-enrichir.
"""

from __future__ import annotations

import hashlib
import json

from anthropic import Anthropic

from ..annuaire import field_label
from ..db.store import LieuDerive, Store
from ..questionnaire.schema import CATEGORIES_POSSIBLES
from .embeddings import VoyageEmbedder
from .usage import log_usage
from .vectorstore import ChromaStore

MODEL = "claude-haiku-4-5"
PROMPT_VERSION = "enrichissement-v3"

CHAMPS_DERIVES = [
    "resume", "activites", "publics", "territoire", "gouvernance", "ressources",
    "besoins", "modele_economique", "partenaires", "competences", "projets",
    "enjeux", "mots_cles", "categories",
]
# Sections soumises à la longueur homogène (resume/mots_cles/categories en sont
# exclus : nature différente, pas comparable section à section dans l'Annuaire).
CHAMPS_LONGUEUR_CIBLE = [c for c in CHAMPS_DERIVES if c not in ("resume", "mots_cles", "categories")]
LONGUEUR_CIBLE_MIN = 150
LONGUEUR_CIBLE_MAX = 220

PROMPT_TEMPLATE = """Voici l'ensemble des réponses collectées pour un tiers-lieu, données par un ou
plusieurs contributeurs (fondateur, équipe, partenaire...), ainsi que des notes libres. Chaque
réponse structurée est précédée de son identifiant technique entre crochets, ex. [milieu] :

RÉPONSES STRUCTURÉES :
{reponses_texte}

NOTES LIBRES (identifiées note_0, note_1...) :
{notes_texte}

À partir de ces informations, produis un JSON avec exactement ces clés :
- resume : 1-2 phrases de synthèse du lieu (pas de contrainte de longueur particulière)
- activites : synthèse des activités et services proposés
- publics : synthèse des publics accueillis
- territoire : synthèse de l'ancrage territorial (localisation, milieu, mobilité)
- gouvernance : synthèse du mode de gouvernance et de la participation des usagers
- ressources : synthèse des ressources humaines et matérielles
- besoins : synthèse des besoins et difficultés exprimés
- modele_economique : synthèse du modèle économique et des sources de financement
- partenaires : synthèse des partenariats territoriaux
- competences : compétences ou savoir-faire distinctifs identifiés
- projets : projets en cours ou à venir mentionnés
- enjeux : enjeux ou défis principaux identifiés
- mots_cles : liste de 5-10 mots-clés pertinents pour la recherche
- categories : liste (0 à {nb_categories} éléments) parmi EXACTEMENT ces valeurs :
  {categories_possibles} — uniquement celles qui correspondent clairement aux activités du
  lieu (un lieu peut en avoir plusieurs, ou aucune si rien ne correspond). N'utilise aucune
  autre valeur que celles listées.

Pour LES 11 SECTIONS ci-dessus SAUF resume, mots_cles et categories : vise impérativement une longueur
homogène de {longueur_min} à {longueur_max} caractères chacune (ni plus court, ni plus long) —
ces synthèses seront affichées côte à côte dans des cartes de taille identique, l'homogénéité
compte plus que l'exhaustivité. Si une section manque d'information, dis-le en une phrase courte
plutôt que de la laisser vide ou de la étirer artificiellement.

- profil_semantique_texte : un texte de 2 à 4 paragraphes en français qui décrit ce lieu de
  façon dense et naturelle (pas une liste), utile pour retrouver ce lieu par recherche
  sémantique à partir de questions comme "quels lieux travaillent sur..." ou "lieux avec
  une approche comparable à...". Pas de contrainte de longueur homogène pour ce champ.
- sources : un objet associant CHAQUE section ci-dessus (les 11 + resume) à la liste des
  identifiants (champ_id entre crochets, ou note_N) qui l'ont concrètement alimentée. Ex :
  {{"activites": ["activites_principales", "equipements"], "besoins": ["difficulte_financiere_actuelle", "note_2"]}}.
  N'invente pas d'identifiant qui n'apparaît pas ci-dessus.

N'invente rien qui ne soit pas présent dans les données ci-dessus. Réponds UNIQUEMENT avec
l'objet JSON, sans texte autour.
"""


def _format_reponses(par_contributeur: dict) -> str:
    lines = []
    for contributeur_id, reponses in par_contributeur.items():
        lines.append(f"[Contributeur {contributeur_id}]")
        for champ_id, valeur in reponses.items():
            lines.append(f"  [{champ_id}] {field_label(champ_id)}: {valeur}")
    return "\n".join(lines) if lines else "(aucune réponse structurée)"


def _format_notes(notes: list) -> str:
    if not notes:
        return "(aucune note libre)"
    return "\n".join(f"[note_{i}] {n['texte']}" for i, n in enumerate(notes))


def compute_source_hash(par_contributeur: dict, notes: list) -> str:
    payload = json.dumps({"reponses": par_contributeur, "notes": [n["texte"] for n in notes]},
                          sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _embed_profil(tiers_lieu_id: str, nom_lieu: str, profil_texte: str,
                   embedder: VoyageEmbedder | None, vectorstore: ChromaStore | None) -> None:
    if not profil_texte:
        return
    embedder = embedder or VoyageEmbedder()
    vectorstore = vectorstore or ChromaStore()
    embedding = embedder.embed_documents([profil_texte])[0]
    vectorstore.upsert(
        ids=[f"profil_lieu::{tiers_lieu_id}"],
        embeddings=[embedding],
        documents=[profil_texte],
        metadatas=[{"doc_type": "profil_lieu", "tiers_lieu_id": tiers_lieu_id, "source_file": nom_lieu}],
    )


def enrich_lieu(store: Store, tiers_lieu_id: str, force: bool = False, nom_lieu: str = "",
                 embedder: VoyageEmbedder | None = None,
                 vectorstore: ChromaStore | None = None) -> tuple[LieuDerive | None, bool]:
    """Renvoie (donnée dérivée, a_ete_recalculee). `a_ete_recalculee` est False
    quand l'enrichissement existant était déjà à jour (source_hash inchangé)."""
    par_contributeur = store.get_all_answers_by_contributeur(tiers_lieu_id)
    notes = store.get_free_text_notes(tiers_lieu_id)
    if not par_contributeur and not notes:
        return None, False

    source_hash = compute_source_hash(par_contributeur, notes)
    existing = store.get_lieu_derive(tiers_lieu_id)
    if existing and existing.source_hash == source_hash and not force:
        return existing, False  # rien de nouveau depuis le dernier enrichissement

    prompt = PROMPT_TEMPLATE.format(
        reponses_texte=_format_reponses(par_contributeur),
        notes_texte=_format_notes(notes),
        longueur_min=LONGUEUR_CIBLE_MIN,
        longueur_max=LONGUEUR_CIBLE_MAX,
        nb_categories=len(CATEGORIES_POSSIBLES),
        categories_possibles=", ".join(CATEGORIES_POSSIBLES),
    )
    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}],
    )
    log_usage(store, "enrichissement", MODEL, response.usage, tiers_lieu_id)

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)

    profil_texte = data.pop("profil_semantique_texte", "")
    sources = data.pop("sources", None)
    donnees = {k: data.get(k) for k in CHAMPS_DERIVES}
    # Filtre défensif : ne garder que des catégories réellement dans la liste
    # autorisée, au cas où le modèle en invente une malgré la consigne.
    donnees["categories"] = [c for c in (donnees.get("categories") or []) if c in CATEGORIES_POSSIBLES]

    lieu_derive = LieuDerive(
        tiers_lieu_id=tiers_lieu_id,
        donnees=donnees,
        sources=sources,
        profil_semantique_texte=profil_texte,
        prompt_version=PROMPT_VERSION,
        model=MODEL,
        source_hash=source_hash,
    )
    store.save_lieu_derive(lieu_derive)
    _embed_profil(tiers_lieu_id, nom_lieu, profil_texte, embedder, vectorstore)
    return lieu_derive, True
