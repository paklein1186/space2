"""Import direct du fichier « fiche identité » du recensement national des
tiers-lieux 2026 (BDTFL, data.gouv.fr) — aucun appel LLM : les champs
structurés sont mappés directement au schéma, le reste (contacts, réseaux
sociaux, date d'ouverture, structure gestionnaire) conservé en note libre.
Même philosophie que import_csv_directory.py : dédoublonnage global par nom
(get_or_create_tiers_lieu, insensible à la casse), jamais d'écrasement d'une
réponse déjà saisie par un vrai contributeur.

Contrairement à import_csv_directory.py, ce fichier fournit déjà latitude et
longitude pour chaque lieu (décimales à virgule, format français) : aucun
géocodage nécessaire à l'import.

Ne couvre que le module « fiche identité » (fichier bdftl-2026-01) — les 11
autres modules thématiques du recensement (activités, RH, gouvernance,
partenariats...) ne sont pas importés par ce script.

Usage :
    python -m src.ingest.import_bdtfl chemin/vers/bdftl-2026-01-fiche-identite.csv
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.questionnaire.schema import Role

# Même pause de courtoisie que import_bdtfl_themes.py — un run de ce script
# a saturé la même base Supabase que le site en production pendant que
# quelqu'un l'utilisait ("ConnectionTerminated" sur l'Annuaire).
PAUSE_S = 0.2

OWNER_ID_LOCAL = "import-bdtfl-2026"
PAYS = "France"  # tout le fichier ne couvre que la France (+ DROM-COM)

_CONTACT_LABELS = [
    ("INTERNET", "Site internet"), ("EMAIL", "E-mail"), ("TELEPHONE", "Téléphone"),
    ("RS_FACEBOOK", "Facebook"), ("RS_X", "X (Twitter)"), ("RS_INSTAGRAM", "Instagram"),
    ("RS_LINKEDIN", "LinkedIn"), ("RS_MASTODON", "Mastodon"), ("RS_MOVILAB", "Fiche MoviLab"),
    ("LIEN_OSM_GOOGLE", "Lien OSM/Google Maps"),
]


def _service_owner_id(store) -> str:
    """Comme import_csv_directory.py : résout (ou crée) le compte de service
    dédié à cet import sur Supabase ; en SQLite local, l'identifiant libre
    suffit directement."""
    from src.db.supabase_store import SupabaseStore

    if isinstance(store, SupabaseStore):
        from src.db.migrate_sqlite_to_supabase import get_or_create_service_user

        return get_or_create_service_user(store.client, OWNER_ID_LOCAL)
    return OWNER_ID_LOCAL


def _coordonnee(valeur: str) -> float | None:
    """'49,438538' (virgule décimale française) -> 49.438538, ou None si vide
    ou illisible — un géocodage manquant ne doit jamais empêcher l'import du
    reste du lieu."""
    valeur = (valeur or "").strip().replace(",", ".")
    if not valeur:
        return None
    try:
        return float(valeur)
    except ValueError:
        return None


def _note_complementaire(row: dict) -> str:
    lignes = []
    structure = (row.get("TYPE_STRUCTURE_GEST") or "").strip()
    nom_structure = (row.get("NOM_STRC_GEST") or "").strip()
    if structure or nom_structure:
        lignes.append("Structure gestionnaire : " + " — ".join(p for p in (nom_structure, structure) if p))
    ouverture = (row.get("DATE_OUV") or "").strip()
    if ouverture:
        lignes.append("Date d'ouverture déclarée : " + ouverture)
    contacts = [f"{label} : {(row.get(cle) or '').strip()}"
                for cle, label in _CONTACT_LABELS if (row.get(cle) or "").strip()]
    if contacts:
        lignes.append("Coordonnées :\n" + "\n".join(contacts))
    return "\n\n".join(lignes)


def import_row(store, owner_user_id: str, row: dict) -> str:
    nom = row["NOM"].strip()
    tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, nom)

    region = (row.get("REGION_TL") or "").strip()
    commune = (row.get("VILLE") or "").strip()
    code_postal = (row.get("CODPOST") or "").strip()
    latitude = _coordonnee(row.get("LATITUDE"))
    longitude = _coordonnee(row.get("LONGITUDE"))

    maj = {}
    if not tiers_lieu.pays:
        maj["pays"] = PAYS
    if region and not tiers_lieu.region:
        maj["region"] = region
    if commune and not tiers_lieu.commune:
        maj["commune"] = commune
    if code_postal and not tiers_lieu.code_postal:
        maj["code_postal"] = code_postal
    if latitude is not None and longitude is not None and tiers_lieu.latitude is None:
        maj["latitude"] = latitude
        maj["longitude"] = longitude
    if maj:
        store.update_tiers_lieu(tiers_lieu.id, **maj)

    contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, Role.AUTRE.value)
    deja_repondu = store.get_answers(tiers_lieu.id, contributeur.id)

    def _save_si_absent(champ_id: str, valeur: str) -> None:
        valeur = (valeur or "").strip()
        if valeur and deja_repondu.get(champ_id) is None:
            store.save_answer(tiers_lieu.id, contributeur.id, champ_id, valeur)

    _save_si_absent("nom_lieu", nom)
    _save_si_absent("pays", PAYS)
    _save_si_absent("adresse", row.get("ADRESSE", ""))
    _save_si_absent("description_courte", row.get("DESCRI_COU", ""))

    note = _note_complementaire(row)
    if note:
        store.save_free_text_note(tiers_lieu.id, contributeur.id, "import_bdtfl", note)

    return tiers_lieu.id


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest.import_bdtfl chemin/vers/bdftl-2026-01-fiche-identite.csv")
        return
    chemin = Path(sys.argv[1])
    store = get_admin_store()
    owner_user_id = _service_owner_id(store)

    with chemin.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    traites = 0
    for i, row in enumerate(rows, start=1):
        if not (row.get("NOM") or "").strip():
            continue
        import_row(store, owner_user_id, row)
        traites += 1
        time.sleep(PAUSE_S)
        if traites % 100 == 0:
            print(f"... {traites}/{len(rows)} lieux traités")

    print(f"{traites} lieu(x) traité(s) depuis {chemin.name}.")


if __name__ == "__main__":
    main()
