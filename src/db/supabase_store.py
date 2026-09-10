"""Implémentation Supabase (production) du Store. Voir schema.sql pour le DDL
à exécuter sur le projet Supabase avant d'utiliser cette classe."""

from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

from .store import Contributeur, LieuDerive, SessionEntretien, Store, TiersLieu


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
        existing = (
            self.client.table("tiers_lieux")
            .select("*")
            .eq("owner_user_id", owner_user_id)
            .eq("nom", nom)
            .execute()
        )
        if existing.data:
            return _to_dataclass(TiersLieu, existing.data[0])
        created = (
            self.client.table("tiers_lieux")
            .insert({"owner_user_id": owner_user_id, "nom": nom})
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

    def get_answers(self, tiers_lieu_id: str, contributeur_id: Optional[str] = None) -> dict:
        result = (
            self.client.table("reponses")
            .select("contributeur_id,champ_id,valeur")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .execute()
        )
        # Les réponses du contributeur courant sont ré-appliquées en dernier pour primer
        # en cas de divergence (même logique que SqliteStore).
        rows = sorted(result.data, key=lambda r: r["contributeur_id"] == contributeur_id)
        return {r["champ_id"]: r["valeur"] for r in rows}

    def get_all_answers_by_contributeur(self, tiers_lieu_id: str) -> dict:
        result = (
            self.client.table("reponses")
            .select("contributeur_id,champ_id,valeur")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .execute()
        )
        out: dict = {}
        for r in result.data:
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
