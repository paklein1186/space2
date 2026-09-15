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

import requests
from bs4 import BeautifulSoup

from ..db.store import Store
from .usage import log_usage

NOTE_SECTION_CRAWL = "crawl_site_lieu"
TIMEOUT_S = 15
MAX_TEXTE_BRUT = 8000  # caractères — borne le coût du prompt d'extraction
USER_AGENT = "Mozilla/5.0 (compatible; lieux-hybrides-territoires/1.0; +https://troistiers.space)"

PROMPT_EXTRACTION = """Voici le texte brut extrait de la page d'accueil du site web d'un tiers-lieu
nommé « {nom_lieu} » (URL : {url}).

TEXTE DE LA PAGE :
{texte}

Résume en quelques phrases factuelles ce que cette page apprend sur ce lieu et qui pourrait
compléter un questionnaire (activités concrètes, statut juridique ou forme d'organisation
mentionnés, horaires, contact, actualités, partenaires cités...). Ignore le texte de navigation,
les mentions de cookies, le footer générique. Si la page n'apporte rien de substantiel au-delà
d'une vitrine sans contenu informatif, réponds exactement "RIEN_D_UTILE" sans rien ajouter
d'autre. Réponds en français, en texte simple (pas de markdown), 3-6 phrases maximum."""


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


def extraire_et_enregistrer(store: Store, tiers_lieu_id: str, contributeur_id: str,
                             nom_lieu: str, url: str, client=None) -> str:
    """Récupère la page, en extrait ce qui est substantiel via un appel LLM
    léger (Haiku), et l'enregistre en note libre. Renvoie un statut lisible
    ("enregistre" / "rien_d_utile" / "erreur: ...") plutôt que de lever pour
    une page individuelle en échec — un site indisponible ne doit jamais
    interrompre le scan des autres lieux (voir l'appelant, qui boucle sur
    tous les lieux)."""
    from anthropic import Anthropic

    try:
        texte_brut = fetch_page_text(url)
    except Exception as exc:
        return f"erreur: {type(exc).__name__}: {exc}"
    if not texte_brut:
        return "rien_d_utile"

    client = client or Anthropic(timeout=30.0)
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": PROMPT_EXTRACTION.format(
            nom_lieu=nom_lieu, url=url, texte=texte_brut,
        )}],
    )
    log_usage(store, "crawl_extraction", "claude-haiku-4-5", response.usage, tiers_lieu_id)
    resume = "".join(b.text for b in response.content if b.type == "text").strip()
    if not resume or "RIEN_D_UTILE" in resume:
        return "rien_d_utile"

    store.save_free_text_note(
        tiers_lieu_id, contributeur_id, NOTE_SECTION_CRAWL,
        f"Extrait du site web du lieu ({url}) :\n\n{resume}",
    )
    return "enregistre"
