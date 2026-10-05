"""Import des modules thématiques complémentaires du recensement national
BDTFL 2026 — tout sauf la fiche identité (voir import_bdtfl.py) : foncier,
activités détaillées, publics, RH, gouvernance, partenariats, labels/
agréments, réseaux, lieux en projet, informations générales.

Pas de mapping champ par champ vers le schéma Space2 : chaque fichier a des
dizaines à plusieurs centaines de colonnes, issues d'un export "une colonne
par case à cocher individuelle" (ex. le module activités : 313 colonnes).
Forcer un mapping 1:1 vers les champs structurés de Space2 serait un chantier
disproportionné pour des taxonomies qui ne correspondent de toute façon pas
aux options déjà définies côté Space2 (OPTIONS_SOUTIEN_ACCOMPAGNEMENT etc.).

Constat sur ce format d'export : chaque groupe de cases à cocher a UNE
colonne "en-tête" dont la valeur est déjà le texte lisible de la ou des
sélections (jointes par ";" pour un choix multiple — ex. activites_toutes =
"Bureau / Coworking;Bar / café"), suivie des colonnes individuelles par case
(valeurs 0/1 uniquement, redondantes avec l'en-tête). Donc : toute colonne
dont les valeurs ne sont JAMAIS que "0"/"1" sur l'ensemble du fichier est une
case individuelle -> ignorée ; le reste (en-têtes de groupe + champs texte/
numériques) est conservé tel quel, une note libre par thème et par lieu —
cohérent avec import_csv_directory.py/import_bdtfl.py : ce qui n'a pas
d'équivalent structuré va en note plutôt que d'être perdu ou forcé dans un
champ qui ne correspond pas.

Usage :
    python -m src.ingest.import_bdtfl_themes chemin/vers/bdftl-2026-03-foncier.csv [autres fichiers...]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.questionnaire.schema import Role

OWNER_ID_LOCAL = "import-bdtfl-2026"

# Colonnes d'identité déjà couvertes par import_bdtfl.py (fiche identité) —
# jamais répétées dans une note thématique.
COLONNES_IDENTITE = {"ID_UNIQUE", "NOM"}

# Préfixe de nom de fichier -> (section_id de la note, titre lisible).
THEMES = {
    "bdftl-2026-02-informations-generales": ("import_bdtfl_informations_generales", "Informations générales (BDTFL)"),
    "bdftl-2026-03-foncier": ("import_bdtfl_foncier", "Foncier (BDTFL)"),
    "bdftl-2026-04-activites": ("import_bdtfl_activites", "Activités détaillées (BDTFL)"),
    "bdftl-2026-05-publics": ("import_bdtfl_publics", "Publics (BDTFL)"),
    "bdftl-2026-06-rh": ("import_bdtfl_rh", "Ressources humaines (BDTFL)"),
    "bdftl-2026-07-gouvernance": ("import_bdtfl_gouvernance", "Gouvernance (BDTFL)"),
    "bdftl-2026-08-partenariats": ("import_bdtfl_partenariats", "Partenariats (BDTFL)"),
    "bdftl-2026-09-labels-agrements": ("import_bdtfl_labels_agrements", "Labels et agréments (BDTFL)"),
    "bdftl-2026-10-perspectives-futures": ("import_bdtfl_perspectives_futures", "Perspectives futures (BDTFL)"),
    "bdftl-2026-11-reseaux": ("import_bdtfl_reseaux", "Réseaux (BDTFL)"),
    "bdftl-2026-12-en-projet": ("import_bdtfl_en_projet", "Lieu en projet (BDTFL)"),
}


def _service_owner_id(store) -> str:
    """Comme import_bdtfl.py : résout (ou crée) le compte de service dédié
    sur Supabase ; en SQLite local, l'identifiant libre suffit directement."""
    from src.db.supabase_store import SupabaseStore

    if isinstance(store, SupabaseStore):
        from src.db.migrate_sqlite_to_supabase import get_or_create_service_user

        return get_or_create_service_user(store.client, OWNER_ID_LOCAL)
    return OWNER_ID_LOCAL


def colonnes_significatives(rows: list, header: list) -> list:
    """Colonnes à conserver : celles dont les valeurs ne sont jamais QUE
    "0"/"1" sur l'ensemble du fichier (une vraie case à cocher individuelle
    ne contient jamais rien d'autre) — voir le constat en tête de module."""
    valeurs_par_colonne: dict = {c: set() for c in header if c}
    for row in rows:
        for c in valeurs_par_colonne:
            v = (row.get(c) or "").strip()
            if v:
                valeurs_par_colonne[c].add(v)
    return [c for c in valeurs_par_colonne
            if c not in COLONNES_IDENTITE and not valeurs_par_colonne[c] <= {"0", "1"}]


def note_theme(row: dict, colonnes: list) -> str:
    lignes = [f"{c} : {(row.get(c) or '').strip()}" for c in colonnes if (row.get(c) or "").strip()]
    return "\n".join(lignes)


def theme_pour_fichier(chemin: Path):
    stem = chemin.stem
    cle = next((k for k in THEMES if stem.startswith(k)), None)
    return THEMES.get(cle)


def import_fichier(store, owner_user_id: str, chemin: Path) -> int:
    theme = theme_pour_fichier(chemin)
    if theme is None:
        print(f"[ignoré] fichier non reconnu : {chemin.name}")
        return 0
    section_id, titre = theme

    with chemin.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        header = reader.fieldnames or []
        rows = list(reader)

    # Idempotent : un lieu qui a déjà une note pour ce thème (ex. reprise
    # après une coupure réseau en cours de fichier — vécu, httpx.ReadTimeout
    # après ~600/998 lignes) n'est jamais réécrit, pour ne jamais dupliquer
    # une note déjà posée (save_free_text_note n'est pas un upsert).
    deja_notes = {n["tiers_lieu_id"] for n in store.get_notes_by_section_id(section_id)}

    colonnes = colonnes_significatives(rows, header)
    traites = ignores = 0
    for i, row in enumerate(rows, start=1):
        nom = (row.get("NOM") or "").strip()
        if not nom:
            continue
        note = note_theme(row, colonnes)
        if not note:
            continue
        tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, nom)
        if tiers_lieu.id in deja_notes:
            ignores += 1
            continue
        contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, Role.AUTRE.value)
        store.save_free_text_note(tiers_lieu.id, contributeur.id, section_id, f"{titre} :\n{note}")
        deja_notes.add(tiers_lieu.id)
        traites += 1
        if traites % 200 == 0:
            print(f"... {chemin.name} : {traites}/{len(rows)} lieux traités")

    print(f"{chemin.name} ({titre}) : {traites} note(s) ajoutée(s), {ignores} déjà présente(s) (reprise).")
    return traites


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest.import_bdtfl_themes chemin/vers/fichier.csv [autres fichiers...]")
        return
    store = get_admin_store()
    owner_user_id = _service_owner_id(store)

    total = 0
    for arg in sys.argv[1:]:
        total += import_fichier(store, owner_user_id, Path(arg))
    print(f"\nTotal : {total} note(s) thématique(s) ajoutée(s) sur {len(sys.argv) - 1} fichier(s).")


if __name__ == "__main__":
    main()
