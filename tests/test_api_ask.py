"""API publique /ask : authentification, validation, filtrage strict des
données publiques (confidentiel / bloqué / champs internes) et budget de
l'agent — sans réseau (faux client Anthropic).

Usage : python3 -m tests.test_api_ask
"""

import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api import app as api_app
from src.api.ask_agent import AskAgent, OutilsPublics
from src.api.public_data import DonneesPubliques, champ_public
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive
from src.questionnaire.schema import all_fields


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def bloc_texte(texte):
    return types.SimpleNamespace(type="text", text=texte)


def bloc_tool(id_, nom, entree):
    b = types.SimpleNamespace(type="tool_use", id=id_, name=nom, input=entree)
    b.model_dump = lambda exclude_none=True: {"type": "tool_use", "id": id_, "name": nom, "input": entree}
    return b


class FauxClient:
    """Rejoue une liste de réponses ; enregistre les kwargs de chaque appel."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []
        self.messages = self

    def create(self, **kwargs):
        self.appels.append(kwargs)
        contenu = self.reponses.pop(0) if self.reponses else [bloc_texte("fin")]
        return types.SimpleNamespace(content=contenu, usage=types.SimpleNamespace(
            input_tokens=1, output_tokens=1))


def main():
    champs = [f for _, _, f in all_fields()]
    public = next(f for f in champs if champ_public(f.id))
    interne = next(f for f in champs if f.roles is not None and not champ_public(f.id))
    confidentiel_defaut = [f for f in champs if f.confidential_default]

    check("un champ réservé aux rôles internes n'est pas public", not champ_public(interne.id))
    check("un champ inconnu n'est pas public", not champ_public("champ_qui_n_existe_pas"))
    check("les champs confidentiels par défaut ne sont pas publics",
          all(not champ_public(f.id) for f in confidentiel_defaut))

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "api.sqlite3"))
        lieu = store.get_or_create_tiers_lieu("u1", "Lieu Public")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu.id, donnees={"resume": "Un résumé.", "categories": ["Culturel"]},
            profil_semantique_texte="p", prompt_version="v1", model="m", source_hash="h"))
        ok = store.get_or_create_contributeur("c1", lieu.id, "fondateur")
        bloque = store.get_or_create_contributeur("c2", lieu.id, "usager")
        store.conn.execute("update contributeurs set bloque = 1 where id = ?", (bloque.id,))
        store.conn.commit()

        store.save_answer(lieu.id, ok.id, public.id, "valeur publique")
        store.save_answer(lieu.id, ok.id, interne.id, "valeur interne")
        publics = [f for f in champs if champ_public(f.id) and f.id != public.id]
        conf, champ_bloque = publics[0], publics[1]
        store.save_answer(lieu.id, bloque.id, champ_bloque.id, "valeur bloquée")
        store.save_answer(lieu.id, ok.id, conf.id, "valeur confidentielle", confidentiel=True)

        donnees = DonneesPubliques(store, ttl=60).get()
        reps = donnees["reponses_publiques"]
        check("la réponse publique est exposée", (reps["champ_id"] == public.id).any())
        check("le champ interne est exclu", not (reps["champ_id"] == interne.id).any())
        check("la réponse confidentiel=true est exclue", not (reps["champ_id"] == conf.id).any())
        check("aucune réponse de contributeur bloqué (champ pourtant public)",
              not (reps["champ_id"] == champ_bloque.id).any())
        check("aucun identifiant de contributeur exposé", "contributeur_id" not in reps.columns)
        check("le dataset lieux n'expose jamais la synthèse interne (donnees)",
              "Un résumé." not in str(donnees["lieux"].to_dict()))
        check("le dataset lieux liste le lieu", list(donnees["lieux"]["tiers_lieu"]) == ["Lieu Public"])

        # --- Agent : passe par un tool puis répond ; budget respecté ---
        source = DonneesPubliques(store, ttl=60)
        client = FauxClient([
            [bloc_tool("t1", "query_structured_data",
                       {"dataset_name": "lieux", "operation": "head", "params": {"n": 3}})],
            [bloc_texte("Réponse.\nSources : Lieu Public")],
        ])
        reponse = AskAgent(OutilsPublics(source), client=client).ask([{"role": "user", "content": "Quels lieux ?"}])
        check("l'agent renvoie le texte final", reponse.startswith("Réponse."))
        check("le résultat du tool est renvoyé au modèle",
              "Lieu Public" in client.appels[1]["messages"][-1]["content"][0]["content"])

        client = FauxClient([[bloc_tool(f"t{i}", "list_datasets", {})] for i in range(10)])
        AskAgent(OutilsPublics(source), client=client).ask([{"role": "user", "content": "?"}])
        check("nombre de tours borné", len(client.appels) <= 4)
        check("dernier tour sans tools (tool_choice none)",
              client.appels[-1].get("tool_choice") == {"type": "none"})

        client = FauxClient([[bloc_texte("x")]])
        rep = AskAgent(OutilsPublics(source), client=client, budget=1.0).ask([{"role": "user", "content": "?"}])
        check("budget épuisé → message explicite sans appel LLM", not client.appels and "temps" in rep)

        # --- HTTP ---
        os.environ["CTG_WEBHOOK_SECRET"] = "s3cret"
        os.environ["CTG_ASK_FULL_ACCESS"] = "false"
        api_app._agent = AskAgent(OutilsPublics(source), client=FauxClient([[bloc_texte("ok\nSources : aucune")]]))
        http = TestClient(api_app.app)
        corps = {"messages": [{"role": "user", "content": "Bonjour"}]}
        check("sans secret → 401", http.post("/ask", json=corps).status_code == 401)
        check("mauvais secret → 401",
              http.post("/ask", json=corps, headers={"X-Webhook-Secret": "nope"}).status_code == 401)
        check("bon secret → 200 + content",
              http.post("/ask", json=corps, headers={"X-Webhook-Secret": "s3cret"}).json()["content"].startswith("ok"))
        h = {"X-Webhook-Secret": "s3cret"}
        check("messages vides → 422", http.post("/ask", json={"messages": []}, headers=h).status_code == 422)
        check("dernier message assistant → 422", http.post("/ask", json={"messages": [
            {"role": "assistant", "content": "x"}]}, headers=h).status_code == 422)
        check("rôle invalide → 422", http.post("/ask", json={"messages": [
            {"role": "system", "content": "x"}]}, headers=h).status_code == 422)
        os.environ.pop("CTG_WEBHOOK_SECRET")
        check("secret non configuré → tout refusé (fail closed)",
              http.post("/ask", json=corps, headers=h).status_code == 401)
        check("/health public", http.get("/health").json() == {"status": "ok"})
        m = http.get("/manifest")
        check("/manifest public (sans secret)", m.status_code == 200)
        fiche = m.json()
        check("manifest : champs de la fiche ctg",
              all(k in fiche for k in ("name", "description", "purpose", "readme", "variables",
                                       "topics", "territories", "category", "version")))
        check("manifest : reflète le modèle configuré", fiche["model"] in fiche["readme"])
        check("manifest : liste les jeux de données réels",
              {d["name"] for d in fiche["datasets"]} == {"lieux", "reponses_publiques", "activite_ctg"})
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
