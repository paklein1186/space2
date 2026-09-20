"""Implémentation Supabase (production) du Store. Voir schema.sql pour le DDL
à exécuter sur le projet Supabase avant d'utiliser cette classe."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from supabase import Client, create_client

from .store import (
    CampagnePrioritaire,
    ConversationBibliotheque,
    Contributeur,
    LieuDerive,
    Litige,
    SessionEntretien,
    Store,
    TiersLieu,
)


def _to_dataclass(cls, row: dict):
    """Filtre les colonnes Supabase (ex. `cree_le`) absentes du dataclass
    avant construction — évite un TypeError sur tout champ ajouté côté SQL
    (audit, timestamps) qui n'a pas d'équivalent côté Python."""
    return cls(**{k: v for k, v in row.items() if k in cls.__dataclass_fields__})


PAGE = 1000  # plafond de lignes par requête PostgREST


def creer_client(url: str, key: str) -> Client:
    """Client Supabase en HTTP/1.1 : le client par défaut multiplexe en HTTP/2
    sur une connexion unique, qui n'est pas sûre en accès concurrent — mesuré :
    ~3 % de requêtes en échec (ReadError, RemoteProtocolError COMPRESSION_ERROR)
    dès que plusieurs threads lisent en même temps (outils de l'agent en
    parallèle, pages Streamlit). Avec HTTP/1.1 : aucune erreur, même vitesse."""
    import httpx
    from supabase.lib.client_options import SyncClientOptions

    http = httpx.Client(http2=False, timeout=httpx.Timeout(60.0, connect=10.0))
    return create_client(url, (key or "").strip(), options=SyncClientOptions(httpx_client=http))


def _lire_tout(fabrique_requete) -> list:
    """Lit toutes les lignes d'une requête par pages de PAGE : sans cela,
    PostgREST tronque silencieusement à 1000 lignes (la table `reponses` en
    comptait 925 le 2026-09-20). `fabrique_requete` doit renvoyer une requête
    NEUVE, triée de façon stable, à chaque appel."""
    lignes, debut = [], 0
    while True:
        page = fabrique_requete().range(debut, debut + PAGE - 1).execute().data
        lignes.extend(page)
        if len(page) < PAGE:
            return lignes
        debut += PAGE


class SupabaseStore(Store):
    def __init__(self, url: str, key: str, client: Optional[Client] = None):
        """Si `client` est fourni (ex. déjà authentifié via OTP dans app.py),
        il est réutilisé tel quel — indispensable pour que les policies RLS
        s'appliquent au bon utilisateur plutôt qu'à une session anonyme."""
        self.client: Client = client or creer_client(url, key)

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

    def delete_tiers_lieu(self, tiers_lieu_id: str) -> None:
        # Toutes les tables qui référencent tiers_lieu_id sont en "on delete
        # cascade" côté schema.sql (contributeurs, reponses, notes_libres,
        # sessions_entretien, lieu_derive, journal_modifications, litiges) —
        # une seule suppression suffit. llm_calls (on delete set null) garde
        # son historique de coût, orphelin plutôt que supprimé.
        self.client.table("tiers_lieux").delete().eq("id", tiers_lieu_id).execute()

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

    def _contributeurs_bloques(self, tiers_lieu_id: str) -> set:
        """Ids explicitement bloqués (pas l'inverse : une réponse dont le
        contributeur n'a plus de ligne dans `contributeurs` — vu en
        production le 2026-09-15, cause encore non élucidée — doit rester
        visible. Un ancien filtre `actifs = non-bloqués` cachait purement et
        simplement toutes ces réponses orphelines au lieu de ne cacher que
        celles réellement bloquées."""
        try:
            rows = (
                self.client.table("contributeurs").select("id")
                .eq("tiers_lieu_id", tiers_lieu_id).eq("bloque", True).execute()
            )
        except Exception:
            # Colonne `bloque` absente avant migration : personne n'est
            # considéré bloqué (comportement identique à avant cette feature).
            return set()
        return {r["id"] for r in rows.data}

    def get_answers(self, tiers_lieu_id: str, contributeur_id: Optional[str] = None) -> dict:
        bloques = self._contributeurs_bloques(tiers_lieu_id)
        result = (
            self.client.table("reponses")
            .select("contributeur_id,champ_id,valeur")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .execute()
        )
        rows = [r for r in result.data if r["contributeur_id"] not in bloques]
        # Les réponses du contributeur courant sont ré-appliquées en dernier pour primer
        # en cas de divergence (même logique que SqliteStore).
        rows = sorted(rows, key=lambda r: r["contributeur_id"] == contributeur_id)
        return {r["champ_id"]: r["valeur"] for r in rows}

    def get_all_answers_by_contributeur(self, tiers_lieu_id: str) -> dict:
        bloques = self._contributeurs_bloques(tiers_lieu_id)
        result = (
            self.client.table("reponses")
            .select("contributeur_id,champ_id,valeur")
            .eq("tiers_lieu_id", tiers_lieu_id)
            .execute()
        )
        out: dict = {}
        for r in result.data:
            if r["contributeur_id"] in bloques:
                continue
            out.setdefault(r["contributeur_id"], {})[r["champ_id"]] = r["valeur"]
        return out

    def get_all_answers_by_contributeur_batch(self, tiers_lieu_ids: list,
                                               exclure_confidentiel: bool = False) -> dict:
        if not tiers_lieu_ids:
            return {}
        try:
            contributeurs_result = (
                self.client.table("contributeurs").select("id,tiers_lieu_id")
                .in_("tiers_lieu_id", tiers_lieu_ids).eq("bloque", True).execute()
            )
            bloques_par_lieu: dict = {}
            for c in contributeurs_result.data:
                bloques_par_lieu.setdefault(c["tiers_lieu_id"], set()).add(c["id"])
        except Exception:
            # Colonne `bloque` absente avant migration : personne n'est
            # considéré bloqué (comportement identique à avant cette feature,
            # voir _contributeurs_bloques).
            bloques_par_lieu = {}

        def requete():
            q = (self.client.table("reponses")
                 .select("tiers_lieu_id,contributeur_id,champ_id,valeur")
                 .in_("tiers_lieu_id", tiers_lieu_ids))
            if exclure_confidentiel:
                q = q.eq("confidentiel", False)
            return q.order("tiers_lieu_id").order("contributeur_id").order("champ_id")

        out: dict = {}
        for r in _lire_tout(requete):
            bloques = bloques_par_lieu.get(r["tiers_lieu_id"], set())
            if r["contributeur_id"] in bloques:
                continue
            out.setdefault(r["tiers_lieu_id"], {}).setdefault(r["contributeur_id"], {})[r["champ_id"]] = r["valeur"]
        return out

    def get_lieux_avec_confidentiel(self, tiers_lieu_ids: list) -> set:
        if not tiers_lieu_ids:
            return set()
        lignes = _lire_tout(lambda: (
            self.client.table("reponses").select("tiers_lieu_id,contributeur_id,champ_id")
            .in_("tiers_lieu_id", tiers_lieu_ids).eq("confidentiel", True)
            .order("tiers_lieu_id").order("contributeur_id").order("champ_id")))
        return {r["tiers_lieu_id"] for r in lignes}

    def get_public_answers_batch(self, tiers_lieu_ids: list) -> dict:
        if not tiers_lieu_ids:
            return {}
        lignes = _lire_tout(lambda: (
            self.client.table("reponses")
            .select("tiers_lieu_id,contributeur_id,champ_id,valeur")
            .in_("tiers_lieu_id", tiers_lieu_ids)
            .eq("confidentiel", False)
            .order("maj_le").order("tiers_lieu_id").order("contributeur_id").order("champ_id")))
        # Bloqués : même sémantique que get_answers (exclusion explicite
        # uniquement — un contributeur absent de la table ne doit pas
        # masquer ses réponses, voir _contributeurs_bloques).
        bloques: dict = {}
        try:
            for c in (
                self.client.table("contributeurs").select("id,tiers_lieu_id")
                .in_("tiers_lieu_id", tiers_lieu_ids).eq("bloque", True).execute().data
            ):
                bloques.setdefault(c["tiers_lieu_id"], set()).add(c["id"])
        except Exception:
            bloques = {}
        out: dict = {}
        for r in lignes:
            if r["contributeur_id"] in bloques.get(r["tiers_lieu_id"], set()):
                continue
            out.setdefault(r["tiers_lieu_id"], {})[r["champ_id"]] = r["valeur"]
        return out

    def update_lieu_derive_publique(self, tiers_lieu_id: str, donnees_publiques: dict,
                                     source_hash: str) -> None:
        self.client.table("lieu_derive").update({
            "donnees_publiques": donnees_publiques,
            "donnees_publiques_source_hash": source_hash,
            "donnees_publiques_maj": datetime.now(timezone.utc).isoformat(),
        }).eq("tiers_lieu_id", tiers_lieu_id).execute()

    def add_evenement_ctg(self, tiers_lieu_id: str, ctg_event_id: str, type_: str,
                           titre: Optional[str], texte: Optional[str], url: Optional[str],
                           survenu_le: Optional[str]) -> None:
        self.client.table("evenements_ctg").upsert({
            "tiers_lieu_id": tiers_lieu_id, "ctg_event_id": ctg_event_id, "type": type_,
            "titre": titre, "texte": texte, "url": url, "survenu_le": survenu_le,
        }, on_conflict="ctg_event_id").execute()

    def list_evenements_ctg(self) -> list:
        return (
            self.client.table("evenements_ctg")
            .select("tiers_lieu_id,type,titre,texte,url,survenu_le")
            .order("survenu_le", desc=True).execute().data
        )

    def upsert_objets_ctg(self, objets: list) -> None:
        if objets:
            self.client.table("objets_ctg").upsert(objets, on_conflict="ctg_id").execute()

    def list_objets_ctg(self) -> list:
        return _lire_tout(lambda: self.client.table("objets_ctg").select("*").order("ctg_id"))

    def upsert_acces_externe(self, email: str, source: str, guilde_id: Optional[str],
                              statut: str) -> None:
        self.client.table("acces_externes").upsert({
            "email": email.strip().lower(), "source": source, "guilde_id": guilde_id,
            "statut": statut, "maj_le": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="email").execute()

    def has_acces_externe(self, email: str) -> bool:
        result = (
            self.client.table("acces_externes").select("email")
            .eq("email", email.strip().lower()).eq("statut", "actif").execute()
        )
        return bool(result.data)

    def get_reponses_pour_champs(self, champ_ids: list) -> list:
        if not champ_ids:
            return []
        result = (
            self.client.table("reponses")
            .select("tiers_lieu_id,contributeur_id,champ_id,valeur")
            .in_("champ_id", champ_ids)
            .execute()
        )
        return result.data

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
        # order() explicite : Postgres/PostgREST ne garantit aucun ordre par
        # défaut, ce qui rendait compute_source_hash() non déterministe d'un
        # appel à l'autre (voir le tri côté hash pour le détail).
        result = (
            self.client.table("notes_libres").select("*")
            .eq("tiers_lieu_id", tiers_lieu_id).order("id").execute()
        )
        return result.data

    def get_notes_by_section_id(self, section_id: str) -> list:
        result = (
            self.client.table("notes_libres").select("*")
            .eq("section_id", section_id).order("id").execute()
        )
        return result.data

    def update_free_text_note(self, note_id: str, texte: str) -> None:
        self.client.table("notes_libres").update({"texte": texte}).eq("id", note_id).execute()

    def delete_free_text_note(self, note_id: str) -> None:
        self.client.table("notes_libres").delete().eq("id", note_id).execute()

    def delete_answer(self, tiers_lieu_id: str, contributeur_id: str, champ_id: str) -> None:
        self.client.table("reponses").delete().eq("tiers_lieu_id", tiers_lieu_id) \
            .eq("contributeur_id", contributeur_id).eq("champ_id", champ_id).execute()

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

    def get_lieu_derive_batch(self, tiers_lieu_ids: list) -> dict:
        if not tiers_lieu_ids:
            return {}
        result = self.client.table("lieu_derive").select("*").in_("tiers_lieu_id", tiers_lieu_ids).execute()
        return {row["tiers_lieu_id"]: _to_dataclass(LieuDerive, row) for row in result.data}

    def update_lieu_derive_liens(self, tiers_lieu_id: str, lien_externe: Optional[str],
                                  photo_url: Optional[str]) -> None:
        self.client.table("lieu_derive").update({
            "lien_externe": lien_externe,
            "photo_url": photo_url,
        }).eq("tiers_lieu_id", tiers_lieu_id).execute()

    def update_lieu_derive_traduction(self, tiers_lieu_id: str, donnees_en: dict,
                                       source_hash: str) -> None:
        self.client.table("lieu_derive").update({
            "donnees_en": donnees_en,
            "donnees_en_source_hash": source_hash,
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

    def update_besoins_mis_en_avant(self, tiers_lieu_id: str, besoins: list) -> None:
        self.client.table("lieu_derive").update({
            "besoins_mis_en_avant": besoins,
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

    def list_users_with_last_login(self) -> list:
        users = self.client.auth.admin.list_users()
        try:
            admin_ids = {r["user_id"] for r in self.client.table("admins").select("user_id").execute().data}
        except Exception:
            admin_ids = set()
        resultat = [
            {
                "email": u.email or u.id,
                "cree_le": str(u.created_at) if u.created_at else None,
                "derniere_connexion": str(u.last_sign_in_at) if u.last_sign_in_at else None,
                "admin": u.id in admin_ids,
                # "@system.local" : voir SERVICE_ACCOUNTS_EMAIL_DOMAIN dans
                # migrate_sqlite_to_supabase.py (comptes créés pour attribuer
                # les imports groupés/le crawl à un auteur, jamais un vrai
                # utilisateur connecté — leur dernière_connexion reste None).
                "compte_service": (u.email or "").endswith("@system.local"),
            }
            for u in users
        ]
        resultat.sort(key=lambda r: r["derniere_connexion"] or "", reverse=True)
        return resultat

    def map_user_emails(self, user_ids: list) -> dict:
        if not user_ids:
            return {}
        users = self.client.auth.admin.list_users()
        voulus = set(user_ids)
        return {u.id: u.email for u in users if u.id in voulus}

    # -- historique des conversations Bibliothèque ------------------------
    # Même repli que campagnes_prioritaires ci-dessus : table absente avant
    # migration_003 -> dégrader silencieusement (liste vide / None / no-op)
    # plutôt que de casser la Bibliothèque pour tout le monde tant que la
    # migration n'a pas été exécutée.

    def save_conversation_bibliotheque(self, conversation: ConversationBibliotheque) -> str:
        from datetime import datetime, timezone

        payload = {
            "user_id": conversation.user_id,
            "titre": conversation.titre,
            "messages": conversation.messages,
            "maj_le": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if conversation.id:
                payload["id"] = conversation.id
                result = self.client.table("conversations_bibliotheque").upsert(
                    payload, on_conflict="id"
                ).execute()
            else:
                result = self.client.table("conversations_bibliotheque").insert(payload).execute()
        except Exception:
            return conversation.id
        return result.data[0]["id"] if result.data else conversation.id

    def list_conversations_bibliotheque(self, user_id: str) -> list:
        try:
            result = (
                self.client.table("conversations_bibliotheque")
                .select("id,titre,cree_le,maj_le")
                .eq("user_id", user_id)
                .order("maj_le", desc=True)
                .execute()
            )
        except Exception:
            return []
        return [_to_dataclass(ConversationBibliotheque, {**row, "user_id": user_id, "messages": []})
                for row in result.data]

    def get_conversation_bibliotheque(self, conversation_id: str) -> Optional[ConversationBibliotheque]:
        try:
            result = (
                self.client.table("conversations_bibliotheque").select("*").eq("id", conversation_id).execute()
            )
        except Exception:
            return None
        return _to_dataclass(ConversationBibliotheque, result.data[0]) if result.data else None

    def delete_conversation_bibliotheque(self, conversation_id: str) -> None:
        try:
            self.client.table("conversations_bibliotheque").delete().eq("id", conversation_id).execute()
        except Exception:
            pass

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
