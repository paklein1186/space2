"""Recherche web complémentaire, trois usages :

1. Le site externe déclaré d'UN lieu (lieu_derive.lien_externe, alimenté
   notamment par l'import CommunECter) : extrait ce que les réponses au
   questionnaire ne couvrent pas encore, capturé en note libre pour ce lieu
   — même mécanisme que les imports CSV/CommunECter.
2. Une connaissance générale, transverse, pas rattachée à un lieu (un
   article de la base de connaissances Trois-Tiers, une page trouvée par un
   admin sur un sujet donné) : versée directement dans l'index vectoriel
   (ChromaDB), cherchable tout de suite par la Bibliothèque — pas de
   nouvelle table SQL, le vecteur embeddé EST le stockage (même mécanisme
   que le bouton "🧠 Nourrir l'intelligence" de la Bibliothèque, voir
   `ajouter_connaissance`).
3. Une recherche web ponctuelle PENDANT l'entretien (`rechercher_web`,
   API Brave Search) quand un lieu est inconnu à la fois des réponses déjà
   données et de la base de connaissances interne (voir
   `rechercher_connaissances_existantes` dans collecte_tools.py) — pour ne
   jamais faire repartir un répondant de zéro sur une info trouvable en une
   recherche. Nécessite BRAVE_SEARCH_API_KEY (payant au-delà d'un crédit
   mensuel offert) ; dégrade silencieusement en liste vide si absent, cette
   capacité reste optionnelle.

1 et 2 restent toujours déclenchés manuellement depuis l'admin (jamais en
tâche de fond automatique) : un site web réel est plus lent et plus gros
qu'un texte déjà en base, et sa structure est imprévisible — mieux vaut que
quelqu'un supervise plutôt qu'un cron qui échoue silencieusement sur des
sites variés.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..db.store import Store
from ..ingest.loaders import SUPPORTED_TEXT_SUFFIXES, extract_text
from .usage import log_usage

NOTE_SECTION_CRAWL = "crawl_site_lieu"
TIMEOUT_S = 15
MAX_TEXTE_BRUT = 8000  # caractères — borne le coût du prompt d'extraction
USER_AGENT = "Mozilla/5.0 (compatible; lieux-hybrides-territoires/1.0; +https://troistiers.space)"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def rechercher_web(requete: str, max_resultats: int = 3) -> list:
    """Recherche web publique via l'API Brave Search — renvoie une liste de
    {titre, url, description}, ou une liste vide si BRAVE_SEARCH_API_KEY
    n'est pas configuré ou en cas d'erreur réseau. Jamais d'exception : cette
    capacité reste un bonus ponctuel pendant l'entretien (une piste à faire
    confirmer par le répondant, voir la règle dédiée dans collecte_agent.
    SYSTEM_PROMPT), jamais un prérequis pour continuer sans elle."""
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return []
    try:
        response = requests.get(
            BRAVE_SEARCH_URL,
            params={"q": requete, "count": max_resultats},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    resultats = (data.get("web") or {}).get("results") or []
    return [
        {"titre": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
        for r in resultats[:max_resultats]
    ]


PROMPT_EXTRACTION = """Voici du texte brut concernant un tiers-lieu nommé « {nom_lieu} »,
transmis via {source_label}.

TEXTE :
{texte}

Résume en quelques phrases factuelles ce que ce texte apprend sur ce lieu et qui pourrait
compléter un questionnaire (activités concrètes, statut juridique ou forme d'organisation
mentionnés, horaires, contact, actualités, partenaires cités...). Ignore le texte de navigation,
les mentions de cookies, le footer générique si présents. Si le texte n'apporte rien de
substantiel, réponds exactement "RIEN_D_UTILE" sans rien ajouter d'autre. Réponds en français,
en texte simple (pas de markdown), 3-6 phrases maximum."""

PROMPT_EXTRACTION_GENERAL = """Voici du texte brut transmis via {source_label}, à verser dans la
base de connaissances générale de la plateforme "Lieux hybrides et territoires" (pas rattaché à
un lieu précis).

TEXTE :
{texte}

Résume en quelques phrases factuelles ce que ce texte apporte comme savoir réutilisable pour
l'écosystème des tiers-lieux (méthode, retour d'expérience, ressource, dispositif, cadre
juridique ou de financement, contact ou réseau utile...). Ignore le texte de navigation, les
mentions de cookies, le footer générique si présents. Si le texte n'apporte rien de substantiel,
réponds exactement "RIEN_D_UTILE" sans rien ajouter d'autre. Réponds en français, en texte
simple (pas de markdown), 3-8 phrases maximum."""

# Articles publics de la base de connaissances Odoo de Trois-Tiers
# (troistiers.space/knowledge/article/<id>), capturés depuis le sommaire
# public (troistiers.space/knowledge/article/108, section "Section
# publique") le 2026-09-15 — pas d'API de découverte automatique trouvée
# (le sommaire se charge côté client via un appel dont les paramètres
# exacts n'ont pas pu être reconstitués ; chaque article, lui, est bien
# rendu côté serveur et directement récupérable). À rafraîchir à la main si
# de nouveaux articles sont ajoutés d'ici là.
ARTICLES_TROIS_TIERS_IDS = [
    108, 211, 212, 213, 215, 205, 223, 81, 58, 88, 89, 90, 91, 92, 217, 222, 219, 93, 97, 94, 95,
    96, 49, 206, 208, 103, 104, 105, 107, 106, 109, 110, 111, 112, 115, 210, 114, 140, 141, 143,
    142, 144, 145, 147, 149, 150, 151, 152, 153, 154, 113, 159, 160, 161, 146, 162, 163, 164, 165,
    116, 117, 46, 118, 119, 120, 121, 122, 123, 126, 127, 128, 129, 130, 131, 132, 133, 194, 134,
    135, 136, 137, 138, 196, 221, 192, 101, 125, 99, 156, 157, 158, 193, 124, 98, 167, 139, 168,
    169, 170, 171, 100, 102, 197, 191, 190, 220, 173, 179, 176, 175, 177, 180, 181, 182, 183, 184,
    185, 186, 187, 188, 195, 199, 209, 224, 225, 178,
]
TROIS_TIERS_ARTICLE_URL = "https://www.troistiers.space/knowledge/article/{id}"


_GOOGLE_DOCS_RE = re.compile(r"^https?://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)")


def _normaliser_url(url: str) -> str:
    """Un lien Google Docs tel que copié depuis la barre d'adresse (.../edit)
    ne renvoie qu'une coquille JS vide sans être connecté à Google — donnait
    à tort "rien d'exploitable" pour un document par ailleurs public. Son
    export texte brut (.../export?format=txt), lui, est accessible sans
    authentification dès que le document est partagé au moins en lecture —
    pas de vrai contenu récupéré si le document n'est PAS partagé (Google
    répond alors par une page de connexion, filtrée comme les autres pages
    sans substance)."""
    m = _GOOGLE_DOCS_RE.match(url)
    if m:
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    return url


def fetch_page_text(url: str) -> str:
    """Récupère le texte visible d'une page (hors script/style/nav/footer),
    nettoyé des espaces superflus. Lève une exception explicite en cas
    d'échec réseau/HTTP plutôt que de renvoyer un texte vide silencieux."""
    url = _normaliser_url(url)
    response = requests.get(url, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    texte = soup.get_text(separator=" ")
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte[:MAX_TEXTE_BRUT]


def fetch_page_text_complet(url: str) -> str:
    """Comme fetch_page_text, mais SANS tronquer à MAX_TEXTE_BRUT et en
    conservant une frontière de paragraphe par ligne (chaque ligne non vide
    devient un paragraphe séparé par une ligne blanche) — nécessaire à
    chunk_text pour découper correctement. À réserver à l'ingestion d'un
    document long (rapport, guide) : fetch_page_text seule, en résumant en
    quelques phrases un texte tronqué à 8000 caractères, avait réduit un
    rapport de 179 000 caractères documentant 23 accompagnements individuels
    à un unique paragraphe global — perdant l'essentiel du détail."""
    url = _normaliser_url(url)
    response = requests.get(url, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    texte = soup.get_text(separator="\n")
    lignes = [re.sub(r"[ \t]+", " ", l).strip() for l in texte.split("\n")]
    return "\n\n".join(l for l in lignes if l)


def extraire_texte_fichier(uploaded_file) -> str:
    """Texte brut d'un fichier déposé via st.file_uploader (txt/docx/pdf) —
    réutilise l'extraction déjà écrite pour l'ingestion admin (loaders.py),
    qui travaille sur un chemin disque, via un fichier temporaire (l'objet
    Streamlit n'est qu'un buffer en mémoire, sans chemin réel)."""
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        raise ValueError(f"Format non supporté : {suffix} (formats acceptés : "
                          f"{', '.join(sorted(SUPPORTED_TEXT_SUFFIXES))})")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp.flush()
        return extract_text(Path(tmp.name))


def extraire_essentiel(store: Store, tiers_lieu_id: str, nom_lieu: str, texte_brut: str,
                        source_label: str, client=None) -> str:
    """Étape commune à toutes les sources (site web, fichier déposé, texte
    collé) : extrait via un appel LLM léger (Haiku) ce qu'un texte brut
    apporte de substantiel sur un lieu. Renvoie le résumé, ou une chaîne vide
    si rien d'exploitable — ne sauvegarde rien elle-même, laissé à l'appelant
    (note libre pour le scan admin, tour de conversation pour l'entretien)."""
    from anthropic import Anthropic

    texte_brut = (texte_brut or "").strip()[:MAX_TEXTE_BRUT]
    if not texte_brut:
        return ""

    client = client or Anthropic(timeout=30.0)
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": PROMPT_EXTRACTION.format(
            nom_lieu=nom_lieu, source_label=source_label, texte=texte_brut,
        )}],
    )
    try:
        log_usage(store, "crawl_extraction", "claude-haiku-4-5", response.usage, tiers_lieu_id)
    except Exception:
        # La télémétrie de coût ne doit jamais faire échouer une extraction
        # par ailleurs réussie (vécu : une contrainte Postgres pas encore à
        # jour sur ce type d'appel a fait planter toute la fonctionnalité
        # côté admin ET entretien — voir migration_005).
        pass
    resume = "".join(b.text for b in response.content if b.type == "text").strip()
    if not resume or "RIEN_D_UTILE" in resume:
        return ""
    return resume


def extraire_essentiel_general(store: Store, texte_brut: str, source_label: str, client=None) -> str:
    """Variante de `extraire_essentiel` pour une connaissance générale, pas
    rattachée à un lieu — même mécanique (Haiku léger, "RIEN_D_UTILE" si rien
    de substantiel), prompt différent (pas de "tiers-lieu nommé X", un savoir
    réutilisable par l'écosystème plutôt qu'un fait sur un lieu précis)."""
    from anthropic import Anthropic

    texte_brut = (texte_brut or "").strip()[:MAX_TEXTE_BRUT]
    if not texte_brut:
        return ""

    client = client or Anthropic(timeout=30.0)
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": PROMPT_EXTRACTION_GENERAL.format(
            source_label=source_label, texte=texte_brut,
        )}],
    )
    try:
        log_usage(store, "crawl_extraction", "claude-haiku-4-5", response.usage, None)
    except Exception:
        pass
    resume = "".join(b.text for b in response.content if b.type == "text").strip()
    if not resume or "RIEN_D_UTILE" in resume:
        return ""
    return resume


def ajouter_connaissance(store: Store, texte_brut: str, source_label: str,
                          doc_type: str = "connaissance_bibliotheque", client=None) -> str:
    """Extrait l'essentiel de `texte_brut` puis le verse directement dans
    l'index vectoriel (embeddé, cherchable tout de suite par
    search_knowledge_base) — pas de lieu à sélectionner, pas de note libre.
    Renvoie un statut lisible ("ajoute" / "rien_d_utile" / "erreur: ..."),
    même convention que `extraire_et_enregistrer`, pour ne jamais interrompre
    un scan groupé sur un texte individuel en échec."""
    import uuid
    from datetime import datetime, timezone

    from .embeddings import VoyageEmbedder
    from .vectorstore import ChromaStore

    resume = extraire_essentiel_general(store, texte_brut, source_label, client=client)
    if not resume:
        return "rien_d_utile"
    try:
        embedder = VoyageEmbedder()
        embedding = embedder.embed_documents([resume])[0]
        ChromaStore().upsert(
            ids=[f"connaissance_{uuid.uuid4()}"],
            embeddings=[embedding],
            documents=[resume],
            metadatas=[{
                "doc_type": doc_type, "source_file": source_label,
                "date_ajout": datetime.now(timezone.utc).isoformat(),
            }],
        )
    except Exception as exc:
        return f"erreur: {type(exc).__name__}: {exc}"
    return "ajoute"


def ajouter_connaissance_longue(store: Store, texte_complet: str, source_label: str,
                                 doc_type: str = "connaissance_bibliotheque") -> dict:
    """Découpe `texte_complet` en chunks (même mécanisme que l'indexation
    des documents déposés dans data/raw/, voir ingest/chunking.py) et les
    embedde tels quels, sans résumé intermédiaire. Contrairement à
    `ajouter_connaissance` (pensée pour une page web courte, réduite à
    quelques phrases), celle-ci préserve le détail d'un document long —
    vécu : un rapport de 179 000 caractères documentant 23 accompagnements
    individuels distincts, réduit par l'autre chemin à un unique paragraphe
    global, avait perdu tout le détail nominatif par lieu. Renvoie
    {"chunks": n} ou {"erreur": ...}."""
    from datetime import datetime, timezone
    from hashlib import sha256

    from ..ingest.chunking import chunk_text
    from .embeddings import VoyageEmbedder
    from .vectorstore import ChromaStore

    texte_complet = (texte_complet or "").strip()
    if not texte_complet:
        return {"chunks": 0}

    chunks = chunk_text(texte_complet, metadata={
        "doc_type": doc_type, "source_file": source_label,
        "date_ajout": datetime.now(timezone.utc).isoformat(),
    })
    if not chunks:
        return {"chunks": 0}
    try:
        embedder = VoyageEmbedder()
        embeddings = embedder.embed_documents([c.text for c in chunks])
        # Id stable par source + position : ré-ingérer le même lien met à
        # jour ses chunks (upsert) plutôt que d'en créer des doublons.
        source_hash = sha256(source_label.encode("utf-8")).hexdigest()[:12]
        ids = [f"connaissance_longue_{source_hash}_{c.metadata['chunk_index']}" for c in chunks]
        ChromaStore().upsert(
            ids=ids, embeddings=embeddings,
            documents=[c.text for c in chunks], metadatas=[c.metadata for c in chunks],
        )
    except Exception as exc:
        return {"erreur": f"{type(exc).__name__}: {exc}"}
    return {"chunks": len(chunks)}


def dernier_ajout_connaissance(doc_type: str) -> str | None:
    """Date (ISO) du document le plus récent de ce doc_type dans l'index
    vectoriel, ou None si la base de connaissances est vide pour ce
    doc_type — pour afficher "dernier scan" côté admin sans avoir à tenir
    un état séparé (la date est déjà portée par chaque document)."""
    from .vectorstore import ChromaStore

    try:
        metadatas = ChromaStore().get_metadatas({"doc_type": doc_type})
    except Exception:
        return None
    dates = [m["date_ajout"] for m in metadatas if m.get("date_ajout")]
    return max(dates) if dates else None


def crawler_trois_tiers(store: Store, client=None, callback=None) -> dict:
    """Scanne tous les articles connus de la base de connaissances publique
    Trois-Tiers (ARTICLES_TROIS_TIERS_IDS) et verse ce qui est substantiel
    dans la base de connaissances générale. `callback(i, total, titre_ou_url)`
    optionnel, appelé avant chaque page (pour une barre de progression côté
    admin). Ne lève jamais pour une page individuelle en échec."""
    resultats = {"ajoutes": 0, "rien_d_utile": 0, "erreurs": []}
    total = len(ARTICLES_TROIS_TIERS_IDS)
    for i, article_id in enumerate(ARTICLES_TROIS_TIERS_IDS):
        url = TROIS_TIERS_ARTICLE_URL.format(id=article_id)
        if callback:
            callback(i, total, url)
        try:
            texte_brut = fetch_page_text(url)
        except Exception as exc:
            resultats["erreurs"].append(f"{url} : {type(exc).__name__}: {exc}")
            continue
        statut = ajouter_connaissance(store, texte_brut, f"la base de connaissances Trois-Tiers ({url})",
                                       doc_type="connaissance_trois_tiers", client=client)
        if statut == "ajoute":
            resultats["ajoutes"] += 1
        elif statut == "rien_d_utile":
            resultats["rien_d_utile"] += 1
        else:
            resultats["erreurs"].append(f"{url} : {statut}")
    return resultats


def extraire_et_enregistrer(store: Store, tiers_lieu_id: str, contributeur_id: str,
                             nom_lieu: str, url: str, client=None) -> str:
    """Récupère la page, en extrait ce qui est substantiel, et l'enregistre
    directement en note libre. Renvoie un statut lisible ("enregistre" /
    "rien_d_utile" / "erreur: ...") plutôt que de lever pour une page
    individuelle en échec — un site indisponible ne doit jamais interrompre
    le scan des autres lieux (voir l'appelant, qui boucle sur tous les
    lieux). Utilisé par le scan groupé admin ; l'entretien passe plutôt par
    `extraire_essentiel` pour injecter le résumé dans la conversation."""
    try:
        texte_brut = fetch_page_text(url)
    except Exception as exc:
        return f"erreur: {type(exc).__name__}: {exc}"

    resume = extraire_essentiel(store, tiers_lieu_id, nom_lieu, texte_brut, f"le site web ({url})", client=client)
    if not resume:
        return "rien_d_utile"

    store.save_free_text_note(
        tiers_lieu_id, contributeur_id, NOTE_SECTION_CRAWL,
        f"Extrait du site web du lieu ({url}) :\n\n{resume}",
    )
    return "enregistre"
