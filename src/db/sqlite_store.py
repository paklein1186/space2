"""Implémentation locale (SQLite) du Store — pour le développement et les tests
sans dépendance à un projet Supabase réel. Même schéma logique que schema.sql,
adapté à SQLite (uuid remplacé par un id texte généré côté Python)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from .store import CampagnePrioritaire, Contributeur, LieuDerive, SessionEntretien, Store, TiersLieu

DDL = """
create table if not exists tiers_lieux (
    id text primary key,
    owner_user_id text not null,
    nom text not null,
    pays text,
    region text,
    latitude real,
    longitude real,
    statut_progression text default 'en_cours'
);
create table if not exists contributeurs (
    id text primary key,
    user_id text not null,
    tiers_lieu_id text not null,
    role text not null,
    unique (user_id, tiers_lieu_id, role)
);
create table if not exists sessions_entretien (
    id text primary key,
    tiers_lieu_id text not null,
    contributeur_id text not null,
    module_courant text,
    section_courante text,
    completed_sections text not null default '[]',
    statut text not null default 'en_cours'
);
create table if not exists reponses (
    tiers_lieu_id text not null,
    contributeur_id text not null,
    champ_id text not null,
    valeur text,
    confidentiel integer not null default 0,
    primary key (tiers_lieu_id, contributeur_id, champ_id)
);
create table if not exists notes_libres (
    id text primary key,
    tiers_lieu_id text not null,
    contributeur_id text not null,
    section_id text,
    texte text not null
);
create table if not exists lieu_derive (
    tiers_lieu_id text primary key,
    donnees text not null,
    sources text,
    profil_semantique_texte text not null,
    prompt_version text not null,
    model text not null,
    source_hash text not null,
    valide_manuellement integer not null default 0,
    corrections_manuelles text,
    lien_externe text,
    photo_url text,
    inclus_portfolio integer not null default 0,
    campagne_texte text,
    campagne_objectif text,
    campagne_contact text,
    genere_le text not null default (datetime('now'))
);
create table if not exists admins (
    user_id text primary key
);
create table if not exists campagnes_prioritaires (
    id text primary key,
    titre text not null,
    description text,
    champ_ids text not null default '[]',
    date_debut text not null,
    date_fin text not null,
    cree_par text,
    cree_le text not null default (datetime('now'))
);
create table if not exists llm_calls (
    id text primary key,
    type_appel text not null,
    tiers_lieu_id text,
    model text not null,
    tokens_in integer not null,
    tokens_out integer not null,
    cout_estime real not null,
    cree_le text not null default (datetime('now'))
);
"""


class SqliteStore(Store):
    def __init__(self, db_path: str = "data/local_dev.sqlite3"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(DDL)
        self.conn.commit()

    # -- tiers_lieux --------------------------------------------------

    def get_or_create_tiers_lieu(self, owner_user_id: str, nom: str) -> TiersLieu:
        # Recherche globale (tous propriétaires confondus), insensible à la
        # casse et aux espaces superflus : un lieu est identifié par son nom,
        # pas par qui l'a créé en premier — sinon un contributeur qui retape
        # le nom d'un lieu existant (au lieu de le sélectionner dans la liste)
        # crée un doublon vide au lieu de rejoindre le lieu déjà documenté.
        nom_normalise = nom.strip()
        row = self.conn.execute(
            "select * from tiers_lieux where trim(lower(nom)) = trim(lower(?))", (nom_normalise,)
        ).fetchone()
        if row:
            return TiersLieu(**dict(row))
        new_id = str(uuid.uuid4())
        self.conn.execute(
            "insert into tiers_lieux (id, owner_user_id, nom) values (?, ?, ?)",
            (new_id, owner_user_id, nom_normalise),
        )
        self.conn.commit()
        return TiersLieu(id=new_id, owner_user_id=owner_user_id, nom=nom_normalise)

    def update_tiers_lieu(self, tiers_lieu_id: str, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [tiers_lieu_id]
        self.conn.execute(f"update tiers_lieux set {columns} where id = ?", values)
        self.conn.commit()

    def list_tiers_lieux(self, owner_user_id: Optional[str] = None) -> list:
        if owner_user_id:
            rows = self.conn.execute(
                "select * from tiers_lieux where owner_user_id = ?", (owner_user_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("select * from tiers_lieux").fetchall()
        return [TiersLieu(**dict(r)) for r in rows]

    # -- contributeurs --------------------------------------------------

    def get_or_create_contributeur(self, user_id: str, tiers_lieu_id: str, role: str) -> Contributeur:
        row = self.conn.execute(
            "select * from contributeurs where user_id = ? and tiers_lieu_id = ? and role = ?",
            (user_id, tiers_lieu_id, role),
        ).fetchone()
        if row:
            return Contributeur(**dict(row))
        new_id = str(uuid.uuid4())
        self.conn.execute(
            "insert into contributeurs (id, user_id, tiers_lieu_id, role) values (?, ?, ?, ?)",
            (new_id, user_id, tiers_lieu_id, role),
        )
        self.conn.commit()
        return Contributeur(id=new_id, user_id=user_id, tiers_lieu_id=tiers_lieu_id, role=role)

    # -- sessions --------------------------------------------------

    def get_or_start_session(self, tiers_lieu_id: str, contributeur_id: str) -> SessionEntretien:
        row = self.conn.execute(
            "select * from sessions_entretien where tiers_lieu_id = ? and contributeur_id = ? "
            "and statut = 'en_cours' order by rowid desc limit 1",
            (tiers_lieu_id, contributeur_id),
        ).fetchone()
        if row:
            data = dict(row)
            data["completed_sections"] = json.loads(data["completed_sections"] or "[]")
            return SessionEntretien(**data)
        new_id = str(uuid.uuid4())
        self.conn.execute(
            "insert into sessions_entretien (id, tiers_lieu_id, contributeur_id) values (?, ?, ?)",
            (new_id, tiers_lieu_id, contributeur_id),
        )
        self.conn.commit()
        return SessionEntretien(id=new_id, tiers_lieu_id=tiers_lieu_id, contributeur_id=contributeur_id)

    def update_session_progress(self, session_id: str, module_courant: Optional[str],
                                 section_courante: Optional[str], completed_sections: list,
                                 statut: str = "en_cours") -> None:
        self.conn.execute(
            "update sessions_entretien set module_courant = ?, section_courante = ?, "
            "completed_sections = ?, statut = ? where id = ?",
            (module_courant, section_courante, json.dumps(completed_sections), statut, session_id),
        )
        self.conn.commit()

    # -- reponses --------------------------------------------------

    def save_answer(self, tiers_lieu_id: str, contributeur_id: str, champ_id: str, valeur,
                     confidentiel: bool = False) -> None:
        self.conn.execute(
            "insert into reponses (tiers_lieu_id, contributeur_id, champ_id, valeur, confidentiel) "
            "values (?, ?, ?, ?, ?) "
            "on conflict(tiers_lieu_id, contributeur_id, champ_id) do update set valeur = excluded.valeur, "
            "confidentiel = excluded.confidentiel",
            (tiers_lieu_id, contributeur_id, champ_id, json.dumps(valeur), int(confidentiel)),
        )
        self.conn.commit()

    def get_answers(self, tiers_lieu_id: str, contributeur_id: Optional[str] = None) -> dict:
        """Vue fusionnée : toutes les réponses du lieu, celles du contributeur
        courant prenant le pas en cas de divergence — utilisée pour résoudre
        les conditions du schéma pendant une session."""
        rows = self.conn.execute(
            "select contributeur_id, champ_id, valeur from reponses where tiers_lieu_id = ? "
            "order by (contributeur_id = ?) asc",
            (tiers_lieu_id, contributeur_id or ""),
        ).fetchall()
        merged = {}
        for r in rows:
            merged[r["champ_id"]] = json.loads(r["valeur"]) if r["valeur"] is not None else None
        return merged

    def get_all_answers_by_contributeur(self, tiers_lieu_id: str) -> dict:
        rows = self.conn.execute(
            "select contributeur_id, champ_id, valeur from reponses where tiers_lieu_id = ?",
            (tiers_lieu_id,),
        ).fetchall()
        result: dict = {}
        for r in rows:
            result.setdefault(r["contributeur_id"], {})[r["champ_id"]] = (
                json.loads(r["valeur"]) if r["valeur"] is not None else None
            )
        return result

    # -- notes libres --------------------------------------------------

    def save_free_text_note(self, tiers_lieu_id: str, contributeur_id: str, section_id: Optional[str],
                             texte: str) -> None:
        self.conn.execute(
            "insert into notes_libres (id, tiers_lieu_id, contributeur_id, section_id, texte) "
            "values (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), tiers_lieu_id, contributeur_id, section_id, texte),
        )
        self.conn.commit()

    def get_free_text_notes(self, tiers_lieu_id: str) -> list:
        rows = self.conn.execute(
            "select * from notes_libres where tiers_lieu_id = ?", (tiers_lieu_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- donnée dérivée (jamais dans reponses) --------------------------------------------------

    def save_lieu_derive(self, lieu_derive: LieuDerive) -> None:
        # lien_externe/photo_url ne sont jamais touchés ici : ce sont des champs
        # édités manuellement (voir update_lieu_derive_liens), indépendants du
        # cycle de (ré)enrichissement automatique.
        self.conn.execute(
            "insert into lieu_derive (tiers_lieu_id, donnees, sources, profil_semantique_texte, "
            "prompt_version, model, source_hash, valide_manuellement, corrections_manuelles) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "on conflict(tiers_lieu_id) do update set donnees = excluded.donnees, "
            "sources = excluded.sources, "
            "profil_semantique_texte = excluded.profil_semantique_texte, "
            "prompt_version = excluded.prompt_version, model = excluded.model, "
            "source_hash = excluded.source_hash, genere_le = datetime('now')",
            (
                lieu_derive.tiers_lieu_id,
                json.dumps(lieu_derive.donnees, ensure_ascii=False),
                json.dumps(lieu_derive.sources, ensure_ascii=False) if lieu_derive.sources else None,
                lieu_derive.profil_semantique_texte,
                lieu_derive.prompt_version,
                lieu_derive.model,
                lieu_derive.source_hash,
                int(lieu_derive.valide_manuellement),
                json.dumps(lieu_derive.corrections_manuelles, ensure_ascii=False)
                if lieu_derive.corrections_manuelles else None,
            ),
        )
        self.conn.commit()

    def get_lieu_derive(self, tiers_lieu_id: str) -> Optional[LieuDerive]:
        row = self.conn.execute(
            "select * from lieu_derive where tiers_lieu_id = ?", (tiers_lieu_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        return LieuDerive(
            tiers_lieu_id=data["tiers_lieu_id"],
            donnees=json.loads(data["donnees"]),
            sources=json.loads(data["sources"]) if data["sources"] else None,
            profil_semantique_texte=data["profil_semantique_texte"],
            prompt_version=data["prompt_version"],
            model=data["model"],
            source_hash=data["source_hash"],
            valide_manuellement=bool(data["valide_manuellement"]),
            corrections_manuelles=json.loads(data["corrections_manuelles"])
            if data["corrections_manuelles"] else None,
            lien_externe=data["lien_externe"],
            photo_url=data["photo_url"],
            inclus_portfolio=bool(data["inclus_portfolio"]),
            campagne_texte=data["campagne_texte"],
            campagne_objectif=data["campagne_objectif"],
            campagne_contact=data["campagne_contact"],
            genere_le=data["genere_le"],
        )

    def update_lieu_derive_liens(self, tiers_lieu_id: str, lien_externe: Optional[str],
                                  photo_url: Optional[str]) -> None:
        self.conn.execute(
            "update lieu_derive set lien_externe = ?, photo_url = ? where tiers_lieu_id = ?",
            (lien_externe, photo_url, tiers_lieu_id),
        )
        self.conn.commit()

    # -- suivi des coûts LLM --------------------------------------------------

    def log_llm_call(self, type_appel: str, model: str, tokens_in: int, tokens_out: int,
                      cout_estime: float, tiers_lieu_id: Optional[str] = None) -> None:
        self.conn.execute(
            "insert into llm_calls (id, type_appel, tiers_lieu_id, model, tokens_in, tokens_out, "
            "cout_estime) values (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), type_appel, tiers_lieu_id, model, tokens_in, tokens_out, cout_estime),
        )
        self.conn.commit()

    # -- administration --------------------------------------------------

    def is_admin(self, user_id: str) -> bool:
        row = self.conn.execute("select 1 from admins where user_id = ?", (user_id,)).fetchone()
        return row is not None

    def add_admin_by_email(self, email: str) -> bool:
        # Pas de vraie table auth.users en local : l'email EST l'identifiant
        # utilisateur en mode développement (cf. LOCAL_DEV_AUTOLOGIN / mode dev
        # sans Supabase), donc toujours "trouvé".
        self.conn.execute("insert or ignore into admins (user_id) values (?)", (email,))
        self.conn.commit()
        return True

    def list_admin_emails(self) -> list:
        return [r["user_id"] for r in self.conn.execute("select user_id from admins").fetchall()]

    def update_portfolio_entry(self, tiers_lieu_id: str, inclus_portfolio: bool,
                                campagne_texte: Optional[str], campagne_objectif: Optional[str],
                                campagne_contact: Optional[str]) -> None:
        self.conn.execute(
            "update lieu_derive set inclus_portfolio = ?, campagne_texte = ?, "
            "campagne_objectif = ?, campagne_contact = ? where tiers_lieu_id = ?",
            (int(inclus_portfolio), campagne_texte, campagne_objectif, campagne_contact, tiers_lieu_id),
        )
        self.conn.commit()

    def list_lieux_portfolio(self) -> list:
        rows = self.conn.execute(
            "select tiers_lieu_id from lieu_derive where inclus_portfolio = 1"
        ).fetchall()
        ids = {r["tiers_lieu_id"] for r in rows}
        return [lieu for lieu in self.list_tiers_lieux() if lieu.id in ids]

    def save_campagne_prioritaire(self, campagne: CampagnePrioritaire) -> None:
        self.conn.execute(
            "insert into campagnes_prioritaires (id, titre, description, champ_ids, date_debut, "
            "date_fin, cree_par) values (?, ?, ?, ?, ?, ?, ?) "
            "on conflict(id) do update set titre = excluded.titre, description = excluded.description, "
            "champ_ids = excluded.champ_ids, date_debut = excluded.date_debut, date_fin = excluded.date_fin",
            (
                campagne.id or str(uuid.uuid4()), campagne.titre, campagne.description,
                json.dumps(campagne.champ_ids, ensure_ascii=False), campagne.date_debut,
                campagne.date_fin, campagne.cree_par,
            ),
        )
        self.conn.commit()

    def list_campagnes_prioritaires(self) -> list:
        rows = self.conn.execute("select * from campagnes_prioritaires").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            result.append(CampagnePrioritaire(
                id=d["id"], titre=d["titre"], description=d["description"],
                champ_ids=json.loads(d["champ_ids"]), date_debut=d["date_debut"],
                date_fin=d["date_fin"], cree_par=d["cree_par"], cree_le=d["cree_le"],
            ))
        return result

    def delete_campagne_prioritaire(self, campagne_id: str) -> None:
        self.conn.execute("delete from campagnes_prioritaires where id = ?", (campagne_id,))
        self.conn.commit()
