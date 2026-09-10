"""Interface d'accès aux données, indépendante du backend (Supabase ou local).

Deux implémentations : `SupabaseStore` (production, cf. supabase_store.py) et
`SqliteStore` (développement/tests locaux sans dépendance réseau, cf.
sqlite_store.py). `factory.get_store()` choisit automatiquement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TiersLieu:
    id: str
    owner_user_id: str
    nom: str
    pays: Optional[str] = None
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    statut_progression: str = "en_cours"


@dataclass
class Contributeur:
    id: str
    user_id: str
    tiers_lieu_id: str
    role: str


@dataclass
class SessionEntretien:
    id: str
    tiers_lieu_id: str
    contributeur_id: str
    module_courant: Optional[str] = None
    section_courante: Optional[str] = None
    statut: str = "en_cours"
    completed_sections: list = field(default_factory=list)


@dataclass
class LieuDerive:
    tiers_lieu_id: str
    donnees: dict
    profil_semantique_texte: str
    prompt_version: str
    model: str
    source_hash: str
    sources: Optional[dict] = None  # {section: [champ_id, ...]} — provenance par section
    valide_manuellement: bool = False
    corrections_manuelles: Optional[dict] = None
    lien_externe: Optional[str] = None
    photo_url: Optional[str] = None
    genere_le: Optional[str] = None


class Store(ABC):
    @abstractmethod
    def get_or_create_tiers_lieu(self, owner_user_id: str, nom: str) -> TiersLieu: ...

    @abstractmethod
    def update_tiers_lieu(self, tiers_lieu_id: str, **fields) -> None: ...

    @abstractmethod
    def list_tiers_lieux(self, owner_user_id: Optional[str] = None) -> list: ...

    @abstractmethod
    def get_or_create_contributeur(self, user_id: str, tiers_lieu_id: str, role: str) -> Contributeur: ...

    @abstractmethod
    def get_or_start_session(self, tiers_lieu_id: str, contributeur_id: str) -> SessionEntretien: ...

    @abstractmethod
    def update_session_progress(self, session_id: str, module_courant: Optional[str],
                                 section_courante: Optional[str], completed_sections: list,
                                 statut: str = "en_cours") -> None: ...

    @abstractmethod
    def save_answer(self, tiers_lieu_id: str, contributeur_id: str, champ_id: str, valeur,
                     confidentiel: bool = False) -> None: ...

    @abstractmethod
    def get_answers(self, tiers_lieu_id: str, contributeur_id: Optional[str] = None) -> dict: ...

    @abstractmethod
    def get_all_answers_by_contributeur(self, tiers_lieu_id: str) -> dict: ...

    @abstractmethod
    def save_free_text_note(self, tiers_lieu_id: str, contributeur_id: str, section_id: Optional[str],
                             texte: str) -> None: ...

    @abstractmethod
    def get_free_text_notes(self, tiers_lieu_id: str) -> list: ...

    @abstractmethod
    def save_lieu_derive(self, lieu_derive: LieuDerive) -> None:
        """Écrit/remplace la donnée dérivée d'un lieu. Ne touche jamais à
        `reponses` — table strictement séparée de la donnée brute."""
        ...

    @abstractmethod
    def get_lieu_derive(self, tiers_lieu_id: str) -> Optional[LieuDerive]: ...

    @abstractmethod
    def update_lieu_derive_liens(self, tiers_lieu_id: str, lien_externe: Optional[str],
                                  photo_url: Optional[str]) -> None:
        """Met à jour uniquement lien_externe/photo_url (édition manuelle depuis
        l'Annuaire), sans toucher au reste de la donnée dérivée."""
        ...

    @abstractmethod
    def log_llm_call(self, type_appel: str, model: str, tokens_in: int, tokens_out: int,
                      cout_estime: float, tiers_lieu_id: Optional[str] = None) -> None: ...
