"""Connexion unique depuis troistiers.space : jeton ChangeTheGame vérifié par Space2,
ticket à usage unique et de courte durée, session Space2 ouverte sans code.
Sans réseau : ChangeTheGame et Supabase sont simulés.

Usage : python3 -m tests.test_sso
"""

import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src import sso
from src.api import app as api_app

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


class Rep:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data or {}

    def json(self):
        return self._data


def faux_ctg(jetons_valides):
    appels = []

    def get(url, headers):
        appels.append((url, headers))
        jeton = headers["Authorization"].removeprefix("Bearer ")
        if jeton in jetons_valides:
            return Rep(200, {"id": "ctg-123", "email": jetons_valides[jeton]})
        return Rep(401)
    return get, appels


def main():
    os.environ["CTG_SUPABASE_URL"] = "https://ctg.example.supabase.co/"
    os.environ["CTG_SUPABASE_ANON_KEY"] = "cle-anon-ctg"

    # 1. Vérification du jeton auprès de ChangeTheGame
    get, appels = faux_ctg({"jeton-valide-de-pa": "PA@Exemple.org"})
    email, ctg_id = sso.verifier_jeton_ctg("jeton-valide-de-pa", http_get=get)
    check("jeton valide → email (minuscules) et id ctg", (email, ctg_id) == ("pa@exemple.org", "ctg-123"))
    check("appel à l'Auth de ctg avec la clé anon",
          appels[0][0] == "https://ctg.example.supabase.co/auth/v1/user" and appels[0][1]["apikey"] == "cle-anon-ctg")
    for jeton in ("jeton-invente", ""):
        try:
            sso.verifier_jeton_ctg(jeton, http_get=get)
            check(f"jeton refusé : {jeton!r}", False)
        except sso.JetonInvalide:
            check(f"jeton refusé : {jeton!r}", True)
    del os.environ["CTG_SUPABASE_ANON_KEY"]
    try:
        sso.verifier_jeton_ctg("jeton-valide-de-pa", http_get=get)
        check("sans configuration ctg : refus", False)
    except sso.JetonInvalide:
        check("sans configuration ctg : refus", True)
    os.environ["CTG_SUPABASE_ANON_KEY"] = "cle-anon-ctg"

    # 2. Tickets : usage unique, durée limitée, seul le hash est stocké
    t = sso.TicketsMemoire()
    ticket = sso.creer_ticket(t, "PA@exemple.org", "ctg-123")
    check("le ticket en clair n'est pas stocké", ticket not in str(t.lignes))
    check("ticket valable → email", sso.consommer_ticket(t, ticket) == "pa@exemple.org")
    check("ticket déjà utilisé → refus", sso.consommer_ticket(t, ticket) is None)
    vieux = sso.creer_ticket(t, "pa@exemple.org", maintenant=datetime.now(timezone.utc) - timedelta(seconds=sso.TTL_TICKET + 5))
    check("ticket expiré → refus", sso.consommer_ticket(t, vieux) is None)
    check("ticket inventé → refus", sso.consommer_ticket(t, "n-importe-quoi") is None)
    check("deux tickets différents à chaque fois", sso.creer_ticket(t, "a@b.c") != sso.creer_ticket(t, "a@b.c"))

    # 3. Ouverture de la session Space2 sans code
    traces = []

    class Admin:
        def __init__(self, existe):
            self.existe = existe
            self.auth = types.SimpleNamespace(admin=self)

        def generate_link(self, params):
            traces.append(("lien", params["email"]))
            if not self.existe:
                raise RuntimeError("User not found")
            return types.SimpleNamespace(properties=types.SimpleNamespace(hashed_token="h4sh"))

        def create_user(self, params):
            traces.append(("creation", params["email"], params["email_confirm"]))
            self.existe = True

    class App:
        def __init__(self):
            self.auth = self

        def verify_otp(self, params):
            traces.append(("verif", params["token_hash"], params["type"]))
            return types.SimpleNamespace(user=types.SimpleNamespace(id="s2-user", email="pa@exemple.org"), session=None)

    r = sso.ouvrir_session_space2(Admin(existe=True), App(), "pa@exemple.org")
    check("compte existant : lien vérifié aussitôt", r.user.id == "s2-user" and ("verif", "h4sh", "email") in traces)
    traces.clear()
    sso.ouvrir_session_space2(Admin(existe=False), App(), "nouveau@exemple.org")
    check("compte inexistant : créé (email confirmé) puis connecté",
          ("creation", "nouveau@exemple.org", True) in traces and traces[-1][0] == "verif")

    # 4. Route POST /sso/ticket
    os.environ["SITE_READ_SECRET"] = "cle-site"
    os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"
    memoire = sso.TicketsMemoire()
    sso.tickets_du_store = lambda store: memoire
    api_app.get_store = lambda: None
    api_app._appels_site.clear()
    ancien = sso.verifier_jeton_ctg
    sso.verifier_jeton_ctg = lambda jeton: ("pa@exemple.org", "ctg-123") if jeton == "jeton-valide-de-pa" else (_ for _ in ()).throw(sso.JetonInvalide("non"))
    http = TestClient(api_app.app)
    site = {"X-Webhook-Secret": "cle-site"}
    r = http.post("/sso/ticket", json={"ctg_token": "jeton-valide-de-pa"}, headers=site)
    check("route : jeton valide → ticket", r.status_code == 200 and sso.consommer_ticket(memoire, r.json()["ticket"]) == "pa@exemple.org")
    check("route : jeton refusé par ctg → 401",
          http.post("/sso/ticket", json={"ctg_token": "jeton-invente-xx"}, headers=site).status_code == 401)
    check("route : sans clé du site → 401",
          http.post("/sso/ticket", json={"ctg_token": "jeton-valide-de-pa"}).status_code == 401)
    sso.verifier_jeton_ctg = ancien

    for k in ("CTG_SUPABASE_URL", "CTG_SUPABASE_ANON_KEY", "SITE_READ_SECRET", "CTG_WEBHOOK_SECRET"):
        os.environ.pop(k, None)
    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
