"""POST /ask depuis le site Trois-Tiers : clé du site acceptée, agent du site distinct
(public par défaut, complet seulement si SITE_ASK_FULL_ACCESS=true), plafond de débit
séparé de celui de ctg. Sans réseau : agents factices.

Usage : python3 -m tests.test_api_ask_site
"""

import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api import app as api_app
from src.api import ask_agent

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


class FauxAgent:
    def __init__(self, nom):
        self.nom = nom

    def ask(self, messages, context=None):
        return f"réponse de l'agent {self.nom}"


def main():
    os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"
    os.environ["SITE_READ_SECRET"] = "cle-site"
    ctg, site = {"X-Webhook-Secret": "secret-ctg"}, {"X-Webhook-Secret": "cle-site"}
    corps = {"messages": [{"role": "user", "content": "Combien de lieux nourriciers en Wallonie ?"}]}

    api_app._agent = FauxAgent("ctg")
    api_app._agent_site = FauxAgent("site")
    api_app._appels.clear()
    api_app._appels_site.clear()
    http = TestClient(api_app.app)

    r = http.post("/ask", json=corps, headers=site)
    check("clé du site acceptée sur /ask", r.status_code == 200)
    check("le site reçoit SON agent, pas celui de ctg", r.json().get("content") == "réponse de l'agent site")
    check("ctg garde son agent", http.post("/ask", json=corps, headers=ctg).json().get("content") == "réponse de l'agent ctg")
    check("sans clé → 401", http.post("/ask", json=corps).status_code == 401)
    check("mauvaise clé → 401", http.post("/ask", json=corps, headers={"X-Webhook-Secret": "x"}).status_code == 401)

    # Plafonds séparés : le site sature le sien sans toucher à celui de ctg.
    api_app._appels.clear()
    api_app._appels_site.clear()
    codes = [http.post("/ask", json=corps, headers=site).status_code for _ in range(api_app.RATE_LIMIT_SITE_PAR_MINUTE + 1)]
    check("plafond du site atteint → 429", codes[-1] == 429 and codes.count(200) == api_app.RATE_LIMIT_SITE_PAR_MINUTE)
    check("ctg n'est pas bloqué par le plafond du site", http.post("/ask", json=corps, headers=ctg).status_code == 200)

    # Mode de l'agent du site : public par défaut, complet seulement si demandé.
    os.environ.pop("SITE_ASK_FULL_ACCESS", None)
    check("agent du site public par défaut", ask_agent.acces_complet_site() is False)
    os.environ["SITE_ASK_FULL_ACCESS"] = "true"
    check("SITE_ASK_FULL_ACCESS=true ouvre le mode complet", ask_agent.acces_complet_site() is True)
    os.environ["SITE_ASK_FULL_ACCESS"] = "non"
    check("toute autre valeur reste public", ask_agent.acces_complet_site() is False)

    vus = []
    api_app._agent_site = None
    ancien = api_app.creer_agent
    api_app.creer_agent = lambda store, model=None, complet=None: vus.append(complet) or FauxAgent("site-cree")
    api_app.get_admin_store = lambda: None
    os.environ.pop("SITE_ASK_FULL_ACCESS", None)
    api_app._appels_site.clear()
    http.post("/ask", json=corps, headers=site)
    check("l'agent du site est créé en mode public (complet=False)", vus == [False])
    api_app.creer_agent = ancien

    for k in ("CTG_WEBHOOK_SECRET", "SITE_READ_SECRET", "SITE_ASK_FULL_ACCESS"):
        os.environ.pop(k, None)
    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
