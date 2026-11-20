"""Connexion unique depuis troistiers.space (sans second code par e-mail).

Parcours :
1. le site appelle POST /sso/ticket (clé du site) avec le jeton ChangeTheGame
   de la personne connectée ;
2. l'API vérifie CE jeton auprès de ChangeTheGame (verifier_jeton_ctg) : c'est
   ChangeTheGame qui atteste l'email, pas le site — la clé du site seule ne
   permet de connecter personne ;
3. l'API crée un ticket aléatoire, à usage unique, valable TTL_TICKET secondes
   (seul son hash est stocké, table sso_tickets) ;
4. l'app Streamlit reçoit ?ticket=..., le consomme (une seule fois) et ouvre une
   session Supabase de Space2 pour le même email (ouvrir_session_space2).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

TTL_TICKET = 120


class JetonInvalide(Exception):
    pass


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def verifier_jeton_ctg(jeton: str, http_get=None) -> tuple[str, str]:
    """(email, id ChangeTheGame) du titulaire du jeton, vérifié auprès de l'Auth de
    ChangeTheGame (GET <CTG_SUPABASE_URL>/auth/v1/user). Lève JetonInvalide sinon."""
    url = os.environ.get("CTG_SUPABASE_URL", "").rstrip("/")
    cle = os.environ.get("CTG_SUPABASE_ANON_KEY", "")
    if not url or not cle:
        raise JetonInvalide("connexion ChangeTheGame non configurée (CTG_SUPABASE_URL, CTG_SUPABASE_ANON_KEY)")
    if not jeton or len(jeton) > 8000:
        raise JetonInvalide("jeton absent")
    if http_get is None:
        import httpx
        http_get = lambda u, headers: httpx.get(u, headers=headers, timeout=10.0)  # noqa: E731
    r = http_get(f"{url}/auth/v1/user", headers={"apikey": cle, "Authorization": f"Bearer {jeton}"})
    if r.status_code != 200:
        raise JetonInvalide(f"jeton refusé par ChangeTheGame ({r.status_code})")
    data = r.json()
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise JetonInvalide("aucun email vérifiable pour ce compte")
    return email, str(data.get("id") or "")


class Tickets(Protocol):
    def inserer(self, ligne: dict) -> None: ...
    def consommer(self, hash_: str, maintenant: str) -> Optional[dict]: ...


class TicketsSupabase:
    """Table sso_tickets, via le client service_role."""

    def __init__(self, client):
        self.client = client

    def inserer(self, ligne: dict) -> None:
        self.client.table("sso_tickets").insert(ligne).execute()

    def consommer(self, hash_: str, maintenant: str) -> Optional[dict]:
        # Mise à jour conditionnelle : seul le premier appel trouve utilise_le vide.
        r = (self.client.table("sso_tickets").update({"utilise_le": maintenant})
             .eq("hash", hash_).is_("utilise_le", "null").gt("expire_le", maintenant).execute())
        return (r.data or [None])[0]


class TicketsMemoire:
    """Pour les tests et le développement sans Supabase."""

    def __init__(self):
        self.lignes: dict = {}

    def inserer(self, ligne: dict) -> None:
        self.lignes[ligne["hash"]] = dict(ligne)

    def consommer(self, hash_: str, maintenant: str) -> Optional[dict]:
        l = self.lignes.get(hash_)
        if not l or l.get("utilise_le") or l["expire_le"] <= maintenant:
            return None
        l["utilise_le"] = maintenant
        return dict(l)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def creer_ticket(tickets: Tickets, email: str, ctg_user_id: str = "",
                 maintenant: Optional[datetime] = None) -> str:
    maintenant = maintenant or datetime.now(timezone.utc)
    ticket = secrets.token_urlsafe(32)
    tickets.inserer({
        "hash": _hash(ticket), "email": email.strip().lower(), "ctg_user_id": ctg_user_id or None,
        "expire_le": _iso(maintenant + timedelta(seconds=TTL_TICKET)),
    })
    return ticket


def consommer_ticket(tickets: Tickets, ticket: str, maintenant: Optional[datetime] = None) -> Optional[str]:
    """Email du ticket s'il est valable (existant, non expiré, jamais utilisé) ; le ticket devient inutilisable."""
    if not ticket or len(ticket) > 200:
        return None
    ligne = tickets.consommer(_hash(ticket), _iso(maintenant or datetime.now(timezone.utc)))
    return ligne["email"] if ligne else None


def ouvrir_session_space2(client_admin, client_app, email: str):
    """Ouvre, dans le client Supabase de l'app (client_app), une session pour `email`
    sans lui envoyer de code : le serveur génère un lien de connexion (clé service_role)
    et le vérifie aussitôt. Crée le compte Space2 s'il n'existe pas encore.
    Renvoie la réponse de verify_otp (user, session)."""
    def lien():
        return client_admin.auth.admin.generate_link({"type": "magiclink", "email": email})

    try:
        r = lien()
    except Exception:
        # Compte Space2 inexistant : on le crée, email déjà vérifié par ChangeTheGame.
        client_admin.auth.admin.create_user({"email": email, "email_confirm": True})
        r = lien()
    hashed = r.properties.hashed_token
    try:
        return client_app.auth.verify_otp({"token_hash": hashed, "type": "email"})
    except Exception:
        return client_app.auth.verify_otp({"token_hash": hashed, "type": "magiclink"})


_tickets_dev = TicketsMemoire()


def tickets_du_store(store) -> Tickets:
    """Table sso_tickets si le store est Supabase (client service_role) ; mémoire en développement."""
    client = getattr(store, "client", None)
    return TicketsSupabase(client) if client is not None and hasattr(client, "table") else _tickets_dev
