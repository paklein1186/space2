"""Extraction assistée de lieux candidats depuis un document (voir
agent/extraction_lieux.py) : le CRUD CandidatLieu, l'extraction elle-même
(faux client Anthropic — doublons écartés, JSON malformé, texte vide,
troncature) et l'acceptation/le rejet (création du lieu, non-écrasement d'un
lieu existant, jamais publié au Portfolio, note de provenance, candidat marqué
traité). Sans réseau.

Usage : python3 -m tests.test_extraction_lieux
"""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.extraction_lieux import accepter_candidat, extraire_candidats, rejeter_candidat
from src.db.sqlite_store import SqliteStore
from src.db.store import CandidatLieu, LieuDerive


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def bloc_texte(texte):
    return types.SimpleNamespace(type="text", text=texte)


class FauxClient:
    def __init__(self, reponse_texte, stop_reason="end_turn"):
        self.reponse_texte, self.stop_reason, self.prompts = reponse_texte, stop_reason, []
        self.messages = self

    def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return types.SimpleNamespace(content=[bloc_texte(self.reponse_texte)], stop_reason=self.stop_reason,
                                     usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))


class ClientQuiPlante:
    messages = None

    def create(self, **kwargs):
        raise RuntimeError("panne réseau")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "extraction.sqlite3"))

        # --- CRUD CandidatLieu ---
        c = store.save_candidat_lieu(CandidatLieu(nom="Le Phare Rural", description="d", source_label="s"))
        check("save_candidat_lieu : id posé, statut par défaut 'propose'", c.id and c.statut == "propose")
        check("list_candidats_lieux() : le candidat y est", any(x.id == c.id for x in store.list_candidats_lieux()))
        check("list_candidats_lieux(statut='propose') : présent", any(x.id == c.id for x in
                                                                      store.list_candidats_lieux("propose")))
        store.traiter_candidat_lieu(c.id, "rejete", None, "admin@x.org")
        check("list_candidats_lieux(statut='propose') : disparu après traitement",
              not any(x.id == c.id for x in store.list_candidats_lieux("propose")))
        check("list_candidats_lieux(statut='rejete') : le retrouve, traite_par posé",
              next(x for x in store.list_candidats_lieux("rejete") if x.id == c.id).traite_par == "admin@x.org")

        # --- extraction : cas normal, doublons écartés (existants + au sein de la réponse) ---
        store.get_or_create_tiers_lieu("u1", "Lieu Déjà Recensé")
        json_reponse = (
            '{"lieux": [\n'
            '  {"nom": "Lieu Déjà Recensé", "description": "x", "commune": null, "pays": null, "citation": "x"},\n'
            '  {"nom": "  lieu déjà RECENSÉ  ", "description": "x", "commune": null, "pays": null, "citation": "x"},\n'
            '  {"nom": "Nouveau Lieu A", "description": "Un tiers-lieu rural.", "commune": "Blanmont", '
            '"pays": "Belgique", "citation": "Nouveau Lieu A, à Blanmont, est un tiers-lieu rural."},\n'
            '  {"nom": "Nouveau Lieu A", "description": "doublon dans la même réponse", "commune": null, '
            '"pays": null, "citation": "x"},\n'
            '  {"nom": "Nouveau Lieu B", "description": "Un café associatif.", "commune": null, "pays": null, '
            '"citation": "x"}\n'
            "]}"
        )
        client = FauxClient(json_reponse)
        resultat = extraire_candidats(store, "texte source du document...", "un document (guide.pdf)", client=client)
        check("extraction : 2 proposés (A et B), 3 doublons écartés (1 existant + 1 casse/espaces + 1 intra-réponse)",
              resultat == {"proposes": 2, "doublons_ecartes": 3})
        noms_proposes = {c.nom for c in store.list_candidats_lieux("propose")}
        check("extraction : les deux nouveaux lieux sont bien enregistrés, pas le doublon",
              noms_proposes == {"Nouveau Lieu A", "Nouveau Lieu B"})
        candidat_a = next(c for c in store.list_candidats_lieux("propose") if c.nom == "Nouveau Lieu A")
        check("extraction : commune/pays/citation transmis", candidat_a.commune == "Blanmont"
              and candidat_a.pays == "Belgique" and "Blanmont" in candidat_a.citation)
        check("extraction : source_label transmis", candidat_a.source_label == "un document (guide.pdf)")
        check("extraction : le document source est bien dans le prompt", "texte source du document" in client.prompts[0])

        # --- réponse entourée de ```json ... ``` ---
        client2 = FauxClient('```json\n{"lieux": [{"nom": "Lieu Fence", "description": "d", "commune": null, '
                             '"pays": null, "citation": null}]}\n```')
        r2 = extraire_candidats(store, "texte", "source", client=client2)
        check("extraction : réponse entourée de balises markdown correctement parsée", r2["proposes"] == 1)

        # --- cas limites ---
        check("extraction : texte vide → rien, aucun appel LLM",
              extraire_candidats(store, "   ", "source", client=FauxClient("{}")) == {"proposes": 0, "doublons_ecartes": 0})
        client_vide = FauxClient('{"lieux": []}')
        check("extraction : aucun lieu trouvé → proposes=0", extraire_candidats(
            store, "texte", "source", client=client_vide) == {"proposes": 0, "doublons_ecartes": 0})
        client_casse = FauxClient("ceci n'est pas du JSON")
        r_casse = extraire_candidats(store, "texte", "source", client=client_casse)
        check("extraction : JSON illisible → erreur explicite, pas de plantage", "erreur" in r_casse)
        r_panne = extraire_candidats(store, "texte", "source", client=ClientQuiPlante())
        check("extraction : panne réseau → erreur explicite, pas de plantage", "erreur" in r_panne)

        # --- troncature ---
        client_long = FauxClient('{"lieux": []}')
        long_texte = "a" * 700_000
        extraire_candidats(store, long_texte, "source", client=client_long)
        check("extraction : document trop long → tronqué avant l'appel LLM",
              len(client_long.prompts[0]) < len(long_texte))
        client_court = FauxClient('{"lieux": []}')
        r_court = extraire_candidats(store, "un texte court", "source", client=client_court)
        check("extraction : document court → pas de mention de troncature", "tronque" not in r_court)

        # --- réponse coupée à max_tokens (JSON en plein milieu d'une chaîne) : récupération partielle ---
        json_coupe = (
            '{"lieux": [\n'
            '  {"nom": "Lieu Complet Un", "description": "d1", "commune": null, "pays": null, "citation": "c1"},\n'
            '  {"nom": "Lieu Complet Deux", "description": "d2", "commune": null, "pays": null, "citation": "c2"},\n'
            '  {"nom": "Lieu Coupe", "description": "phrase interrompue au milieu de la cha'
        )
        client_tronque = FauxClient(json_coupe, stop_reason="max_tokens")
        r_tronque = extraire_candidats(store, "texte", "source coupée", client=client_tronque)
        check("réponse tronquée : les objets complets sont récupérés, signalé dans le résultat",
              r_tronque["proposes"] == 2 and r_tronque.get("reponse_tronquee") is True)
        candidats_ce_cas = [c for c in store.list_candidats_lieux("propose") if c.source_label == "source coupée"]
        check("réponse tronquée : le lieu coupé (objet incomplet) n'est jamais enregistré",
              {c.nom for c in candidats_ce_cas} == {"Lieu Complet Un", "Lieu Complet Deux"})

        # --- réponse coupée avant le moindre objet complet : rien à récupérer, pas d'erreur ---
        client_coupe_tot = FauxClient('{"lieux": [\n  {"nom": "Lieu jamais term', stop_reason="max_tokens")
        r_coupe_tot = extraire_candidats(store, "texte", "source", client=client_coupe_tot)
        check("réponse coupée trop tôt : 0 proposé, signalé, jamais d'erreur qui ferait perdre l'appel",
              r_coupe_tot == {"proposes": 0, "doublons_ecartes": 0, "reponse_tronquee": True})

        # --- réponse non tronquée mais malgré tout invalide : toujours une vraie erreur (pas de faux salut) ---
        client_casse_normal = FauxClient("ceci n'est pas du JSON", stop_reason="end_turn")
        r_casse_normal = extraire_candidats(store, "texte", "source", client=client_casse_normal)
        check("JSON invalide SANS troncature : erreur franche, pas de récupération silencieuse",
              "erreur" in r_casse_normal)

        # --- acceptation ---
        candidat_b = next(c for c in store.list_candidats_lieux("propose") if c.nom == "Nouveau Lieu B")
        lieu = accepter_candidat(store, candidat_a, "admin@x.org")
        check("acceptation : lieu créé avec le nom du candidat", lieu.nom == "Nouveau Lieu A")
        check("acceptation : pays/commune du candidat posés", lieu.pays == "Belgique" and lieu.commune == "Blanmont")
        derive = store.get_lieu_derive(lieu.id)
        check("acceptation : synthèse minimale à partir de la description",
              derive.donnees["resume"] == "Un tiers-lieu rural." and derive.donnees_publiques["resume"] == derive.donnees["resume"])
        check("acceptation : PAS inclus au Portfolio automatiquement", lieu.id not in {l.id for l in store.list_lieux_portfolio()})
        notes = store.get_free_text_notes(lieu.id)
        check("acceptation : note de provenance ajoutée, citation incluse",
              len(notes) == 1 and "guide.pdf" in notes[0]["texte"] and "Blanmont" in notes[0]["texte"])
        candidat_a_traite = next(c for c in store.list_candidats_lieux("accepte") if c.id == candidat_a.id)
        check("acceptation : candidat marqué 'accepte', tiers_lieu_id et traite_par posés",
              candidat_a_traite.tiers_lieu_id == lieu.id and candidat_a_traite.traite_par == "admin@x.org")

        # --- acceptation d'un candidat dont le nom correspond à un lieu déjà réel et alimenté ---
        vrai_lieu = store.get_or_create_tiers_lieu("proprietaire-reel", "Lieu Avec Vraies Données")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=vrai_lieu.id, donnees={"resume": "Vrai résumé, pas celui du candidat."},
            profil_semantique_texte="profil", prompt_version="enrichissement-v3", model="m", source_hash="h"))
        candidat_conflit = store.save_candidat_lieu(CandidatLieu(
            nom="Lieu Avec Vraies Données", description="Résumé venant du document extrait", source_label="s"))
        lieu_conflit = accepter_candidat(store, candidat_conflit, "admin@x.org")
        check("acceptation sur un lieu déjà réel : rattaché, pas de doublon", lieu_conflit.id == vrai_lieu.id)
        check("acceptation sur un lieu déjà réel : sa synthèse existante n'est jamais écrasée",
              store.get_lieu_derive(vrai_lieu.id).donnees["resume"] == "Vrai résumé, pas celui du candidat."
              and store.get_lieu_derive(vrai_lieu.id).prompt_version == "enrichissement-v3")

        # --- rejet ---
        rejeter_candidat(store, candidat_b.id, "admin@x.org")
        check("rejet : candidat marqué 'rejete', aucun lieu créé",
              next(c for c in store.list_candidats_lieux("rejete") if c.id == candidat_b.id).tiers_lieu_id is None
              and not any(l.nom == "Nouveau Lieu B" for l in store.list_tiers_lieux()))
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
