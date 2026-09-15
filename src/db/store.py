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
    bloque: bool = False
    bloque_le: Optional[str] = None
    bloque_par: Optional[str] = None


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
    inclus_portfolio: bool = False
    campagne_texte: Optional[str] = None
    campagne_objectif: Optional[str] = None
    campagne_contact: Optional[str] = None
    genere_le: Optional[str] = None


@dataclass
class CampagnePrioritaire:
    titre: str
    champ_ids: list
    date_debut: str
    date_fin: str
    id: str = ""  # vide = création (id généré par le store), sinon mise à jour
    description: Optional[str] = None
    cree_par: Optional[str] = None
    cree_le: Optional[str] = None


@dataclass
class Litige:
    """Signalement d'un désaccord sur les contributions d'un lieu — ouvert par
    un steward/fondateur/équipe de ce lieu ou par un admin, résolu uniquement
    par un admin (arbitrage)."""

    tiers_lieu_id: str
    description: str
    signale_par: str
    id: str = ""  # vide = création
    contributeur_vise_id: Optional[str] = None
    statut: str = "ouvert"  # "ouvert" | "resolu"
    cree_le: Optional[str] = None
    resolu_le: Optional[str] = None


@dataclass
class ConversationBibliotheque:
    """Historique de chat de l'assistant Bibliothèque, par utilisateur —
    jamais rattaché à un lieu précis (la Bibliothèque interroge l'ensemble
    du corpus). `messages` : liste de {"role": "user"|"assistant", "content": str},
    format d'affichage simplifié (pas le format brut de l'API Anthropic —
    une conversation rouverte redémarre avec un contexte simplifié plutôt
    que de reconstruire l'état exact des appels de tools passés)."""

    user_id: str
    messages: list
    id: str = ""  # vide = création (id généré par le store)
    titre: Optional[str] = None
    cree_le: Optional[str] = None
    maj_le: Optional[str] = None


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
    def get_all_answers_by_contributeur_batch(self, tiers_lieu_ids: list) -> dict:
        """Version batch de get_all_answers_by_contributeur : une seule paire
        de requêtes (contributeurs bloqués + réponses) pour plusieurs lieux à
        la fois, clé = tiers_lieu_id, au lieu de N x 2 appels séquentiels —
        utilisée par les vues agrégées (Observatoire) qui parcourent tous les
        lieux d'un coup."""
        ...

    @abstractmethod
    def get_reponses_pour_champs(self, champ_ids: list) -> list:
        """Réponses à un ensemble de champs, tous lieux confondus — chaque
        élément : {tiers_lieu_id, contributeur_id, champ_id, valeur}. Utilisé
        pour lister les répondants d'une campagne prioritaire (email, lieu,
        rôle) indépendamment du lieu auquel ils appartiennent."""
        ...

    @abstractmethod
    def save_free_text_note(self, tiers_lieu_id: str, contributeur_id: str, section_id: Optional[str],
                             texte: str) -> None: ...

    @abstractmethod
    def get_free_text_notes(self, tiers_lieu_id: str) -> list: ...

    @abstractmethod
    def get_notes_by_section_id(self, section_id: str) -> list:
        """Notes libres tous lieux confondus portant ce `section_id` — utilisé
        pour retrouver les retours d'expérience taggués "bonne_pratique" par
        l'agent d'entretien (voir collecte_agent.SYSTEM_PROMPT), indépendamment
        du lieu, pour les exposer à la Bibliothèque comme un jeu de données
        comparable entre lieux."""
        ...

    @abstractmethod
    def update_free_text_note(self, note_id: str, texte: str) -> None:
        """Édite le texte d'une note libre existante (import ou saisie
        conversationnelle) — utilisé par la vue admin "Données brutes"."""
        ...

    @abstractmethod
    def delete_free_text_note(self, note_id: str) -> None: ...

    @abstractmethod
    def delete_answer(self, tiers_lieu_id: str, contributeur_id: str, champ_id: str) -> None:
        """Supprime une réponse structurée précise — utilisé par la vue admin
        "Données brutes" pour retirer une saisie erronée ou obsolète."""
        ...

    @abstractmethod
    def save_lieu_derive(self, lieu_derive: LieuDerive) -> None:
        """Écrit/remplace la donnée dérivée d'un lieu. Ne touche jamais à
        `reponses` — table strictement séparée de la donnée brute."""
        ...

    @abstractmethod
    def get_lieu_derive(self, tiers_lieu_id: str) -> Optional[LieuDerive]: ...

    @abstractmethod
    def get_lieu_derive_batch(self, tiers_lieu_ids: list) -> dict:
        """Version batch de get_lieu_derive : une seule requête pour plusieurs
        lieux à la fois (clé = tiers_lieu_id), au lieu de N appels séquentiels
        — utilisée par les vues qui affichent tous les lieux d'un coup
        (Annuaire) pour éviter un N+1 qui la rendrait perceptiblement lente."""
        ...

    @abstractmethod
    def update_lieu_derive_liens(self, tiers_lieu_id: str, lien_externe: Optional[str],
                                  photo_url: Optional[str]) -> None:
        """Met à jour uniquement lien_externe/photo_url (édition manuelle depuis
        l'Annuaire), sans toucher au reste de la donnée dérivée."""
        ...

    @abstractmethod
    def log_llm_call(self, type_appel: str, model: str, tokens_in: int, tokens_out: int,
                      cout_estime: float, tiers_lieu_id: Optional[str] = None) -> None: ...

    # -- historique des conversations Bibliothèque ------------------------

    @abstractmethod
    def save_conversation_bibliotheque(self, conversation: ConversationBibliotheque) -> str:
        """Crée (id vide) ou met à jour (id renseigné) une conversation.
        Renvoie l'id (généré à la création)."""
        ...

    @abstractmethod
    def list_conversations_bibliotheque(self, user_id: str) -> list:
        """Conversations d'un utilisateur, les plus récemment mises à jour
        en premier — pour les lister sans charger le contenu complet de
        chacune (utiliser get_conversation_bibliotheque pour le détail)."""
        ...

    @abstractmethod
    def get_conversation_bibliotheque(self, conversation_id: str) -> Optional[ConversationBibliotheque]: ...

    @abstractmethod
    def delete_conversation_bibliotheque(self, conversation_id: str) -> None: ...

    # -- administration --------------------------------------------------

    @abstractmethod
    def is_admin(self, user_id: str) -> bool: ...

    @abstractmethod
    def add_admin_by_email(self, email: str) -> bool:
        """Ajoute un admin en le résolvant par email. Renvoie False si
        l'utilisateur n'a pas été trouvé (aucun compte avec cet email)."""
        ...

    @abstractmethod
    def list_admin_emails(self) -> list: ...

    @abstractmethod
    def list_users_with_last_login(self) -> list:
        """Comptes connus (email, date de création, dernière connexion,
        admin ou non, compte de service ou non), triés de la connexion la
        plus récente à la plus ancienne (jamais connecté en dernier) —
        utilisé par la section Administration."""
        ...

    @abstractmethod
    def update_portfolio_entry(self, tiers_lieu_id: str, inclus_portfolio: bool,
                                campagne_texte: Optional[str], campagne_objectif: Optional[str],
                                campagne_contact: Optional[str]) -> None: ...

    @abstractmethod
    def list_lieux_portfolio(self) -> list:
        """Lieux avec inclus_portfolio=true, pour la page Portfolio publique."""
        ...

    @abstractmethod
    def save_campagne_prioritaire(self, campagne: CampagnePrioritaire) -> None: ...

    @abstractmethod
    def list_campagnes_prioritaires(self) -> list: ...

    @abstractmethod
    def delete_campagne_prioritaire(self, campagne_id: str) -> None: ...

    @abstractmethod
    def map_user_emails(self, user_ids: list) -> dict:
        """Résout un ensemble d'identifiants utilisateur en emails —
        {user_id: email}. Utilisé pour afficher l'email des répondants
        d'une campagne prioritaire (table admin)."""
        ...

    # -- historique, stewardship, modération --------------------------------------------------

    @abstractmethod
    def list_contributeurs(self, tiers_lieu_id: str) -> list:
        """Tous les contributeurs (tous rôles) d'un lieu, avec leur statut de
        blocage — pour l'écran d'historique/modération d'un lieu."""
        ...

    @abstractmethod
    def set_contributeur_bloque(self, contributeur_id: str, bloque: bool,
                                 bloque_par: Optional[str] = None) -> None:
        """Bloque/débloque un contributeur : ses réponses sont exclues de la
        lecture agrégée (get_answers/get_all_answers_by_contributeur), donc de
        l'enrichissement et de l'Annuaire, sans supprimer la donnée brute
        elle-même (traçabilité conservée)."""
        ...

    @abstractmethod
    def get_historique(self, tiers_lieu_id: str, limite: int = 100) -> list:
        """Journal d'écriture (append-only) des réponses/notes d'un lieu,
        le plus récent en premier — indépendant de `reponses` (qui ne garde
        que la valeur courante par champ)."""
        ...

    @abstractmethod
    def save_litige(self, litige: Litige) -> Litige: ...

    @abstractmethod
    def list_litiges(self, tiers_lieu_id: Optional[str] = None) -> list: ...

    @abstractmethod
    def resoudre_litige(self, litige_id: str) -> None: ...

    def get_active_campagnes_prioritaires(self) -> list:
        """Campagnes dont la fenêtre [date_debut, date_fin] couvre maintenant.
        Implémentation par défaut (filtre en Python) commune aux deux stores —
        pas besoin de la redéfinir sauf optimisation spécifique."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        actives = []
        for c in self.list_campagnes_prioritaires():
            debut = _parse_dt(c.date_debut)
            fin = _parse_dt(c.date_fin)
            if debut and fin and debut <= now <= fin:
                actives.append(c)
        return actives


def _parse_dt(value):
    from datetime import datetime, timezone

    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None
