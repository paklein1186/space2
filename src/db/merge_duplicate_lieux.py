"""Script ponctuel : fusionne des lieux en double créés par l'import CSV/
CommunECter (nom légèrement différent d'un lieu déjà recensé via le
questionnaire original — get_or_create_tiers_lieu ne fait qu'une
correspondance exacte insensible à la casse, donc "Le Monty" et "Le Monty
Tiers Lieu" ont été traités comme deux lieux distincts au lieu d'un seul).

Les paires ci-dessous ont été vérifiées manuellement une par une (adresse/
commune correspondante, pas seulement un nom proche — un faux positif,
"Domaine des Possibles" / "Domaine des ColibrYs", a été écarté car les
adresses ne correspondent pas du tout).

Pour chaque paire (garder, fusionner) : réattribue toutes les lignes du
lieu à fusionner vers le lieu à garder (contributeurs, réponses, notes,
sessions, historique, litiges), supprime la synthèse dérivée du doublon
(sera régénérée pour le lieu conservé avec l'ensemble des données),
supprime le lieu en double, puis relance l'enrichissement du lieu conservé.

Usage : python -m src.db.merge_duplicate_lieux
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.db.supabase_store import SupabaseStore

# (id à garder, nom à garder, id à fusionner/supprimer, nom à fusionner)
PAIRES = [
    ("eceaf046-83ae-4e5f-ae49-5973e788e31b", "Le Monty",
     "a74708ca-3e8b-460c-beb7-97b00a35b21c", "Le Monty Tiers Lieu"),
    ("68d5b0b3-5efd-49d8-b7bb-f0da99eacb29", "L'e-Square",
     "75ad5f8b-108c-4efd-8283-6b1eaa8b145d", "e-square"),
    ("5afa6742-6b42-4549-a71a-92451698685a", "Forêt de Luhan",
     "9d829ebb-d556-46f1-b2ee-447d754b1a60", "La forêt de Luhan"),
    ("c6ad2c58-3c5b-4028-b8ca-6e3cf25bd1af", "Pfarrhaus Aldringen – Presbytère d'Aldringen",
     "4073d722-299b-4a84-978b-f75ac9ac120d", "Pfarrhaus Aldringern (Presbytère d'Aldringen)"),
    ("0e4036e8-3be1-430f-af12-3c5e72bf4584", "La Gare",
     "474ffeab-0df7-4b69-86e2-a8a868671406", "La Gare - Houyet"),
]

TABLES_A_REPOINTER = ("reponses", "notes_libres", "sessions_entretien", "journal_modifications", "litiges")


def merge_one(client, keep_id: str, keep_nom: str, merge_id: str, merge_nom: str) -> None:
    print(f"Fusion : {merge_nom!r} ({merge_id[:8]}) -> {keep_nom!r} ({keep_id[:8]})")

    # Contributeurs : réattribués en place (même id conservé, donc reponses/
    # notes/journal qui référencent contributeur_id restent valides sans
    # modification pour cette partie-là) — sauf collision (le lieu à garder
    # a déjà un contributeur avec le même user_id+role), auquel cas on
    # fusionne les réponses vers ce contributeur déjà existant plutôt que de
    # créer un doublon de contributeur qui violerait la contrainte unique.
    contribs_merge = client.table("contributeurs").select("*").eq("tiers_lieu_id", merge_id).execute().data
    contribs_keep = client.table("contributeurs").select("*").eq("tiers_lieu_id", keep_id).execute().data
    keep_by_user_role = {(c["user_id"], c["role"]): c["id"] for c in contribs_keep}

    for c in contribs_merge:
        cle = (c["user_id"], c["role"])
        if cle in keep_by_user_role:
            cible_contributeur_id = keep_by_user_role[cle]
            print(f"  collision contributeur {c['user_id'][:8]}/{c['role']} -> fusion vers {cible_contributeur_id[:8]}")
            client.table("reponses").update(
                {"tiers_lieu_id": keep_id, "contributeur_id": cible_contributeur_id}
            ).eq("contributeur_id", c["id"]).execute()
            client.table("notes_libres").update(
                {"tiers_lieu_id": keep_id, "contributeur_id": cible_contributeur_id}
            ).eq("contributeur_id", c["id"]).execute()
            client.table("journal_modifications").update(
                {"tiers_lieu_id": keep_id, "contributeur_id": cible_contributeur_id}
            ).eq("contributeur_id", c["id"]).execute()
            client.table("sessions_entretien").delete().eq("contributeur_id", c["id"]).execute()
            client.table("contributeurs").delete().eq("id", c["id"]).execute()
        else:
            client.table("contributeurs").update({"tiers_lieu_id": keep_id}).eq("id", c["id"]).execute()

    # Reste des lignes encore rattachées à merge_id via leur propre colonne
    # tiers_lieu_id (redondante avec contributeur_id mais bien réelle dans
    # le schéma) — cas normal, sans collision de contributeur.
    for table in TABLES_A_REPOINTER:
        try:
            client.table(table).update({"tiers_lieu_id": keep_id}).eq("tiers_lieu_id", merge_id).execute()
        except Exception as exc:
            print(f"  (ignoré) {table}: {exc}")

    # La synthèse du doublon est obsolète par construction (calculée
    # uniquement à partir de ses propres réponses, désormais fusionnées) :
    # supprimée plutôt que réattribuée (conflit de clé primaire sur
    # tiers_lieu_id sinon), régénérée pour le lieu conservé juste après.
    client.table("lieu_derive").delete().eq("tiers_lieu_id", merge_id).execute()

    client.table("tiers_lieux").delete().eq("id", merge_id).execute()
    print(f"  OK — {merge_nom!r} supprimé, tout rattaché à {keep_nom!r}.")


def main():
    load_dotenv()
    store = get_admin_store()
    if not isinstance(store, SupabaseStore):
        print("Cette opération ne concerne que Supabase (get_admin_store() n'a pas retourné un SupabaseStore).")
        return
    client = store.client

    for keep_id, keep_nom, merge_id, merge_nom in PAIRES:
        merge_one(client, keep_id, keep_nom, merge_id, merge_nom)

    print("\nRé-enrichissement des lieux fusionnés (force=True, pour refléter l'ensemble des données)...")
    from src.agent.enrichissement import enrich_lieu
    for keep_id, keep_nom, _, _ in PAIRES:
        try:
            enrich_lieu(store, keep_id, force=True, nom_lieu=keep_nom)
            print(f"  OK — {keep_nom!r} réenrichi.")
        except Exception as exc:
            print(f"  ! échec enrichissement {keep_nom!r}: {exc}")


if __name__ == "__main__":
    main()
