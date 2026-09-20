"""/ask en mode accès complet (CTG_ASK_FULL_ACCESS) : opération `near`,
exclusion stricte de ce qui est explicitement confidentiel (réponses, lieux
dont la synthèse a pu l'absorber, contributeurs bloqués), index sémantique des
profils, choix du mode, et fidélité du /manifest aux jeux de données servis.
Sans réseau.

Usage : python3 -m tests.test_api_full
"""

import os
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.enrichissement import CHAMPS_DERIVES
from src.agent.structured_query import run_structured_query
from src.api import manifest
from tests.faux import FauxVectorStore
from src.api.ask_agent import (MAX_TOKENS, MAX_TOURS, TOOLS, AskAgent, OutilsComplets,
                               OutilsPublics, creer_agent)
from src.api.profil_search import ProfilSearch
from src.api.public_data import construire_datasets
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive
from src.questionnaire.schema import all_fields, champ_public


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FauxEmbedder:
    MOTS = ["permaculture", "musique", "numérique"]

    def __init__(self):
        self.appels_documents = []

    def _vec(self, texte):
        t = texte.lower()
        return [float(t.count(m)) + 0.01 for m in self.MOTS]

    def embed_documents(self, textes):
        self.appels_documents.append(len(textes))
        return [self._vec(t) for t in textes]

    def embed_query(self, texte):
        return self._vec(texte)


def test_near():
    df = pd.DataFrame([
        {"tiers_lieu": "Blanmont", "latitude": 50.63, "longitude": 4.65, "resume": "r1"},
        {"tiers_lieu": "Wavre", "latitude": 50.72, "longitude": 4.61, "resume": "r2"},
        {"tiers_lieu": "Liège", "latitude": 50.63, "longitude": 5.57, "resume": "r3"},
        {"tiers_lieu": "Sans coord", "latitude": None, "longitude": None, "resume": "r4"},
    ])
    res = run_structured_query(df, "near", {"lat": 50.63, "lon": 4.65, "radius_km": 20})
    noms = [r["tiers_lieu"] for r in res["rows"]]
    check("near : triés par distance, hors rayon exclus", noms == ["Blanmont", "Wavre"])
    check("near : distance_km croissante et ~0 pour le point même",
          res["rows"][0]["distance_km"] < 0.1 and res["rows"][0]["distance_km"] < res["rows"][1]["distance_km"])
    check("near : Wavre à ~10 km", 8 < res["rows"][1]["distance_km"] < 12)
    check("near : lieux sans coordonnées comptés", res["sans_coordonnees"] == 1)
    large = run_structured_query(df, "near", {"lat": 50.63, "lon": 4.65, "radius_km": 100, "limit": 2})
    check("near : limit respecté, row_count = total", large["row_count"] == 3 and len(large["rows"]) == 2)
    check("near : paramètres invalides → erreur",
          "error" in run_structured_query(df, "near", {"lat": "x", "lon": 4, "radius_km": 5}))
    check("near : rayon hors bornes → erreur",
          "error" in run_structured_query(df, "near", {"lat": 50, "lon": 4, "radius_km": 99999}))
    check("near : dataset sans latitude/longitude → erreur explicite",
          "latitude" in run_structured_query(pd.DataFrame({"a": [1]}), "near",
                                             {"lat": 50, "lon": 4, "radius_km": 5})["error"])


def main():
    test_near()

    champs = [f for _, _, f in all_fields()]
    publics = [f for f in champs if champ_public(f.id)]
    interne = next(f for f in champs if f.roles is not None and not champ_public(f.id))

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "full.sqlite3"))
        normal = store.get_or_create_tiers_lieu("u1", "Lieu Normal")
        sensible = store.get_or_create_tiers_lieu("u1", "Lieu Sensible")
        store.update_tiers_lieu(normal.id, pays="Belgique", latitude=50.63, longitude=4.65)
        store.update_tiers_lieu(sensible.id, pays="Belgique", latitude=50.7, longitude=4.6)

        complet = {k: f"{k} complet" for k in CHAMPS_DERIVES}
        complet["mots_cles"], complet["categories"] = ["permaculture"], ["Culturel"]
        for lieu, texte_profil, resume in ((normal, "profil permaculture normal", "Résumé complet normal"),
                                          (sensible, "profil avec SECRET_CONFIDENTIEL musique", "Résumé SECRET_CONFIDENTIEL")):
            store.save_lieu_derive(LieuDerive(
                tiers_lieu_id=lieu.id, donnees={**complet, "resume": resume},
                profil_semantique_texte=texte_profil, prompt_version="v", model="m", source_hash="h"))
        store.update_lieu_derive_publique(sensible.id, {"resume": "Résumé public sensible", "mots_cles": ["musique"],
                                                        "categories": []}, "hp")
        ok = store.get_or_create_contributeur("c1", normal.id, "fondateur")
        ok2 = store.get_or_create_contributeur("c1", sensible.id, "fondateur")
        bloque = store.get_or_create_contributeur("c2", normal.id, "usager")
        store.conn.execute("update contributeurs set bloque = 1 where id = ?", (bloque.id,))
        store.conn.commit()
        store.save_answer(normal.id, ok.id, interne.id, "valeur interne non confidentielle")
        store.save_answer(normal.id, ok.id, publics[0].id, "valeur publique")
        store.save_answer(normal.id, bloque.id, publics[1].id, "valeur du bloqué")
        store.save_answer(sensible.id, ok2.id, publics[0].id, "OK sensible")
        store.save_answer(sensible.id, ok2.id, publics[2].id, "SECRET_CONFIDENTIEL", confidentiel=True)
        store.save_free_text_note(normal.id, ok.id, "bonne_pratique", "Un retour d'expérience.")
        store.add_evenement_ctg(normal.id, "ev1", "discussion", "T", "Texte", "https://x.y", "2026-09-20T10:00:00")

        check("get_lieux_avec_confidentiel", store.get_lieux_avec_confidentiel([normal.id, sensible.id]) == {sensible.id})

        profils = ProfilSearch(store, embedder=FauxEmbedder(), ttl=0)
        outils = OutilsComplets(store, profils, ttl=0, vectorstore=FauxVectorStore([]))

        # --- réponses détaillées ---
        rep = outils._load_dataframe("reponses_tiers_lieux")
        check("réponses : champ interne NON confidentiel conservé (même capacité que le site)",
              (rep["champ_id"] == interne.id).any())
        check("réponses : confidentiel exclu", "SECRET_CONFIDENTIEL" not in str(rep.to_dict()))
        check("réponses : contributeur bloqué exclu", "valeur du bloqué" not in set(rep["valeur"]))
        check("réponses : colonnes identiques au site (contributeur_id inclus)",
              list(rep.columns) == ["tiers_lieu", "pays", "region", "contributeur_id", "champ", "champ_id", "valeur"])

        # --- synthèses ---
        enrichis = outils._load_dataframe("lieux_enrichis").set_index("tiers_lieu")
        check("lieux_enrichis : lieu sans confidentiel → synthèse complète",
              enrichis.loc["Lieu Normal", "resume"] == "Résumé complet normal"
              and enrichis.loc["Lieu Normal", "gouvernance"] == "gouvernance complet")
        check("lieux_enrichis : lieu avec confidentiel → synthèse publique, rien d'absorbé",
              enrichis.loc["Lieu Sensible", "resume"] == "Résumé public sensible"
              and "SECRET_CONFIDENTIEL" not in str(enrichis.loc["Lieu Sensible"].to_dict()))
        check("lieux_enrichis : latitude/longitude présentes", enrichis.loc["Lieu Normal", "latitude"] == 50.63)

        # --- recherche sémantique ---
        res = outils.execute("search_knowledge_base", {"query": "permaculture", "top_k": 5})["results"]
        check("recherche : le lieu pertinent arrive premier", res[0]["metadata"]["source_file"] == "Lieu Normal")
        check("recherche : le profil complet d'un lieu avec confidentiel n'est jamais indexé",
              "SECRET_CONFIDENTIEL" not in str(res))
        check("recherche : lieu avec confidentiel présent via sa synthèse publique",
              any(h["metadata"]["source_file"] == "Lieu Sensible" and "Résumé public sensible" in h["text"] for h in res))
        check("recherche : connaissances de la Bibliothèque exclues (doc_type refusé)",
              "error" in outils.execute("search_knowledge_base", {"query": "x", "doc_type": "connaissance_bibliotheque"}))
        appels = list(profils._embedder.appels_documents)
        outils.execute("search_knowledge_base", {"query": "musique"})
        check("recherche : profils inchangés → pas de nouveaux embeddings",
              profils._embedder.appels_documents == appels)
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=normal.id, donnees={**complet}, profil_semantique_texte="profil modifié numérique",
            prompt_version="v", model="m", source_hash="h2"))
        # TTL expiré : la recherche sert l'ancien index et rafraîchit en arrière-plan.
        ancien = outils.execute("search_knowledge_base", {"query": "numérique"})["results"]
        check("recherche après expiration du TTL : servie avec l'index existant, sans attendre",
              len(ancien) >= 1 and "profil modifié" not in str(ancien))
        for _ in range(50):
            if profils._embedder.appels_documents[-1] == 1 and not profils._en_cours:
                break
            time.sleep(0.05)
        check("rafraîchissement en arrière-plan : seul le profil modifié est recalculé",
              profils._embedder.appels_documents[-1] == 1)
        check("l'index à jour contient le nouveau profil",
              "profil modifié" in str(outils.execute("search_knowledge_base", {"query": "numérique"})["results"]))

        # --- une erreur d'outil ne divulgue jamais de secret ---
        class EmbedderCasse(FauxEmbedder):
            def embed_query(self, texte):
                raise RuntimeError("Error communicating: header 'Bearer pa-SECRETSECRETSECRETSECRET12345\\n'")

        casse = OutilsComplets(store, ProfilSearch(store, embedder=EmbedderCasse(), ttl=10_000), ttl=0,
                               vectorstore=FauxVectorStore([]))
        casse.profils.rafraichir()
        erreur = casse.execute("search_knowledge_base", {"query": "x"})
        check("recherche en échec : message expurgé (aucun secret renvoyé au modèle)",
              "error" in erreur and "SECRET" not in str(erreur) and "Bearer" not in str(erreur))
        class OutilsQuiPlante:
            def execute(self, nom, entree):
                raise ValueError("clé sk-ant-api03-ABCDEFGHIJKLMNOP1234 refusée")
        rep_outil = AskAgent(OutilsQuiPlante())._executer("x", {})
        check("erreur générique d'outil : type seulement, pas de secret",
              "ValueError" in rep_outil["error"] and "sk-ant" not in str(rep_outil))

        # --- outils via l'interface de l'agent ---
        near = outils.execute("query_structured_data", {
            "dataset_name": "lieux_enrichis", "operation": "near",
            "params": {"lat": 50.63, "lon": 4.65, "radius_km": 30}})
        check("near via l'outil, sur lieux_enrichis",
              [r["tiers_lieu"] for r in near["rows"]][0] == "Lieu Normal" and near["row_count"] == 2)
        noms_ds = {d["name"] for d in outils.execute("list_datasets", {})["datasets"]}
        check("list_datasets : les jeux du site",
              {"reponses_tiers_lieux", "lieux_enrichis", "bonnes_pratiques", "activite_ctg"} <= noms_ds)
        check("bonnes_pratiques et activite_ctg disponibles",
              len(outils._load_dataframe("bonnes_pratiques")) == 1 and len(outils._load_dataframe("activite_ctg")) == 1)

        # --- choix du mode ---
        os.environ["CTG_ASK_FULL_ACCESS"] = "true"
        agent = creer_agent(store)
        check("mode complet par défaut : 8 tours, 6000 tokens, sonnet-5, outils du site + near",
              agent.max_tours == MAX_TOURS == 8 and agent.max_tokens == MAX_TOKENS == 6000
              and agent.model == "claude-sonnet-5" and isinstance(agent.outils, OutilsComplets)
              and "near" in str(agent.tools) and "search_knowledge_base" in str(agent.tools))
        check("mode complet : prompt mentionne near, synonymes et confidentialité",
              all(m in agent.system_prompt for m in ("near", "synonymes", "confidentielles", "Blanmont",
                                                     "context.language", "nom exact"))
              and "concise" not in agent.system_prompt.lower())
        os.environ.pop("CTG_ASK_FULL_ACCESS")
        check("défaut (variable absente) = accès complet", isinstance(creer_agent(store).outils, OutilsComplets))
        os.environ["CTG_ASK_FULL_ACCESS"] = "false"
        agent = creer_agent(store)
        check("false : jeux de données publics, mêmes outils d'origine, pas de near",
              isinstance(agent.outils, OutilsPublics)
              and agent.tools is TOOLS and "near" not in str(agent.tools))
        os.environ.pop("CTG_ASK_FULL_ACCESS")

        # --- manifest fidèle aux données servies ---
        reels_complet = {
            "lieux_enrichis": set(outils._load_dataframe("lieux_enrichis").columns),
            "reponses_tiers_lieux": set(rep.columns),
            "bonnes_pratiques": set(outils._load_dataframe("bonnes_pratiques").columns),
            "activite_ctg": set(outils._load_dataframe("activite_ctg").columns),
            "organisations_ctg": set(outils._load_dataframe("organisations_ctg").columns),
        }
        m = manifest.construire_manifest(acces_complet=True)
        declares = {d["name"]: {c["name"] for c in d["columns"]} for d in m["datasets"]}
        check("manifest complet : mêmes jeux de données que ceux servis", set(declares) == set(reels_complet))
        for nom, cols in reels_complet.items():
            check(f"manifest complet : colonnes de {nom} = colonnes réelles", declares[nom] == cols)
        check("manifest : chaque colonne a une description",
              all(c["description"] for d in m["datasets"] for c in d["columns"]))
        check("manifest complet : readme annonce l'accès aux données complètes hors confidentiel",
              "données complètes" in m["readme"] and "confidentiel" in m["readme"]
              and m["access"] == "full_without_confidential")
        reels_public = {nom: set(df.columns) for nom, df in construire_datasets(store).items()}
        mp = manifest.construire_manifest(acces_complet=False)
        declares_p = {d["name"]: {c["name"] for c in d["columns"]} for d in mp["datasets"]}
        check("manifest public : colonnes = colonnes réelles",
              all(declares_p[n] == c for n, c in reels_public.items()) and set(declares_p) == set(reels_public))
        check("manifest public : readme inchangé (données publiques uniquement)",
              "PUBLIQUES" in mp["readme"] and mp["access"] == "public_only")
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
