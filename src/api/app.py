"""API publique de Space2 pour Changethegame (et autres plateformes).

Lancement : `uvicorn src.api.app:app --host 0.0.0.0 --port $PORT`
Variables : CTG_WEBHOOK_SECRET (obligatoire — sans lui l'API refuse tout),
ANTHROPIC_API_KEY, SUPABASE_URL + SUPABASE_SERVICE_KEY (sinon SQLite local),
API_ASK_MODEL (optionnel, défaut claude-haiku-4-5)."""

from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

load_dotenv()

from ..db.factory import get_admin_store  # noqa: E402
from .ask_agent import MODELE_DEFAUT, AskAgent  # noqa: E402
from .public_data import DonneesPubliques  # noqa: E402

MAX_MESSAGES = 20
MAX_CARACTERES = 4000
RATE_LIMIT_PAR_MINUTE = 30

app = FastAPI(title="Space2 API", docs_url=None, redoc_url=None, openapi_url=None)

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
            store = get_admin_store()
            _agent = AskAgent(DonneesPubliques(store), store=store,
                              model=os.environ.get("API_ASK_MODEL", MODELE_DEFAUT))
        return _agent


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(verifier_secret)])
def ask(requete: AskRequest) -> AskResponse:
    limiter_debit()
    try:
        contenu = get_agent().ask([m.model_dump() for m in requete.messages], requete.context)
    except Exception:
        raise HTTPException(status_code=502, detail="upstream error")
    return AskResponse(content=contenu)
