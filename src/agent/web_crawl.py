"""Recherche web complémentaire : scanne le site externe déclaré d'un lieu
(lieu_derive.lien_externe, alimenté notamment par l'import CommunECter — voir
import_communecter.py) pour en extraire ce que les réponses au questionnaire
ne couvrent pas encore (activités détaillées, statut juridique mentionné,
actualités...), et le capture en note libre pour ce lieu — même mécanisme
que les imports CSV/CommunECter, alimente le prochain enrichissement IA sans
nouveau système de stockage.

Toujours déclenché manuellement depuis l'admin (jamais en tâche de fond
automatique) : un site web réel est plus lent et plus gros qu'un texte déjà
en base, et sa structure est imprévisible — mieux vaut que quelqu'un
supervise plutôt qu'un cron qui échoue silencieusement sur des sites variés.

Portée actuelle : uniquement les sites de lieux individuels (lien_externe),
qui s'intègrent directement dans le mécanisme existant (une note libre est
toujours rattachée à UN lieu). Une recherche transverse (site Trois-Tiers,
capitalisation de sujets récurrents comme les statuts juridiques rencontrés)
n'a pas d'équivalent : rien à quoi la rattacher n'a de sens, une nouvelle
table serait nécessaire (voir migration_003_connaissances.sql) — pas
construite ici tant que cette migration n'a pas été exécutée.
"""

from __future__ import annotations

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


def fetch_page_text(url: str) -> str:
    """Récupère le texte visible d'une page (hors script/style/nav/footer),
    nettoyé des espaces superflus. Lève une exception explicite en cas
    d'échec réseau/HTTP plutôt que de renvoyer un texte vide silencieux."""
    response = requests.get(url, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    texte = soup.get_text(separator=" ")
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte[:MAX_TEXTE_BRUT]


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
