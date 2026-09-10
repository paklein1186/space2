"""Import direct d'un export CSV de répertoire de tiers-lieux (colonnes :
adresse, géocoordonnées, réseaux sociaux, descriptions) — aucun appel LLM :
les champs structurés sont mappés directement au schéma, et tout ce qui n'a
pas d'équivalent structuré (description longue, coordonnées, accessibilité)
est conservé tel quel en note libre plutôt que perdu ou forcé dans un champ
qui ne correspond pas.

Dédoublonnage global par nom (get_or_create_tiers_lieu, déjà insensible à la
casse) : un lieu déjà recensé est enrichi par un nouveau contributeur
"autre" (perspective distincte, jamais un écrasement — les champs déjà
répondus par un vrai contributeur ne sont jamais remplacés), un lieu absent
est créé.

Usage :
    python -m src.ingest.import_csv_directory chemin/vers/export.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.questionnaire.schema import Role

OWNER_ID_LOCAL = "import-csv-tierslieux"
PAYS_PAR_CODE = {"BE": "Belgique", "FR": "France"}

_CONTACT_LABELS = [
    "Site internet", "E-mail", "Téléphone", "Facebook", "Instagram", "LinkedIn",
    "Messagerie instantanée", "Autre moyen de contact",
]


def _service_owner_id(store) -> str:
    """Sur Supabase, résout (ou crée) le compte de service dédié à cet
    import, comme pour les autres imports en masse (import_questionnaire.py
    via migrate_sqlite_to_supabase.py) ; en SQLite local, l'identifiant libre
    suffit directement (pas de contrainte de clé étrangère vers auth.users)."""
    from src.db.supabase_store import SupabaseStore

    if isinstance(store, SupabaseStore):
        from src.db.migrate_sqlite_to_supabase import get_or_create_service_user

        return get_or_create_service_user(store.client, OWNER_ID_LOCAL)
    return OWNER_ID_LOCAL


def _adresse(row: dict) -> str:
    parts = [row.get("address.streetAddress", ""), row.get("address.postalCode", ""),
             row.get("address.addressLocality", "")]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _note_complementaire(row: dict) -> str:
    lignes = []
    description_longue = (row.get("Description longue") or "").strip()
    if description_longue:
        lignes.append("Description longue :\n" + description_longue)

    contacts = [f"{label} : {(row.get(label) or '').strip()}"
                for label in _CONTACT_LABELS if (row.get(label) or "").strip()]
    if contacts:
        lignes.append("Coordonnées :\n" + "\n".join(contacts))

    transport = (row.get("Accessibilité en transports en commun") or "").strip()
    if transport:
        lignes.append("Accessibilité en transports en commun :\n" + transport)

    return "\n\n".join(lignes)


def import_row(store, owner_user_id: str, row: dict) -> str:
    nom = row["Nom du tiers-lieu"].strip()
    tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, nom)

    pays = PAYS_PAR_CODE.get((row.get("address.addressCountry") or "").strip().upper())
    locality = (row.get("address.addressLocality") or "").strip()
    lat_brut = (row.get("geo.latitude") or "").strip()
    lon_brut = (row.get("geo.longitude") or "").strip()

    maj = {}
    if pays and not tiers_lieu.pays:
        maj["pays"] = pays
    if locality and not tiers_lieu.region:
        maj["region"] = locality
    if lat_brut and not tiers_lieu.latitude:
        maj["latitude"] = float(lat_brut)
    if lon_brut and not tiers_lieu.longitude:
        maj["longitude"] = float(lon_brut)
    if maj:
        store.update_tiers_lieu(tiers_lieu.id, **maj)

    contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, Role.AUTRE.value)
    deja_repondu = store.get_answers(tiers_lieu.id, contributeur.id)

    def _save_si_absent(champ_id: str, valeur: str) -> None:
        valeur = (valeur or "").strip()
        if valeur and deja_repondu.get(champ_id) is None:
            store.save_answer(tiers_lieu.id, contributeur.id, champ_id, valeur)

    _save_si_absent("nom_lieu", nom)
    if pays:
        _save_si_absent("pays", pays)
    _save_si_absent("adresse", _adresse(row))
    # "Raison d'être ou tagline" (une phrase, ~100 caractères) correspond au
    # format attendu par description_courte ; "Description courte du projet"
    # (plus développée, sur l'origine/le sens du projet) correspond mieux à
    # ce que demande raison_etre — l'inversion apparente des noms de colonnes
    # source vs. champs cibles est volontaire, basée sur le contenu réel.
    _save_si_absent("description_courte", row.get("Raison d'être ou tagline", ""))
    _save_si_absent("raison_etre", row.get("Description courte du projet", ""))

    note = _note_complementaire(row)
    if note:
        store.save_free_text_note(tiers_lieu.id, contributeur.id, "import_csv", note)

    return tiers_lieu.id


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest.import_csv_directory chemin/vers/export.csv")
        return
    chemin = Path(sys.argv[1])
    store = get_admin_store()
    owner_user_id = _service_owner_id(store)

    with chemin.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    traites = 0
    for row in rows:
        if not (row.get("Nom du tiers-lieu") or "").strip():
            continue
        import_row(store, owner_user_id, row)
        traites += 1

    print(f"{traites} lieu(x) traité(s) depuis {chemin.name}.")


if __name__ == "__main__":
    main()
