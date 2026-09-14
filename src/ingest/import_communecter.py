"""Enrichit des lieux déjà recensés avec les données de l'annuaire public
CommunECter (logo, site, tags thématiques) — source complémentaire au même
réseau que l'export CSV déjà importé (mêmes organisations), jamais une
nouvelle source primaire : un lieu sans correspondance par nom déjà recensée
est ignoré plutôt que créé, pour ne jamais dupliquer/fusionner à l'aveugle.

Les tags sont conservés en note libre (signal utile pour la classification
par catégories lors du prochain enrichissement LLM, généralement plus
précis que la seule description : ex. "Tiers-lieu nourricier / Ferme
productive / Maraîchage (production alimentaire)" pointe directement vers
Alimentaire). Logo et site sont appliqués à lieu_derive.photo_url/
lien_externe une fois la synthèse garantie d'exister (update_lieu_derive_liens
exige une ligne lieu_derive existante).

Termine en ré-enrichissant tous les lieux recensés (idempotent : ne rappelle
le LLM que si le contenu source a changé, ce qui est le cas des lieux qui
viennent de recevoir de nouveaux tags) — c'est ce qui (re)calcule les
catégories de chaque lieu à partir de l'ensemble de ses réponses.

Usage :
    python -m src.ingest.import_communecter [url_api]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.questionnaire.schema import Role

DEFAULT_URL = "https://www.communecter.org/api/organization/get/key/tierslieuxbelgique"
OWNER_ID_LOCAL = "import-communecter"
NOTE_SECTION_TAGS = "import_communecter_tags"


def _service_owner_id(store) -> str:
    """Même principe que les autres imports en masse : sur Supabase, résout
    (ou crée) un compte de service dédié ; en SQLite local, l'identifiant
    libre suffit directement."""
    from src.db.supabase_store import SupabaseStore

    if isinstance(store, SupabaseStore):
        from src.db.migrate_sqlite_to_supabase import get_or_create_service_user

        return get_or_create_service_user(store.client, OWNER_ID_LOCAL)
    return OWNER_ID_LOCAL


def _note_tags(entity: dict) -> str:
    tags = entity.get("tags") or []
    if not tags:
        return ""
    return "Tags CommunECter (activités/thématiques déclarées par le lieu) :\n" + "\n".join(
        f"- {t}" for t in tags
    )


def fetch_entities(url: str) -> list:
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    entities = data.get("entities", {})
    return list(entities.values()) if isinstance(entities, dict) else list(entities)


def merge_entity(store, owner_user_id: str, entity: dict, lieux_existants: dict) -> tuple | None:
    """lieux_existants : dict {nom en minuscules -> TiersLieu}, préchargé une
    seule fois par l'appelant (évite un list_tiers_lieux() par entité)."""
    nom = (entity.get("name") or "").strip()
    if not nom:
        return None
    lieu = lieux_existants.get(nom.lower())
    if lieu is None:
        return None  # pas de lieu correspondant déjà recensé : on n'en crée pas ici

    contributeur = store.get_or_create_contributeur(owner_user_id, lieu.id, Role.AUTRE.value)

    note_tags = _note_tags(entity)
    if note_tags:
        deja_present = any(
            n.get("section_id") == NOTE_SECTION_TAGS for n in store.get_free_text_notes(lieu.id)
        )
        if not deja_present:
            store.save_free_text_note(lieu.id, contributeur.id, NOTE_SECTION_TAGS, note_tags)

    site = (entity.get("url") or {}).get("website")
    image = entity.get("image")
    return (lieu.id, site, image) if (site or image) else None


def main():
    load_dotenv()
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    store = get_admin_store()
    owner_user_id = _service_owner_id(store)

    entities = fetch_entities(url)
    lieux_existants = {l.nom.strip().lower(): l for l in store.list_tiers_lieux()}

    liens_a_appliquer = {}
    traites = 0
    for entity in entities:
        resultat = merge_entity(store, owner_user_id, entity, lieux_existants)
        traites += 1 if (entity.get("name") or "").strip().lower() in lieux_existants else 0
        if resultat:
            lieu_id, site, image = resultat
            liens_a_appliquer[lieu_id] = (site, image)

    print(f"{traites} lieu(x) correspondant(s) parmi {len(entities)} entités CommunECter.")

    from src.agent.enrichissement import PROMPT_VERSION, enrich_lieu

    tous_les_lieux = store.list_tiers_lieux()
    print(f"Ré-enrichissement de {len(tous_les_lieux)} lieu(x) (idempotent — recalcule "
          f"seulement ce qui a changé, dont les catégories)...")
    echecs = []
    for lieu in tous_les_lieux:
        derive_actuelle = store.get_lieu_derive(lieu.id)
        # source_hash seul ne détecte pas un changement de PROMPT_VERSION (un
        # lieu enrichi avant l'ajout des catégories resterait "à jour" sans
        # jamais les recevoir tant que ses réponses source ne bougent pas) :
        # on force explicitement le recalcul pour tout lieu encore sur une
        # version de prompt antérieure ou sans catégories du tout.
        force = derive_actuelle is None or derive_actuelle.prompt_version != PROMPT_VERSION or not derive_actuelle.donnees.get("categories")
        try:
            enrich_lieu(store, lieu.id, force=force, nom_lieu=lieu.nom)
        except Exception as exc:
            echecs.append((lieu.nom, str(exc)))
    if echecs:
        print(f"  {len(echecs)} échec(s) d'enrichissement :")
        for nom, err in echecs:
            print(f"    - {nom}: {err}")

    appliques = 0
    for lieu_id, (site, image) in liens_a_appliquer.items():
        derive = store.get_lieu_derive(lieu_id)
        if derive is None:
            continue
        store.update_lieu_derive_liens(
            lieu_id,
            lien_externe=site or derive.lien_externe,
            photo_url=image or derive.photo_url,
        )
        appliques += 1
    print(f"Logo/site appliqué(s) à {appliques} lieu(x).")


if __name__ == "__main__":
    main()
