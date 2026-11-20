"""Entretien de collecte mené depuis troistiers.space (le site affiche la conversation).

Même agent que l'onglet Entretien de l'app (CollecteAgent + CollecteToolHandler) : les réponses
vont dans les mêmes tables, attribuées à la personne et à son rôle dans le lieu.

Identité : chaque appel porte, en plus de la clé du site, le jeton ChangeTheGame de la personne
(en-tête X-CTG-Token), vérifié ICI auprès de ChangeTheGame (src/sso.verifier_jeton_ctg, résultat
gardé quelques minutes). La clé du site seule ne permet d'agir au nom de personne. L'email ainsi
attesté est rattaché au compte Space2 du même email (créé si besoin).

La conversation est enregistrée après chaque tour (table entretiens_site), et seule la personne
qui l'a ouverte peut la reprendre.
"""

from __future__ import annotations

import hashlib
import threading
import time
import unicodedata
from typing import Callable, Optional

from src import sso

# Mêmes libellés que l'app (src/app.py, ROLE_LABELS) : l'agent s'en sert pour personnaliser l'ouverture.
ROLE_LABELS = {
    "fondateur": "Fondateur·rice / porteur de projet",
    "equipe": "Équipe opérationnelle",
    "partenaire": "Partie prenante externe",
    "usager": "Usager régulier",
    "steward": "Steward (je continue à nourrir ce lieu)",
    "autre": "Autre",
}
ROLES = tuple(ROLE_LABELS)
MODES = ("histoire", "besoins", "campagne")
TTL_IDENTITE = 300

_identites: dict = {}
_utilisateurs: dict = {}
_verrou = threading.Lock()


class AccesRefuse(Exception):
    pass


class Introuvable(Exception):
    pass


# -- Identité -----------------------------------------------------------------

def identite(jeton: str, verifier=None) -> str:
    """Email attesté par ChangeTheGame pour ce jeton (résultat gardé TTL_IDENTITE secondes)."""
    cle = hashlib.sha256((jeton or "").encode()).hexdigest()
    with _verrou:
        trouve = _identites.get(cle)
        if trouve and trouve[1] > time.monotonic():
            return trouve[0]
    email, _ = (verifier or sso.verifier_jeton_ctg)(jeton)
    with _verrou:
        _identites[cle] = (email, time.monotonic() + TTL_IDENTITE)
    return email


def utilisateur_space2(store, email: str) -> str:
    """Identifiant du compte Space2 pour cet email (créé si besoin, email confirmé).
    Sans Supabase (développement), l'email sert d'identifiant, comme dans l'app."""
    client = getattr(store, "client", None)
    if client is None or not hasattr(client, "auth"):
        return email
    with _verrou:
        if email in _utilisateurs:
            return _utilisateurs[email]

    def lien():
        return client.auth.admin.generate_link({"type": "magiclink", "email": email})

    try:
        r = lien()
    except Exception:
        client.auth.admin.create_user({"email": email, "email_confirm": True})
        r = lien()
    uid = str(r.user.id)
    with _verrou:
        _utilisateurs[email] = uid
    return uid


# -- Conversations --------------------------------------------------------------

class ConversationsSupabase:
    def __init__(self, client):
        self.client = client

    def creer(self, ligne: dict) -> dict:
        return self.client.table("entretiens_site").insert(ligne).execute().data[0]

    def lire(self, conv_id: str) -> Optional[dict]:
        r = self.client.table("entretiens_site").select("*").eq("id", conv_id).limit(1).execute()
        return (r.data or [None])[0]

    def maj(self, conv_id: str, champs: dict) -> None:
        from datetime import datetime, timezone
        champs = {**champs, "maj_le": datetime.now(timezone.utc).isoformat()}
        self.client.table("entretiens_site").update(champs).eq("id", conv_id).execute()

    def lister(self, user_id: str) -> list:
        r = (self.client.table("entretiens_site").select("id, tiers_lieu_id, role, mode, campagne_id, maj_le")
             .eq("user_id", user_id).order("maj_le", desc=True).limit(20).execute())
        return r.data or []


class ConversationsMemoire:
    def __init__(self):
        self.lignes: dict = {}
        self.n = 0

    def creer(self, ligne: dict) -> dict:
        self.n += 1
        ligne = {"id": f"conv-{self.n}", "maj_le": f"{self.n:06d}", **ligne}
        self.lignes[ligne["id"]] = ligne
        return dict(ligne)

    def lire(self, conv_id: str) -> Optional[dict]:
        l = self.lignes.get(conv_id)
        return dict(l) if l else None

    def maj(self, conv_id: str, champs: dict) -> None:
        self.n += 1
        self.lignes[conv_id].update(champs, maj_le=f"{self.n:06d}")

    def lister(self, user_id: str) -> list:
        return sorted((dict(l) for l in self.lignes.values() if l["user_id"] == user_id),
                      key=lambda l: l["maj_le"], reverse=True)


_conversations_dev = ConversationsMemoire()


def conversations_du_store(store):
    client = getattr(store, "client", None)
    return ConversationsSupabase(client) if client is not None and hasattr(client, "table") else _conversations_dev


# -- Lieux ----------------------------------------------------------------------

def _norm(t: str) -> str:
    return unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().lower().strip()


_cache_lieux: dict = {}


def chercher_lieux(store, q: str, limite: int = 20) -> list:
    """Lieux dont le nom contient `q` (sans accents ni casse) — pour choisir son lieu."""
    q = _norm(q)
    if len(q) < 2:
        return []
    with _verrou:
        cache = _cache_lieux.get("v")
        if not cache or cache[1] < time.monotonic():
            cache = (store.list_tiers_lieux(), time.monotonic() + 300)
            _cache_lieux["v"] = cache
    trouves = [l for l in cache[0] if q in _norm(l.nom)]
    trouves.sort(key=lambda l: (not _norm(l.nom).startswith(q), l.nom.lower()))
    return [{"id": l.id, "nom": l.nom, "commune": getattr(l, "commune", None), "region": l.region, "pays": l.pays}
            for l in trouves[:limite]]


def _lieu_par_id(store, lieu_id: str):
    with _verrou:
        cache = _cache_lieux.get("v")
    lieux = cache[0] if cache else store.list_tiers_lieux()
    lieu = next((l for l in lieux if l.id == lieu_id), None)
    if lieu is None:
        lieu = next((l for l in store.list_tiers_lieux() if l.id == lieu_id), None)
    return lieu


# -- Agent ----------------------------------------------------------------------

def _agent_par_defaut(store, conv: dict, user_id: str):
    from src.agent.collecte_agent import CollecteAgent
    from src.agent.collecte_tools import CollecteToolHandler
    from src.questionnaire.schema import Role
    session = store.get_or_start_session(conv["tiers_lieu_id"], conv["contributeur_id"])
    handler = CollecteToolHandler(store, conv["tiers_lieu_id"], conv["contributeur_id"], session, Role(conv["role"]),
                                  mode_entretien=conv["mode"], campagne_id=conv.get("campagne_id"))
    agent = CollecteAgent(handler, store=store, tiers_lieu_id=conv["tiers_lieu_id"], user_id=user_id)
    agent.messages = list(conv.get("messages") or [])
    return agent


def _completion(agent) -> Optional[dict]:
    try:
        return agent.tool_handler.campagne_completion()
    except Exception:
        return None


def _vue(conv: dict, nom_lieu: Optional[str] = None, completion: Optional[dict] = None) -> dict:
    return {"id": conv["id"], "tiers_lieu_id": conv["tiers_lieu_id"], "nom_lieu": nom_lieu, "role": conv["role"],
            "mode": conv["mode"], "campagne_id": conv.get("campagne_id"),
            "historique": conv.get("historique") or [], "completion": completion}


def ouvrir(store, email: str, user_id: str, *, lieu_id: Optional[str] = None, nouveau_lieu: Optional[str] = None,
           role: str, mode: str = "histoire", campagne: Optional[str] = None,
           fabrique_agent: Callable = _agent_par_defaut) -> dict:
    """Ouvre un entretien pour un lieu existant (lieu_id) ou nouveau (nouveau_lieu = son nom)."""
    from src.agent.collecte_agent import opening_message
    from src.questionnaire.resolver import campagne_completion_stats

    if role not in ROLES:
        raise ValueError("rôle inconnu")
    if mode not in MODES:
        raise ValueError("mode inconnu")
    if lieu_id:
        lieu = _lieu_par_id(store, lieu_id)
        if lieu is None:
            raise Introuvable("lieu")
    elif nouveau_lieu and 2 <= len(nouveau_lieu.strip()) <= 200:
        lieu = store.get_or_create_tiers_lieu(user_id, nouveau_lieu.strip())
        with _verrou:
            _cache_lieux.pop("v", None)
    else:
        raise ValueError("lieu manquant")

    campagne_choisie = None
    if mode == "campagne":
        actives = store.get_active_campagnes_prioritaires()
        campagne_choisie = next((c for c in actives if campagne in (c.code, c.id)), None) if campagne else None
        if campagne_choisie is None:
            raise Introuvable("campagne")

    contributeur = store.get_or_create_contributeur(user_id, lieu.id, role)
    if getattr(contributeur, "bloque", False):
        raise AccesRefuse("contributeur bloqué")
    reponses = store.get_answers(lieu.id, contributeur.id)
    if reponses.get("nom_lieu") is None:
        store.save_answer(lieu.id, contributeur.id, "nom_lieu", lieu.nom)

    depot = conversations_du_store(store)
    conv = depot.creer({
        "user_id": user_id, "email": email, "tiers_lieu_id": lieu.id, "contributeur_id": contributeur.id,
        "role": role, "mode": mode, "campagne_id": campagne_choisie.id if campagne_choisie else None,
        "messages": [], "historique": [],
    })
    agent = fabrique_agent(store, conv, user_id)
    ouverture = agent.send(opening_message(
        store, lieu.id, nom_lieu=lieu.nom, contributeur_id=contributeur.id, role_label=ROLE_LABELS[role],
        mode_entretien=mode,
        campagne_titre=campagne_choisie.titre if campagne_choisie else None,
        campagne_progression=(campagne_completion_stats(reponses, campagne_choisie.champ_ids)
                              if campagne_choisie else None),
    ))
    historique = [{"role": "assistant", "texte": ouverture}]
    depot.maj(conv["id"], {"messages": agent.messages, "historique": historique})
    conv.update(messages=agent.messages, historique=historique)
    return _vue(conv, lieu.nom, _completion(agent))


def _conversation_a_soi(store, user_id: str, conv_id: str) -> dict:
    conv = conversations_du_store(store).lire(conv_id)
    if not conv or conv["user_id"] != user_id:
        raise Introuvable("conversation")
    return conv


def lire(store, user_id: str, conv_id: str) -> dict:
    conv = _conversation_a_soi(store, user_id, conv_id)
    lieu = _lieu_par_id(store, conv["tiers_lieu_id"])
    return _vue(conv, lieu.nom if lieu else None)


def repondre(store, user_id: str, conv_id: str, texte: str, fabrique_agent: Callable = _agent_par_defaut) -> dict:
    texte = (texte or "").strip()
    if not texte or len(texte) > 4000:
        raise ValueError("message vide ou trop long")
    conv = _conversation_a_soi(store, user_id, conv_id)
    agent = fabrique_agent(store, conv, user_id)
    reponse = agent.send(texte)
    historique = list(conv.get("historique") or []) + [{"role": "user", "texte": texte},
                                                      {"role": "assistant", "texte": reponse}]
    conversations_du_store(store).maj(conv_id, {"messages": agent.messages, "historique": historique})
    conv.update(historique=historique)
    lieu = _lieu_par_id(store, conv["tiers_lieu_id"])
    return _vue(conv, lieu.nom if lieu else None, _completion(agent))


def lister(store, user_id: str) -> list:
    sortie = []
    for c in conversations_du_store(store).lister(user_id):
        lieu = _lieu_par_id(store, c["tiers_lieu_id"])
        sortie.append({"id": c["id"], "nom_lieu": lieu.nom if lieu else None, "role": c["role"], "mode": c["mode"],
                       "campagne_id": c.get("campagne_id"), "maj_le": c.get("maj_le")})
    return sortie
