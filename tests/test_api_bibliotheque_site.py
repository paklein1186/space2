"""Bibliothèque menée depuis troistiers.space : profondeur, historique partagé avec l'app,
contributions des membres (ajout, recherche par l'agent, retrait), garde-fous (propriété des
conversations, adresses internes refusées). Base SQLite temporaire, Voyage et Claude simulés.

Usage : python3 -m tests.test_api_bibliotheque_site
"""

import base64
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src import sso
from src.agent import embeddings as emb_mod
from src.agent import vectorstore as vs_mod
from src.api import app as api_app
from src.api import bibliotheque_api as bib
from src.api import entretien_api as ent
from src.db.sqlite_store import SqliteStore

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


class FauxEmbedder:
    def _v(self, t):
        mots = set(t.lower().split())
        return [float(("compost" in mots) or ("compostage" in mots)), float("financement" in mots), 1.0]

    def embed_documents(self, textes):
        return [self._v(t) for t in textes]

    def embed_query(self, t):
        return self._v(t)


class FauxMagasin:
    def __init__(self):
        self.docs = {}
        self.collection = self   # supprimer_ids passe par collection.delete hors Supabase

    def upsert(self, ids, embeddings, documents, metadatas):
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            self.docs[i] = (e, d, m)

    def query(self, embedding, top_k=6, where=None):
        hits = [{"text": d, "metadata": m, "distance": sum((a - b) ** 2 for a, b in zip(e, embedding))}
                for e, d, m in self.docs.values() if not where or m.get("doc_type") == where["doc_type"]]
        return sorted(hits, key=lambda h: h["distance"])[:top_k]

    def lister_documents(self, where):
        return [{"id": i, "text": d, "metadata": m} for i, (e, d, m) in self.docs.items()
                if m.get("doc_type") == where["doc_type"]]

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)


class FauxAgent:
    appels = []

    def __init__(self, profondeur):
        self.profondeur = profondeur

    def ask(self, messages, context=None):
        FauxAgent.appels.append((self.profondeur, [dict(m) for m in messages]))
        return f"Réponse {self.profondeur} n°{len(FauxAgent.appels)}"


class Session:
    """Faux client HTTP : une redirection puis une page HTML."""
    class R:
        def __init__(self, code, headers, corps=b""):
            self.status_code, self.headers, self.corps = code, headers, corps
            self.is_redirect = code in (301, 302)

        def iter_content(self, n):
            yield self.corps

        def raise_for_status(self):
            pass

        def close(self):
            pass

    def get(self, url, **k):
        if url.endswith("/ancien"):
            return self.R(302, {"location": "/page"})
        return self.R(200, {"content-type": "text/html; charset=utf-8"},
                      "<html><nav>menu</nav><p>Le compostage partagé au Tiers-lieu des Prés : 40 foyers.</p></html>".encode())


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "b.sqlite3"))
        magasin = FauxMagasin()
        api_app.get_store = lambda: store
        vs_mod.get_vectorstore = lambda: magasin
        emb_mod.VoyageEmbedder = FauxEmbedder
        ent._identites.clear()
        sso.verifier_jeton_ctg = lambda j: {
            "jeton-de-pa-123456": ("pa@exemple.org", "id1"),
            "jeton-de-zoe-123456": ("zoe@exemple.org", "id2"),
        }[j] if j in ("jeton-de-pa-123456", "jeton-de-zoe-123456") else (_ for _ in ()).throw(sso.JetonInvalide("x"))
        os.environ["SITE_READ_SECRET"] = "cle-site"
        os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"

        # -- Profondeur : vrai AskAgent, aucun appel réseau ---------------------------------
        class Base:
            outils, tools, system_prompt, client, store = object(), [{"name": "list_datasets"}], "Consignes.", object(), None
        a = bib.agent_pour(Base(), "approfondi")
        check("approfondi → Opus, budget allongé", a.model == "claude-opus-5-5" and a.budget > 100)
        check("rapide → Haiku", bib.agent_pour(Base(), "rapide").model.startswith("claude-haiku"))
        check("outil des contributions ajouté, consignes conservées",
              [t["name"] for t in a.tools] == ["list_datasets", "search_member_contributions"]
              and a.system_prompt.startswith("Consignes.") and "non vérifiées" in a.system_prompt)
        try:
            bib.agent_pour(Base(), "extreme")
            check("profondeur inconnue refusée", False)
        except ValueError:
            check("profondeur inconnue refusée", True)

        api_app.get_agent = lambda appelant="ctg": Base()
        bib.agent_pour = (lambda f: lambda base, p, outils=None: FauxAgent(p))(bib.agent_pour)

        client = TestClient(api_app.app)
        PA = {"X-Webhook-Secret": "cle-site", "X-CTG-Token": "jeton-de-pa-123456"}
        ZOE = {"X-Webhook-Secret": "cle-site", "X-CTG-Token": "jeton-de-zoe-123456"}

        r = client.post("/bibliotheque/questions", json={"question": "Qui fait du compost ?"},
                        headers={"X-Webhook-Secret": "cle-site"})
        check("sans jeton CTG : refusé", r.status_code == 401)
        r = client.post("/bibliotheque/questions", json={"question": "Qui fait du compost ?"},
                        headers={"X-CTG-Token": "jeton-de-pa-123456"})
        check("sans clé du site : refusé", r.status_code == 401)

        r = client.post("/bibliotheque/questions", json={"question": "Qui fait du compost ?", "profondeur": "rapide"}, headers=PA)
        check("question : 200", r.status_code == 200)
        conv = r.json()["conversation"]
        check("réponse et conversation enregistrées",
              r.json()["reponse"].startswith("Réponse rapide") and len(conv["messages"]) == 2
              and conv["titre"] == "Qui fait du compost ?")
        r = client.post("/bibliotheque/questions", json={"question": "Et en Wallonie ?", "profondeur": "approfondi",
                                                         "conversation_id": conv["id"]}, headers=PA)
        check("suite : l'historique est renvoyé à l'agent",
              r.status_code == 200 and FauxAgent.appels[-1][0] == "approfondi"
              and [m["content"] for m in FauxAgent.appels[-1][1]][:2] == ["Qui fait du compost ?", "Réponse rapide n°1"])
        check("suite : 4 messages", len(r.json()["conversation"]["messages"]) == 4)
        r = client.post("/bibliotheque/questions", json={"question": "Test", "profondeur": "extreme"}, headers=PA)
        check("profondeur inconnue : 422", r.status_code == 422)

        uid_pa = ent.utilisateur_space2(store, "pa@exemple.org")
        brut = store.get_conversation_bibliotheque(conv["id"])
        check("même table que l'app (rouvrable dans Space2)",
              brut is not None and brut.user_id == uid_pa and brut.messages[1]["role"] == "assistant")

        r = client.get("/bibliotheque/conversations", headers=PA)
        check("historique listé", [c["id"] for c in r.json()["conversations"]] == [conv["id"]])
        check("historique d'une autre personne : vide", client.get("/bibliotheque/conversations", headers=ZOE).json()["conversations"] == [])
        check("conversation d'une autre personne : 404", client.get(f"/bibliotheque/conversations/{conv['id']}", headers=ZOE).status_code == 404)
        r = client.post("/bibliotheque/questions", json={"question": "Je continue", "conversation_id": conv["id"]}, headers=ZOE)
        check("poursuivre la conversation d'une autre : 404", r.status_code == 404)
        check("supprimer celle d'une autre : 404", client.delete(f"/bibliotheque/conversations/{conv['id']}", headers=ZOE).status_code == 404)

        # -- Contributions ----------------------------------------------------------------
        api_app._appels_site.clear()   # plafond de 10 appels par minute : on repart de zéro
        r = client.post("/bibliotheque/contributions", json={
            "nature": "texte", "titre": "Compost collectif",
            "texte": "Au Tiers-lieu des Prés, le compostage partagé réunit 40 foyers chaque semaine."}, headers=PA)
        check("note ajoutée", r.status_code == 200 and r.json()["passages"] == 1)
        id_note = r.json()["id"]
        r = client.post("/bibliotheque/contributions", json={
            "nature": "echange", "conversation_id": conv["id"], "message_index": 1}, headers=PA)
        check("échange ajouté (question + réponse)", r.status_code == 200)
        doc = [d for d in magasin.docs.values() if d[2]["contribution"] == r.json()["id"]][0][1]
        check("échange : question reprise avec la réponse", "Question : Qui fait du compost ?" in doc and "Réponse rapide n°1" in doc)
        r = client.post("/bibliotheque/contributions", json={
            "nature": "echange", "conversation_id": conv["id"], "message_index": 1}, headers=ZOE)
        check("échange d'une autre personne : 404", r.status_code == 404)
        r = client.post("/bibliotheque/contributions", json={
            "nature": "document", "fichier_nom": "guide.txt",
            "fichier_base64": base64.b64encode("Guide du financement participatif des lieux. " .encode() * 3).decode()}, headers=ZOE)
        check("document texte ajouté", r.status_code == 200 and r.json()["titre"] == "guide.txt")
        r = client.post("/bibliotheque/contributions", json={
            "nature": "document", "fichier_nom": "virus.exe", "fichier_base64": "AAAA"}, headers=ZOE)
        check("format de document refusé : 400", r.status_code == 400)
        api_app._appels_site.clear()
        r = client.post("/bibliotheque/contributions", json={"nature": "texte", "texte": "court"}, headers=PA)
        check("texte trop court : 400", r.status_code == 400)
        r = client.post("/bibliotheque/contributions", json={"nature": "lien", "url": "http://127.0.0.1:8000/admin"}, headers=PA)
        check("lien vers une adresse interne : 400", r.status_code == 400 and "public" in r.json()["detail"])
        r = client.post("/bibliotheque/contributions", json={"nature": "lien", "url": "file:///etc/passwd"}, headers=PA)
        check("lien non http : 400", r.status_code == 400)

        hote = bib._hote_public
        bib._hote_public = lambda h: h == "lieu.exemple"
        texte = bib.texte_du_lien("https://lieu.exemple/ancien", session=Session())
        check("lien : redirection suivie, menu retiré", "compostage partagé" in texte and "menu" not in texte)
        try:
            class Vers(Session):
                def get(self, url, **k):
                    return self.R(302, {"location": "http://10.0.0.5/interne"})
            bib.texte_du_lien("https://lieu.exemple/x", session=Vers())
            check("redirection vers une adresse interne refusée", False)
        except ValueError:
            check("redirection vers une adresse interne refusée", True)
        bib._hote_public = hote

        mes = client.get("/bibliotheque/contributions", headers=PA).json()["contributions"]
        check("mes contributions : les miennes seulement", len(mes) == 2 and {c["nature"] for c in mes} == {"texte", "echange"})
        check("aperçu présent", any("40 foyers" in c["apercu"] for c in mes))

        outils = bib.OutilsAvecContributions(type("O", (), {"execute": lambda s, n, e: {"delegue": n}})())
        trouve = outils.execute("search_member_contributions", {"query": "compost"})["results"]
        check("l'agent retrouve la contribution", trouve and "40 foyers" in trouve[0]["texte"])
        check("autres outils délégués", outils.execute("list_datasets", {}) == {"delegue": "list_datasets"})

        check("retirer celle d'une autre : 404", client.delete(f"/bibliotheque/contributions/{id_note}", headers=ZOE).status_code == 404)
        r = client.delete(f"/bibliotheque/contributions/{id_note}", headers=PA)
        check("retirer la sienne", r.status_code == 200 and r.json()["passages"] == 1)
        check("retirée de la base", not any(m["contribution"] == id_note for e, d, m in magasin.docs.values()))

        r = client.delete(f"/bibliotheque/conversations/{conv['id']}", headers=PA)
        check("supprimer sa conversation", r.status_code == 200 and store.get_conversation_bibliotheque(conv["id"]) is None)

    print()
    print(f"{len(ECHECS)} échec(s)" if ECHECS else "Tout passe.")
    sys.exit(1 if ECHECS else 0)


if __name__ == "__main__":
    main()
