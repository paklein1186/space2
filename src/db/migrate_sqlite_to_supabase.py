"""Migration unique : copie les données de la base SQLite locale vers Supabase.

Nécessite SUPABASE_URL + SUPABASE_SERVICE_KEY (clé service_role, qui bypasse
RLS — c'est un script d'administration, jamais l'app interactive).

`owner_user_id` / `contributeur.user_id` référencent `auth.users` côté
Supabase : les lieux importés (ex. via import_questionnaire.py, dont
owner_user_id est une chaîne libre comme "import-drive") sont donc rattachés
à un compte de service créé/retrouvé via l'API Admin Auth.

Usage : python -m src.db.migrate_sqlite_to_supabase
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
from supabase import create_client

from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive

SERVICE_ACCOUNTS_EMAIL_DOMAIN = "system.local"


def get_or_create_service_user(admin_client, local_owner_id: str) -> str:
    """Mappe un owner_user_id libre (SQLite) vers un vrai utilisateur Supabase
    Auth, créé une seule fois par nom d'origine (idempotent par email)."""
    email = f"{local_owner_id}@{SERVICE_ACCOUNTS_EMAIL_DOMAIN}"
    existing = admin_client.auth.admin.list_users()
    for user in existing:
        if user.email == email:
            return user.id
    created = admin_client.auth.admin.create_user({
        "email": email, "email_confirm": True,
    })
    return created.user.id


def main():
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not service_key:
        print("SUPABASE_URL et SUPABASE_SERVICE_KEY sont requis pour cette migration.")
        return

    sqlite_store = SqliteStore()
    admin_client = create_client(url, service_key)

    lieux = sqlite_store.list_tiers_lieux()
    print(f"{len(lieux)} lieu(x) à migrer.")

    owner_map: dict = {}

    for lieu in lieux:
        if lieu.owner_user_id not in owner_map:
            owner_map[lieu.owner_user_id] = get_or_create_service_user(admin_client, lieu.owner_user_id)
        real_owner_id = owner_map[lieu.owner_user_id]

        existing = admin_client.table("tiers_lieux").select("id").eq("id", lieu.id).execute()
        if not existing.data:
            admin_client.table("tiers_lieux").insert({
                "id": lieu.id,
                "owner_user_id": real_owner_id,
                "nom": lieu.nom,
                "pays": lieu.pays,
                "region": lieu.region,
                "latitude": lieu.latitude,
                "longitude": lieu.longitude,
                "statut_progression": lieu.statut_progression,
            }).execute()

        par_contributeur = sqlite_store.get_all_answers_by_contributeur(lieu.id)
        contributeur_rows = sqlite_store.conn.execute(
            "select id, user_id, role from contributeurs where tiers_lieu_id = ?", (lieu.id,)
        ).fetchall()
        contributeur_id_map: dict = {}
        for row in contributeur_rows:
            local_user_id = row["user_id"]
            if local_user_id not in owner_map:
                owner_map[local_user_id] = get_or_create_service_user(admin_client, local_user_id)
            real_user_id = owner_map[local_user_id]

            existing_c = admin_client.table("contributeurs").select("id").eq("id", row["id"]).execute()
            if not existing_c.data:
                admin_client.table("contributeurs").insert({
                    "id": row["id"], "user_id": real_user_id,
                    "tiers_lieu_id": lieu.id, "role": row["role"],
                }).execute()
            contributeur_id_map[row["id"]] = row["id"]

        reponses_rows = sqlite_store.conn.execute(
            "select contributeur_id, champ_id, valeur, confidentiel from reponses where tiers_lieu_id = ?",
            (lieu.id,),
        ).fetchall()
        for r in reponses_rows:
            import json as _json
            admin_client.table("reponses").upsert({
                "tiers_lieu_id": lieu.id,
                "contributeur_id": r["contributeur_id"],
                "champ_id": r["champ_id"],
                "valeur": _json.loads(r["valeur"]) if r["valeur"] is not None else None,
                "confidentiel": bool(r["confidentiel"]),
            }, on_conflict="tiers_lieu_id,contributeur_id,champ_id").execute()

        notes = sqlite_store.get_free_text_notes(lieu.id)
        for n in notes:
            existing_n = admin_client.table("notes_libres").select("id").eq("id", n["id"]).execute()
            if not existing_n.data:
                admin_client.table("notes_libres").insert({
                    "id": n["id"], "tiers_lieu_id": n["tiers_lieu_id"],
                    "contributeur_id": n["contributeur_id"], "section_id": n["section_id"],
                    "texte": n["texte"],
                }).execute()

        derive = sqlite_store.get_lieu_derive(lieu.id)
        if derive:
            admin_client.table("lieu_derive").upsert({
                "tiers_lieu_id": lieu.id,
                "donnees": derive.donnees,
                "profil_semantique_texte": derive.profil_semantique_texte,
                "prompt_version": derive.prompt_version,
                "model": derive.model,
                "source_hash": derive.source_hash,
                "valide_manuellement": derive.valide_manuellement,
                "corrections_manuelles": derive.corrections_manuelles,
            }, on_conflict="tiers_lieu_id").execute()

        print(f"  {lieu.nom}: {len(reponses_rows)} réponses, {len(notes)} notes, "
              f"{'donnée dérivée' if derive else 'pas de donnée dérivée'}")

    print("\nMigration terminée.")


if __name__ == "__main__":
    main()
