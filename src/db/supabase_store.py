"""Implémentation Supabase (production) du Store. Voir schema.sql pour le DDL
à exécuter sur le projet Supabase avant d'utiliser cette classe."""

from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

from .store import CampagnePrioritaire, Contributeur, LieuDerive, Litige, SessionEntretien, Store, TiersLieu


def _to_dataclass(cls, row: dict):
    """Filtre les colonnes Supabase (ex. `cree_le`) absentes du dataclass
    avant construction — évite un TypeError sur tout champ ajouté côté SQL
    (audit, timestamps) qui n'a pas d'équivalent côté Python."""
    return cls(**{k: v for k, v in row.items() if k in cls.__dataclass_fields__})


class SupabaseStore(Store):
    def __init__(self, url: str, key: str, client: Optional[Client] = None):
        """Si `client` est fourni (ex. déjà authentifié via OTP dans app.py),
        il est réutilisé tel quel — indispensable pour que les policies RLS
        s'appliquent au bon utilisateur plutôt qu'à une session anonyme."""
        self.client: Client = client or create_client(url, key)

    def get_or_create_tiers_lieu(self, owner_user_id: str, nom: str) -> TiersLieu:
        # Recherche globale (tous propriétaires confondus), insensible à la
        # casse : un lieu est identifié par son nom, pas par qui l'a créé en
        # premier — sinon un contributeur qui retape le nom d'un lieu existant
        # (au lieu de le sélectionner dans la liste) crée un doublon vide au
        # lieu de rejoindre le lieu déjà documenté.
        nom_normalise = nom.strip()
        existing = (
            self.client.table("tiers_lieux")
            .select("*")
            .ilike("nom", nom_normalise)
            .execute()
        )
        if existing.data:
            return _to_dataclass(TiersLieu, existing.data[0])
        created = (
            self.client.table("tiers_lieux")
            .insert({"owner_user_id": owner_user_id, "nom": nom_normalise})
            .execute()
        )
        return _to_dataclass(TiersLieu, created.data[0])

    def update_tiers_lieu(self, tiers_lieu_id: str, **fields) -> None:
        if not fields:
            return
        self.client.table("tiers_lieux").update(fields).eq("id", tiers_lieu_id).execute()

    def list_tiers_lieux(self, owner_user_id: Optional[str] = None) -> list:
        query = self.client.table("tiers_lieux").select("*")
        if owner_user_id:
            query = query.eq("owner_user_id", owner_user_id)
        result = query.execute()
        return [_to_dataclass(TiersLieu, row) for row in result.data]

    def get_or_create_contributeur(self, user_id: str, tiers_lieu_id: str, role: str) -> Contributeur:
        existing = (
            self.client.table("contributeurs")
            .select("*")
            .eq("user_id", user_id)
            .eq("tiers_lieu_id", tiers_lieu_id)
            .eq("role", role)
            .execute()
        )
        if existing.data:
            return _to_dataclass(Contributeur, existing.data[0])
        created = (
            self.client.table("contributeurs")
            .insert({"user_id": user_id, "tiers_lieu_id": tiers_lieu_id, "role": role})
            .execute()
        )
        return _to_dataclass(Contributeur, created.data[0])

    def get_or_start_session(self, tiers_lieu_id: str, contributeur_id: str) -> SessionEntretien:
        existing = (
            self.client.table("sessions_entretien")
            .select("*")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .eq("contributeur_id", contributeur_id)
            .eq("statut", "en_cours")
            .order("derniere_activite_le", desc=True)
            .limit(1)
            .execute()
        )
        if existing.data:
            return _to_dataclass(SessionEntretien, existing.data[0])
        created = (
            self.client.table("sessions_entretien")
            .insert({"tiers_lieu_id": tiers_lieu_id, "contributeur_id": contributeur_id})
            .execute()
        )
        return _to_dataclass(SessionEntretien, created.data[0])

    def update_session_progress(self, session_id: str, module_courant: Optional[str],
                                 section_courante: Optional[str], completed_sections: list,
                                 statut: str = "en_cours") -> None:
        self.client.table("sessions_entretien").update({
            "module_courant": module_courant,
            "section_courante": section_courante,
            "completed_sections": completed_sections,
            "statut": statut,
            "derniere_activite_le": "now()",
        }).eq("id", session_id).execute()

    def save_answer(self, tiers_lieu_id: str, contributeur_id: str, champ_id: str, valeur,
                     confidentiel: bool = False) -> None:
        self.client.table("reponses").upsert({
            "tiers_lieu_id": tiers_lieu_id,
            "contributeur_id": contributeur_id,
            "champ_id": champ_id,
            "valeur": valeur,
            "confidentiel": confidentiel,
        }, on_conflict="tiers_lieu_id,contributeur_id,champ_id").execute()
        self._log_modification(tiers_lieu_id, contributeur_id, "reponse", champ_id, valeur)

    def _log_modification(self, tiers_lieu_id: str, contributeur_id: str, type_: str,
                           champ_id: Optional[str], valeur) -> None:
        try:
            self.client.table("journal_modifications").insert({
                "tiers_lieu_id": tiers_lieu_id, "contributeur_id": contributeur_id,
                "type": type_, "champ_id": champ_id, "valeur": valeur,
            }).execute()
        except Exception:
            # Table absente avant la migration d'historique : ne jamais faire
            # échouer une sauvegarde de réponse à cause du journal d'audit.
            pass

    def _contributeurs_non_bloques(self, tiers_lieu_id: str) -> set:
        try:
            rows = (
                self.client.table("contributeurs").select("id")
                .eq("tiers_lieu_id", tiers_lieu_id).eq("bloque", False).execute()
            )
        except Exception:
            # Colonne `bloque` absente avant migration : personne n'est
            # considéré bloqué (comportement identique à avant cette feature).
            return None
        return {r["id"] for r in rows.data}

    def get_answers(self, tiers_lieu_id: str, contributeur_id: Optional[str] = None) -> dict:
        actifs = self._contributeurs_non_bloques(tiers_lieu_id)
        result = (
            self.client.table("reponses")
            .select("contributeur_id,champ_id,valeur")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .execute()
        )
        rows = result.data if actifs is None else [r for r in result.data if r["contributeur_id"] in actifs]
        # Les réponses du contributeur courant sont ré-appliquées en dernier pour primer
        # en cas de divergence (même logique que SqliteStore).
        rows = sorted(rows, key=lambda r: r["contributeur_id"] == contributeur_id)
        return {r["champ_id"]: r["valeur"] for r in rows}

    def get_all_answers_by_contributeur(self, tiers_lieu_id: str) -> dict:
        actifs = self._contributeurs_non_bloques(tiers_lieu_id)
        result = (
            self.client.table("reponses")
            .select("contributeur_id,champ_id,valeur")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .execute()
        )
        out: dict = {}
        for r in result.data:
            if actifs is not None and r["contributeur_id"] not in actifs:
                continue
            out.setdefault(r["contributeur_id"], {})[r["champ_id"]] = r["valeur"]
        return out

    def save_free_text_note(self, tiers_lieu_id: str, contributeur_id: str, section_id: Optional[str],
                             texte: str) -> None:
        self.client.table("notes_libres").insert({
            "tiers_lieu_id": tiers_lieu_id,
            "contributeur_id": contributeur_id,
            "section_id": section_id,
            "texte": texte,
        }).execute()
        self._log_modification(tiers_lieu_id, contributeur_id, "note", section_id, texte)

    def get_free_text_notes(self, tiers_lieu_id: str) -> list:
        result = self.client.table("notes_libres").select("*").eq("tiers_lieu_id", tiers_lieu_id).execute()
        return result.data

    def save_lieu_derive(self, lieu_derive: LieuDerive) -> None:
        # lien_externe/photo_url ne sont jamais touchés ici : édités manuellement
        # via update_lieu_derive_liens, indépendants du cycle d'enrichissement.
        self.client.table("lieu_derive").upsert({
            "tiers_lieu_id": lieu_derive.tiers_lieu_id,
            "donnees": lieu_derive.donnees,
            "sources": lieu_derive.sources,
            "profil_semantique_texte": lieu_derive.profil_semantique_texte,
            "prompt_version": lieu_derive.prompt_version,
            "model": lieu_derive.model,
            "source_hash": lieu_derive.source_hash,
            "valide_manuellement": lieu_derive.valide_manuellement,
            "corrections_manuelles": lieu_derive.corrections_manuelles,
        }, on_conflict="tiers_lieu_id").execute()

    def get_lieu_derive(self, tiers_lieu_id: str) -> Optional[LieuDerive]:
        result = (
            self.client.table("lieu_derive").select("*").eq("tiers_lieu_id", tiers_lieu_id).execute()
        )
        if not result.data:
            return None
        return _to_dataclass(LieuDerive, result.data[0])

    def update_lieu_derive_liens(self, tiers_lieu_id: str, lien_externe: Optional[str],
                                  photo_url: Optional[str]) -> None:
        self.client.table("lieu_derive").update({
            "lien_externe": lien_externe,
            "photo_url": photo_url,
        }).eq("tiers_lieu_id", tiers_lieu_id).execute()

    def log_llm_call(self, type_appel: str, model: str, tokens_in: int, tokens_out: int,
                      cout_estime: float, tiers_lieu_id: Optional[str] = None) -> None:
        self.client.table("llm_calls").insert({
            "type_appel": type_appel,
            "tiers_lieu_id": tiers_lieu_id,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cout_estime": cout_estime,
        }).execute()

    # -- administration --------------------------------------------------
    # add_admin_by_email nécessite l'API Admin Supabase (recherche par email)
    # -> n'appeler ces méthodes de curation que sur un store construit via
    # get_admin_store() (clé service_role), après avoir vérifié is_admin()
    # côté appelant avec le store normal de l'utilisateur.

    def is_admin(self, user_id: str) -> bool:
        try:
            result = self.client.table("admins").select("user_id").eq("user_id", user_id).execute()
        except Exception:
            # La table `admins` (migration_002) peut ne pas encore exister sur ce
            # projet Supabase — dégrader en "pas admin" plutôt que de faire
            # planter l'app pour TOUS les utilisateurs (cet appel est fait à
            # chaque chargement de page, pas seulement pour les admins).
            return False
        return bool(result.data)

    def add_admin_by_email(self, email: str) -> bool:
        users = self.client.auth.admin.list_users()
        match = next((u for u in users if (u.email or "").lower() == email.strip().lower()), None)
        if not match:
            return False
        self.client.table("admins").upsert({"user_id": match.id}, on_conflict="user_id").execute()
        return True

    def list_admin_emails(self) -> list:
        try:
            admin_rows = self.client.table("admins").select("user_id").execute().data
        except Exception:
            return []
        if not admin_rows:
            return []
        users = self.client.auth.admin.list_users()
        by_id = {u.id: u.email for u in users}
        return [by_id.get(r["user_id"], r["user_id"]) for r in admin_rows]

    def update_portfolio_entry(self, tiers_lieu_id: str, inclus_portfolio: bool,
                                campagne_texte: Optional[str], campagne_objectif: Optional[str],
                                campagne_contact: Optional[str]) -> None:
        self.client.table("lieu_derive").update({
            "inclus_portfolio": inclus_portfolio,
            "campagne_texte": campagne_texte,
            "campagne_objectif": campagne_objectif,
            "campagne_contact": campagne_contact,
        }).eq("tiers_lieu_id", tiers_lieu_id).execute()

    def list_lieux_portfolio(self) -> list:
        try:
            derive_rows = (
                self.client.table("lieu_derive").select("tiers_lieu_id").eq("inclus_portfolio", True).execute()
            )
        except Exception:
            # Colonne absente avant migration_002 : Portfolio vide plutôt qu'une
            # page publique qui plante.
            return []
        ids = [r["tiers_lieu_id"] for r in derive_rows.data]
        if not ids:
            return []
        result = self.client.table("tiers_lieux").select("*").in_("id", ids).execute()
        return [_to_dataclass(TiersLieu, row) for row in result.data]

    def save_campagne_prioritaire(self, campagne: CampagnePrioritaire) -> None:
        payload = {
            "titre": campagne.titre,
            "description": campagne.description,
            "champ_ids": campagne.champ_ids,
            "date_debut": campagne.date_debut,
            "date_fin": campagne.date_fin,
            "cree_par": campagne.cree_par,
        }
        if campagne.id:
            payload["id"] = campagne.id
            self.client.table("campagnes_prioritaires").upsert(payload, on_conflict="id").execute()
        else:
            self.client.table("campagnes_prioritaires").insert(payload).execute()

    def list_campagnes_prioritaires(self) -> list:
        try:
            result = self.client.table("campagnes_prioritaires").select("*").execute()
        except Exception:
            # Table absente avant migration_002 : dégrader en "aucune campagne"
            # plutôt que de faire planter chaque session d'entretien (appelé à
            # l'initialisation de CollecteToolHandler pour tout le monde).
            return []
        return [_to_dataclass(CampagnePrioritaire, row) for row in result.data]

    def delete_campagne_prioritaire(self, campagne_id: str) -> None:
        self.client.table("campagnes_prioritaires").delete().eq("id", campagne_id).execute()

    # -- historique, stewardship, modération --------------------------------------------------

    def list_contributeurs(self, tiers_lieu_id: str) -> list:
        result = self.client.table("contributeurs").select("*").eq("tiers_lieu_id", tiers_lieu_id).execute()
        return [_to_dataclass(Contributeur, row) for row in result.data]

    def set_contributeur_bloque(self, contributeur_id: str, bloque: bool,
                                 bloque_par: Optional[str] = None) -> None:
        from datetime import datetime, timezone

        payload = {
            "bloque": bloque,
            "bloque_par": bloque_par if bloque else None,
            "bloque_le": datetime.now(timezone.utc).isoformat() if bloque else None,
        }
        self.client.table("contributeurs").update(payload).eq("id", contributeur_id).execute()

    def get_historique(self, tiers_lieu_id: str, limite: int = 100) -> list:
        try:
            result = (
                self.client.table("journal_modifications")
                .select("*, contributeurs(role, user_id, bloque)")
                .eq("tiers_lieu_id", tiers_lieu_id)
                .order("cree_le", desc=True)
                .limit(limite)
                .execute()
            )
        except Exception:
            return []
        entries = []
        for row in result.data:
            contributeur = row.pop("contributeurs", None) or {}
            row["contributeur_role"] = contributeur.get("role")
            row["contributeur_user_id"] = contributeur.get("user_id")
            row["contributeur_bloque"] = contributeur.get("bloque", False)
            entries.append(row)
        return entries

    def save_litige(self, litige: Litige) -> Litige:
        payload = {
            "tiers_lieu_id": litige.tiers_lieu_id,
            "contributeur_vise_id": litige.contributeur_vise_id,
            "signale_par": litige.signale_par,
            "description": litige.description,
            "statut": litige.statut,
        }
        if litige.id:
            payload["id"] = litige.id
            result = self.client.table("litiges").upsert(payload, on_conflict="id").execute()
        else:
            result = self.client.table("litiges").insert(payload).execute()
        return _to_dataclass(Litige, result.data[0])

    def list_litiges(self, tiers_lieu_id: Optional[str] = None) -> list:
        query = self.client.table("litiges").select("*").order("cree_le", desc=True)
        if tiers_lieu_id:
            query = query.eq("tiers_lieu_id", tiers_lieu_id)
        try:
            result = query.execute()
        except Exception:
            # Table absente avant migration : aucun litige plutôt qu'un plantage
            # du panneau de modération dès qu'on l'ouvre.
            return []
        return [_to_dataclass(Litige, row) for row in result.data]

    def resoudre_litige(self, litige_id: str) -> None:
        from datetime import datetime, timezone

        self.client.table("litiges").update(
            {"statut": "resolu", "resolu_le": datetime.now(timezone.utc).isoformat()}
        ).eq("id", litige_id).execute()
