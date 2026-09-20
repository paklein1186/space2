"""PUT /ctg/objects : lieux ctg -> lieux Space2 (galerie + portfolio), tout le
reste -> connaissance (dataset organisations_ctg + recherche sémantique),
jamais galerie/portfolio. Sans réseau.

Usage : python3 -m tests.test_api_objects
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.agent.objets_ctg import organisations_ctg_dataframe
from src.api import app as api_app
from src.api.ask_agent import OutilsComplets
from src.api.profil_search import ProfilSearch
from src.api.public_data import construire_datasets
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


G1 = "0a1b2c3d-0000-4000-8000-000000000001"
G2 = "0a1b2c3d-0000-4000-8000-000000000002"
G3 = "0a1b2c3d-0000-4000-8000-000000000003"
Q1 = "0a1b2c3d-0000-4000-8000-0000000000a1"
C1 = "0a1b2c3d-0000-4000-8000-0000000000c1"
P1 = "0a1b2c3d-0000-4000-8000-0000000000b1"


class FauxEmbedder:
    MOTS = ["permaculture", "musique", "numérique"]

    def _vec(self, t):
        return [float(t.lower().count(m)) + 0.01 for m in self.MOTS]

    def embed_documents(self, textes):
        return [self._vec(t) for t in textes]

    def embed_query(self, t):
        return self._vec(t)


def lieu_ctg(guid, nom, **kw):
    return {"ctg_id": f"guild:{guid}", "kind": "lieu", "is_place": True, "name": nom,
            "description": f"Description de {nom}", "topics": ["permaculture"],
            "territories": ["Belgique", "Brabant wallon"], "commune": "Chastre",
            "latitude": 50.63, "longitude": 4.65, "updated_at": "2026-09-21T10:00:00Z", **kw}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "obj.sqlite3"))
        # Lieu Space2 existant, non lié, avec une vraie synthèse (Portfolio non coché)
        existant = store.get_or_create_tiers_lieu("owner-1", "Lieu Déjà Là")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=existant.id, donnees={"resume": "Vrai résumé Space2"},
            profil_semantique_texte="profil", prompt_version="enrichissement-v3", model="m", source_hash="h"))
        # Lieu déjà lié à une autre guilde
        pris = store.get_or_create_tiers_lieu("owner-1", "Nom Pris")
        store.update_tiers_lieu(pris.id, ctg_entity_id=G3)

        os.environ["CTG_WEBHOOK_SECRET"] = "s3cret"
        os.environ.pop("CTG_OWNER_USER_ID", None)
        api_app.get_store = lambda: store
        http = TestClient(api_app.app)
        h = {"X-Webhook-Secret": "s3cret"}
        put = lambda objs: http.put("/ctg/objects", json={"objects": objs}, headers=h)

        check("sans secret → 401", http.put("/ctg/objects", json={"objects": []}).status_code == 401)
        check("liste vide → 200 received 0", put([]).json()["received"] == 0)

        # --- validation ---
        base = lieu_ctg(G1, "X")
        for label, patch in [("ctg_id sans préfixe", {"ctg_id": G1}), ("préfixe inconnu", {"ctg_id": f"team:{G1}"}),
                             ("uuid invalide", {"ctg_id": "guild:pas-un-uuid"}), ("kind inconnu", {"kind": "spam"}),
                             ("url non http", {"url": "javascript:x"}), ("latitude hors bornes", {"latitude": 123}),
                             ("nom vide", {"name": "  "}), ("updated_at invalide", {"updated_at": "hier"}),
                             ("parent_ctg_id invalide", {"parent_ctg_id": "n'importe quoi"})]:
            check(f"validation : {label} → 422", put([{**base, **patch}]).status_code == 422)
        check("validation : pas de lieu créé par un lot invalide", len(store.list_tiers_lieux()) == 2)

        # --- création d'un lieu ---
        rep = put([lieu_ctg(G1, "Nouveau Lieu ctg")])
        check("200 et received=1", rep.status_code == 200 and rep.json()["received"] == 1)
        check("lieux_created=1", rep.json()["lieux_created"] == 1)
        lieux = {l.nom: l for l in store.list_tiers_lieux()}
        nouveau = lieux["Nouveau Lieu ctg"]
        check("lieu créé dans la bibliothèque (galerie : list_tiers_lieux)", nouveau is not None)
        check("ctg_entity_id = id de la guilde (uuid)", nouveau.ctg_entity_id == G1)
        check("propriétaire = propriétaire le plus fréquent (valide)", nouveau.owner_user_id == "owner-1")
        check("coordonnées, commune et pays posés",
              (nouveau.latitude, nouveau.longitude, nouveau.commune, nouveau.pays) == (50.63, 4.65, "Chastre", "Belgique"))
        derive = store.get_lieu_derive(nouveau.id)
        check("synthèse minimale issue de ctg",
              derive.donnees["resume"] == "Description de Nouveau Lieu ctg" and derive.donnees["mots_cles"] == ["permaculture"]
              and "Chastre" in derive.donnees["territoire"])
        check("synthèse publique posée (flux /lieux, API)", derive.donnees_publiques["resume"] == derive.donnees["resume"])
        check("inclus dans le portfolio", nouveau.id in {l.id for l in store.list_lieux_portfolio()})
        check("flux /lieux : ctg_entity_id + résumé",
              {p["tiers_lieu"]: p for p in http.get("/lieux", headers=h).json()["lieux"]}["Nouveau Lieu ctg"]["resume"]
              == "Description de Nouveau Lieu ctg")
        check("les lieux ne sont pas des 'organisations'", len(organisations_ctg_dataframe(store)) == 0)

        # --- upsert (mêmes ctg_id) ---
        rep = put([lieu_ctg(G1, "Nouveau Lieu ctg", description="Description modifiée")]).json()
        check("upsert : pas de doublon, pas de nouvelle création",
              rep["lieux_created"] == 0 and len(store.list_tiers_lieux()) == 3)
        check("upsert : synthèse ctg rafraîchie (lieu encore alimenté par ctg seul)",
              store.get_lieu_derive(nouveau.id).donnees["resume"] == "Description modifiée")
        check("upsert : objets_ctg à jour", [o["description"] for o in store.list_objets_ctg()] == ["Description modifiée"])

        # --- rattachement d'un lieu existant de même nom ---
        rep = put([lieu_ctg(G2, "lieu déjà là", description="Vue ctg")]).json()
        check("lieu existant de même nom → rattaché (pas créé)", rep["lieux_linked"] == 1 and rep["lieux_created"] == 0)
        relie = store.list_tiers_lieux()
        check("rattaché : ctg_entity_id posé, pas de doublon",
              len([l for l in relie if l.nom.lower() == "lieu déjà là"]) == 1
              and next(l for l in relie if l.nom == "Lieu Déjà Là").ctg_entity_id == G2)
        d = store.get_lieu_derive(existant.id)
        check("rattaché : données Space2 jamais écrasées", d.donnees["resume"] == "Vrai résumé Space2"
              and d.prompt_version == "enrichissement-v3")
        check("rattaché : statut Portfolio inchangé", existant.id not in {l.id for l in store.list_lieux_portfolio()})
        rep = put([lieu_ctg(G2, "Lieu Déjà Là", description="Encore ctg")]).json()
        check("lieu déjà lié : mise à jour sans effet sur la synthèse Space2",
              rep["lieux_created"] == 0 and store.get_lieu_derive(existant.id).donnees["resume"] == "Vrai résumé Space2")

        # --- erreurs de lieu : stockés quand même comme connaissance ---
        rep = put([lieu_ctg(G3.replace("3", "4"), "Nom Pris"),
                   {**lieu_ctg(G1, "Pas une guilde"), "ctg_id": f"company:{C1}"}]).json()
        check("nom pris par un lieu d'une autre guilde → rejeté", any("autre guilde" in r["reason"] for r in rep["rejected"]))
        check("lieu hors guilde → rejeté", any("guilde" in r["reason"] for r in rep["rejected"]) and len(rep["rejected"]) == 2)
        check("aucun lieu créé pour ces rejets", len(store.list_tiers_lieux()) == 3)
        noms_conn = set(organisations_ctg_dataframe(store)["nom"])
        check("un lieu rejeté reste consultable comme connaissance", {"Nom Pris", "Pas une guilde"} <= noms_conn)

        # --- non-lieux : connaissance uniquement ---
        avant = {l.id for l in store.list_tiers_lieux()}
        autres = [
            {"ctg_id": f"quest:{Q1}", "kind": "quete", "is_place": False, "name": "Quête Numérique",
             "description": "Mettre le numérique au service des lieux", "topics": ["numérique"], "territories": ["Wallonie"],
             "parent_ctg_id": f"guild:{G1}", "status": "open", "url": "https://ctg.example/q/1"},
            {"ctg_id": f"company:{C1}", "kind": "organisation", "is_place": False, "name": "Coop Musique",
             "description": "Coopérative de musique", "topics": ["musique"], "website_url": "https://coop.example"},
            {"ctg_id": f"post:{P1}", "kind": "post", "is_place": False, "name": "Un post", "description": "Texte"},
            {**lieu_ctg(G1, "Faux lieu"), "is_place": False, "ctg_id": f"guild:{G2.replace('2', '5')}"},
        ]
        rep = put(autres).json()
        check("received = nombre d'objets", rep["received"] == 4 and rep["lieux_created"] == 0)
        check("jamais dans la galerie", {l.id for l in store.list_tiers_lieux()} == avant)
        check("jamais dans le portfolio", {l.nom for l in store.list_lieux_portfolio()} == {"Nouveau Lieu ctg"})
        df = organisations_ctg_dataframe(store).set_index("nom")
        check("dataset organisations_ctg : kinds et thèmes",
              df.loc["Quête Numérique", "kind"] == "quete" and df.loc["Quête Numérique", "topics"] == ["numérique"])
        check("parent résolu par nom", df.loc["Quête Numérique", "parent_nom"] == "Nouveau Lieu ctg")
        check("objet non-lieu marqué is_place=false : connaissance", "Faux lieu" in df.index)
        check("un lieu devenu lieu Space2 n'apparaît pas comme organisation", "Nouveau Lieu ctg" not in df.index)

        # --- doublon dans un lot : le dernier gagne ---
        rep = put([{**autres[2], "name": "Premier"}, {**autres[2], "name": "Second"}]).json()
        check("doublon de ctg_id dans un lot : received compte les deux, le dernier gagne",
              rep["received"] == 2 and any(o["name"] == "Second" for o in store.list_objets_ctg())
              and not any(o["name"] == "Premier" for o in store.list_objets_ctg()))

        # --- exposition à l'agent /ask ---
        pub = construire_datasets(store)
        check("mode public : dataset organisations_ctg", "Coop Musique" in set(pub["organisations_ctg"]["nom"]))
        outils = OutilsComplets(store, ProfilSearch(store, embedder=FauxEmbedder(), ttl=0), ttl=0)
        check("mode complet : list_datasets contient organisations_ctg",
              "organisations_ctg" in {d["name"] for d in outils.execute("list_datasets", {})["datasets"]})
        res = outils.execute("query_structured_data", {
            "dataset_name": "organisations_ctg", "operation": "filter",
            "params": {"conditions": [{"column": "kind", "op": "eq", "value": "quete"}]}})
        check("mode complet : requête structurée sur organisations_ctg", res["row_count"] == 1)
        hits = outils.execute("search_knowledge_base", {"query": "musique", "doc_type": "objet_ctg"})["results"]
        check("recherche sémantique sur les objets ctg", hits[0]["source_file"] if False else hits[0]["metadata"]["source_file"] == "Coop Musique")
        check("recherche objet_ctg : jamais de profil de lieu", all(h["metadata"]["doc_type"] == "objet_ctg" for h in hits))
        hits = outils.execute("search_knowledge_base", {"query": "permaculture", "doc_type": "profil_lieu"})["results"]
        check("recherche profil_lieu : jamais d'objet ctg", all(h["metadata"]["doc_type"] == "profil_lieu" for h in hits))
        tout = outils.execute("search_knowledge_base", {"query": "musique"})["results"]
        check("sans doc_type : profils et objets confondus",
              {"profil_lieu", "objet_ctg"} <= {h["metadata"]["doc_type"] for h in tout})

        # --- propriétaire configurable ---
        os.environ["CTG_OWNER_USER_ID"] = "service-user"
        put([lieu_ctg("0a1b2c3d-0000-4000-8000-000000000009", "Lieu Service")])
        check("CTG_OWNER_USER_ID prioritaire",
              next(l for l in store.list_tiers_lieux() if l.nom == "Lieu Service").owner_user_id == "service-user")
        os.environ.pop("CTG_OWNER_USER_ID")
    os.environ.pop("CTG_WEBHOOK_SECRET", None)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
