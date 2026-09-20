"""API de Space2 pour Changethegame (et autres plateformes).

  GET  /manifest                  fiche de l'agent (publique, sans secret)
  POST /ask                       questions-réponses sur les données publiques
  GET  /lieux[?updated_since=]    flux des lieux (synthèse publique) pour ctg
  POST /lieux/{space2_id}/link    ctg associe son entité à un lieu
  POST /events                    événements publics ctg (RAG de Space2)
  PUT  /access                    membres de guilde / loueurs ayant accès

Lancement : `uvicorn src.api.app:app --host 0.0.0.0 --port $PORT`
Variables : CTG_WEBHOOK_SECRET (obligatoire — sans lui l'API refuse tout),
ANTHROPIC_API_KEY, SUPABASE_URL + SUPABASE_SERVICE_KEY (sinon SQLite local),
API_ASK_MODEL (optionnel, défaut claude-haiku-4-5)."""

from __future__ import annotations

import hmac
import os
import threading
import time
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

load_dotenv()

from ..db.factory import get_admin_store  # noqa: E402
from .ask_agent import MODELE_DEFAUT, acces_complet_actif, creer_agent  # noqa: E402
from .manifest import construire_manifest  # noqa: E402
from .public_data import flux_lieux  # noqa: E402

MAX_MESSAGES = 20
MAX_CARACTERES = 4000
RATE_LIMIT_PAR_MINUTE = 30

def _prechauffer() -> None:
    # Construit l'index sémantique des profils au démarrage : évite que la
    # première question paie le calcul des embeddings dans son budget de 25 s.
    try:
        get_agent().warmup()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_prechauffer, daemon=True).start()
    yield


app = FastAPI(title="Space2 API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

_agent: Optional[AskAgent] = None
_agent_lock = threading.Lock()
_appels: list = []
_appels_lock = threading.Lock()


class Message(BaseModel):
    role: str
    content: str = Field(max_length=MAX_CARACTERES)

    @field_validator("role")
    @classmethod
    def role_valide(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError("role doit valoir 'user' ou 'assistant'")
        return v


class AskRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)
    context: Optional[dict[str, Any]] = None

    @field_validator("messages")
    @classmethod
    def finit_par_user(cls, v: list) -> list:
        if v[-1].role != "user":
            raise ValueError("le dernier message doit être de rôle 'user'")
        return v


class AskResponse(BaseModel):
    content: str


def verifier_secret(x_webhook_secret: Optional[str] = Header(default=None)) -> None:
    attendu = os.environ.get("CTG_WEBHOOK_SECRET", "")
    # Fail closed : secret non configuré côté serveur = tout refuser.
    if not attendu or not x_webhook_secret or not hmac.compare_digest(
            x_webhook_secret.encode(), attendu.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


def limiter_debit() -> None:
    maintenant = time.monotonic()
    with _appels_lock:
        _appels[:] = [t for t in _appels if maintenant - t < 60]
        if len(_appels) >= RATE_LIMIT_PAR_MINUTE:
            raise HTTPException(status_code=429, detail="rate limit")
        _appels.append(maintenant)


def get_agent() -> AskAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = creer_agent(get_admin_store(), model=os.environ.get("API_ASK_MODEL", MODELE_DEFAUT))
        return _agent


def get_store():
    return get_admin_store()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/manifest")
def manifest() -> dict:
    return construire_manifest(acces_complet_actif())


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(verifier_secret)])
def ask(requete: AskRequest) -> AskResponse:
    limiter_debit()
    try:
        contenu = get_agent().ask([m.model_dump() for m in requete.messages], requete.context)
    except Exception:
        raise HTTPException(status_code=502, detail="upstream error")
    return AskResponse(content=contenu)


# -- Flux lieux ------------------------------------------------------------

@app.get("/lieux", dependencies=[Depends(verifier_secret)])
def lieux(updated_since: Optional[str] = None) -> dict:
    return {"lieux": flux_lieux(get_store(), updated_since)}


class LienCtg(BaseModel):
    ctg_entity_id: str = Field(min_length=1, max_length=200)


@app.post("/lieux/{space2_id}/link", dependencies=[Depends(verifier_secret)])
def lier_lieu(space2_id: str, lien: LienCtg) -> dict:
    store = get_store()
    lieux_ = {lieu.id: lieu for lieu in store.list_tiers_lieux()}
    if space2_id not in lieux_:
        raise HTTPException(status_code=404, detail="lieu inconnu")
    deja = next((l for l in lieux_.values() if l.ctg_entity_id == lien.ctg_entity_id), None)
    if deja and deja.id != space2_id:
        raise HTTPException(status_code=409, detail="ctg_entity_id déjà lié à un autre lieu")
    store.update_tiers_lieu(space2_id, ctg_entity_id=lien.ctg_entity_id)
    return {"space2_id": space2_id, "ctg_entity_id": lien.ctg_entity_id}


# -- Événements ctg -> RAG ---------------------------------------------------

class EvenementCtg(BaseModel):
    ctg_event_id: str = Field(min_length=1, max_length=200)
    space2_id: Optional[str] = Field(default=None, max_length=100)
    ctg_entity_id: Optional[str] = Field(default=None, max_length=200)
    type: Literal["membre", "discussion", "mise_a_jour", "quete", "besoin"]
    titre: Optional[str] = Field(default=None, max_length=300)
    texte: Optional[str] = Field(default=None, max_length=MAX_CARACTERES)
    url: Optional[str] = Field(default=None, max_length=500)
    occurred_at: Optional[str] = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def url_http(cls, v):
        if v is not None and not re.match(r"^https?://", v):
            raise ValueError("url doit commencer par http(s)://")
        return v

    @field_validator("occurred_at")
    @classmethod
    def date_iso(cls, v):
        if v is not None:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class LotEvenements(BaseModel):
    events: list[EvenementCtg] = Field(min_length=1, max_length=100)


@app.post("/events", dependencies=[Depends(verifier_secret)])
def evenements(lot: LotEvenements) -> dict:
    store = get_store()
    tous = store.list_tiers_lieux()
    par_id = {l.id: l for l in tous}
    par_ctg = {l.ctg_entity_id: l for l in tous if l.ctg_entity_id}
    acceptes, rejetes = 0, []
    for ev in lot.events:
        lieu = par_id.get(ev.space2_id) if ev.space2_id else par_ctg.get(ev.ctg_entity_id)
        if lieu is None:
            rejetes.append({"ctg_event_id": ev.ctg_event_id, "reason": "lieu inconnu ou non lié"})
            continue
        store.add_evenement_ctg(lieu.id, ev.ctg_event_id, ev.type, ev.titre, ev.texte, ev.url,
                                ev.occurred_at)
        acceptes += 1
    return {"accepted": acceptes, "rejected": rejetes}


# -- Accès externes ------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class MembreAcces(BaseModel):
    email: str = Field(max_length=320)
    statut: Literal["actif", "revoque"] = "actif"
    guilde_id: Optional[str] = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def email_valide(cls, v: str) -> str:
        if not _EMAIL.match(v.strip()):
            raise ValueError("email invalide")
        return v.strip().lower()


class LotAcces(BaseModel):
    members: list[MembreAcces] = Field(min_length=1, max_length=500)


@app.put("/access", dependencies=[Depends(verifier_secret)])
def acces(lot: LotAcces) -> dict:
    store = get_store()
    for m in lot.members:
        store.upsert_acces_externe(m.email, "ctg", m.guilde_id, m.statut)
    return {"updated": len(lot.members)}
