"""Campagnes « Enquête gestionnaires » (coworkings / tiers-lieux,
src/questionnaire/campagne_gestionnaires.py), sans réseau ni appel LLM :
- toutes leurs questions existent, sans doublon ni libellé en double ;
- les grilles détaillées restent hors de l'entretien général ;
- les questions d'évolution sur 3 ans dépendent de l'âge du lieu ;
- le panneau de sélection rapide montre la question en cours, pas une
  question à choix plus loin dans la liste ;
- l'export éclate les choix multiples en une colonne par option.

Usage : python3 -m tests.test_campagne_gestionnaires
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import PRIORITY_MODULE_ID, CollecteToolHandler, champs_choix_rapide
from src.db.sqlite_store import SqliteStore
from src.questionnaire import campagne_gestionnaires as cg
from src.questionnaire.export import colonnes_par_option
from src.questionnaire.resolver import completion_stats
from src.questionnaire.schema import QUESTIONNAIRE, FieldType, Role, field_label, get_field


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def _handler(store, nom, campagne_id):
    lieu = store.get_or_create_tiers_lieu("user-" + nom, nom)
    contributeur = store.get_or_create_contributeur("user-" + nom, lieu.id, Role.FONDATEUR.value)
    session = store.get_or_start_session(lieu.id, contributeur.id)
    return lieu, contributeur, CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.FONDATEUR,
                                                   mode_entretien="campagne", campagne_id=campagne_id)


def _ids(section):
    return [f["id"] for f in section["fields"]]


def main():
    for d in cg.CAMPAGNES:
        manquants = [c for c in d.champ_ids if get_field(c) is None]
        check(f"{d.code} : toutes les questions existent dans le schéma", manquants == [])
        check(f"{d.code} : aucune question en double", len(set(d.champ_ids)) == len(d.champ_ids))
        libelles = [field_label(c) for c in d.champ_ids]
        check(f"{d.code} : libellés distincts (une colonne d'export par question)",
              len(set(libelles)) == len(libelles))
        nb_choix = sum(get_field(c).type in (FieldType.SINGLE_CHOICE, FieldType.MULTI_CHOICE, FieldType.BOOLEAN)
                       for c in d.champ_ids)
        check(f"{d.code} : {len(d.champ_ids)} questions dont {nb_choix} à choix", nb_choix >= 40)
        check(f"{d.code} : l'âge du lieu est demandé avant les questions d'évolution",
              d.champ_ids.index("lieu_existait_3_ans")
              < min(d.champ_ids.index(c) for c in d.champ_ids if c.startswith("evolution_")))

    cw, tl = set(cg.COWORKINGS.champ_ids), set(cg.TIERS_LIEUX.champ_ids)
    check("coworkings : fréquentation par semaine", "frequentation_semaine_type" in cw - tl)
    check("tiers-lieux : fréquentation par mois", "frequentation_mois_type" in tl - cw)
    check("riverains : tiers-lieux seulement", "part_statut_riverain" in tl - cw)
    check("acheter des produits / prendre un verre : tiers-lieux seulement",
          {"motif_acheter_produits", "motif_boire_manger"} <= tl - cw)
    check("animations extraprofessionnelles : coworkings seulement", "motif_animations_extraprofessionnelles" in cw - tl)
    check("bloc économie et emploi dans les deux", set(cg.BLOC_ECONOMIE_EMPLOI) <= cw & tl)
    check("table ronde en dernière question",
          cg.COWORKINGS.champ_ids[-1] == cg.TIERS_LIEUX.champ_ids[-1] == "interet_table_ronde_gestionnaires")
    check("métiers : choix multiple", get_field("metiers_tiers_lieu").type == FieldType.MULTI_CHOICE)
    check("raisons de venue : oui / non / éventuellement",
          get_field("motif_teletravail").options == ["Oui", "Non", "Éventuellement"])

    # Grilles détaillées hors de l'entretien général.
    ids_parcours = {f.id for m in QUESTIONNAIRE for s in m.sections for f in s.fields}
    check("grilles détaillées absentes du parcours général",
          not ({"motif_teletravail", "part_statut_salarie", "metiers_tiers_lieu"} & ids_parcours))
    total_avant = completion_stats({}, None, None)["total"]
    check("taux de complétion général inchangé par ces questions",
          completion_stats({"motif_teletravail": "Oui"}, None, None)["total"] == total_avant)

    # Export : une colonne par option.
    cols = colonnes_par_option("metiers_tiers_lieu", ["Régisseur·se", "Autre", "Cuisinier"])
    label = field_label("metiers_tiers_lieu")
    check("export : option cochée marquée x", cols[f"{label} — Régisseur·se"] == "x")
    check("export : option non cochée vide", cols[f"{label} — Support informatique / numérique"] == "")
    check("export : valeur hors liste dans « précisions »", cols[f"{label} — précisions"] == "Cuisinier")
    check("export : non répondu = colonnes vides", set(colonnes_par_option("metiers_tiers_lieu", None).values()) == {""})
    check("export : pas d'éclatement pour un choix unique", colonnes_par_option("motif_teletravail", "Oui") is None)

    maintenant = datetime.now(timezone.utc)
    debut, fin = (maintenant - timedelta(days=1)).isoformat(), (maintenant + timedelta(days=30)).isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "gestionnaires.sqlite3"))
        campagnes = {d.code: cg.creer_ou_mettre_a_jour(store, d, debut, fin) for d in cg.CAMPAGNES}
        cg.creer_ou_mettre_a_jour(store, cg.COWORKINGS, debut, fin)
        check("deux campagnes créées, relance sans doublon", len(store.list_campagnes_prioritaires()) == 2)
        tl_campagne = campagnes["gestionnaires-tiers-lieux-ruraux"]
        check("campagne tiers-lieux : code et titre",
              tl_campagne.titre == cg.TIERS_LIEUX.titre and len(tl_campagne.champ_ids) == len(tl))

        lieu, contributeur, h = _handler(store, "Ferme Test", tl_campagne.id)
        s = h.get_current_section({})
        check("section prioritaire de la campagne", s["section_id"] == PRIORITY_MODULE_ID)
        check("questions d'évolution masquées tant que l'âge du lieu est inconnu",
              not any(i.startswith("evolution_") for i in _ids(s)))
        check("détail du lancement masqué tant que « seul ? » est sans réponse",
              "modalite_lancement_collectif" not in _ids(s))

        # Panneau de sélection rapide : la question en cours seulement.
        premiere = s["fields"][0]
        check("première question ouverte (nom du lieu)… ", premiere["type"] == "text")
        check("… donc aucun panneau de choix (pas une question plus loin)", champs_choix_rapide(s) == [])
        for champ_id in ("nom_lieu", "adresse", "avantages_localisation", "inconvenients_localisation"):
            h.execute("save_answer", {"champ_id": champ_id, "valeur": "x"})
        s = h.get_current_section({})
        check("question à choix en cours (statut d'occupation) : affichée dans le panneau",
              [f["id"] for f in champs_choix_rapide(s)] == ["statut_occupation"])
        check("hors campagne : comportement inchangé (première question à choix de la section)",
              [f["id"] for f in champs_choix_rapide({"module_id": "socle", "fields": [
                  {"id": "a", "type": "text"}, {"id": "b", "type": "multi_choice"}]})] == ["b"])

        h.execute("save_answer", {"champ_id": "lieu_existait_3_ans", "valeur": True})
        h.execute("save_answer", {"champ_id": "services_proposes",
                                  "valeur": ["Domiciliation d'entreprises", "Espaces de bien-être (yoga, sport, médecine alternative)"]})
        s = h.get_current_section({})
        check("lieu de plus de 3 ans : questions d'évolution proposées",
              {"evolution_part_usagers_commune", "evolution_frequentation_mois"} <= set(_ids(s)))
        check("domiciliation cochée : nombre d'entreprises domiciliées demandé",
              "nombre_entreprises_domiciliees" in _ids(s))
        check("pas de question de la version coworkings", "frequentation_semaine_type" not in _ids(s))

        _, _, h2 = _handler(store, "Lieu Recent", tl_campagne.id)
        h2.execute("save_answer", {"champ_id": "lieu_existait_3_ans", "valeur": False})
        s = h2.get_current_section({})
        check("lieu récent : aucune question d'évolution sur 3 ans",
              not any(i.startswith("evolution_") for i in _ids(s)))

        # Données déjà connues (import) : à confirmer, pas sautées.
        lieu_i = store.get_or_create_tiers_lieu("user-Import", "Lieu Importe")
        import_c = store.get_or_create_contributeur("import", lieu_i.id, Role.AUTRE.value)
        store.save_answer(lieu_i.id, import_c.id, "nom_lieu", "Lieu Importé")
        store.save_answer(lieu_i.id, import_c.id, "adresse", "Rue du Moulin 3, Durbuy")
        store.save_answer(lieu_i.id, import_c.id, "avantages_localisation", "Calme")
        contrib_i = store.get_or_create_contributeur("user-Importe", lieu_i.id, Role.FONDATEUR.value)
        hi = CollecteToolHandler(store, lieu_i.id, contrib_i.id, store.get_or_start_session(lieu_i.id, contrib_i.id),
                                 Role.FONDATEUR, mode_entretien="campagne", campagne_id=tl_campagne.id)
        s = hi.get_current_section({})
        adresse = next(f for f in s["fields"] if f["id"] == "adresse")
        check("adresse importée : reposée pour confirmation, avec la valeur connue",
              adresse.get("brouillon_connu") == "Rue du Moulin 3, Durbuy")
        check("nom importé : première question, signalé comme déjà en partie connu",
              s["fields"][0]["id"] == "nom_lieu"
              and s.get("prochaine_question_deja_en_partie_connue", {}).get("brouillon") == "Lieu Importé")
        check("autre donnée connue (avantages) : toujours sautée", "avantages_localisation" not in _ids(s))
        hi.execute("save_answer", {"champ_id": "adresse", "valeur": "Rue du Moulin 3, 6940 Durbuy"})
        check("adresse confirmée : plus reposée", "adresse" not in _ids(hi.get_current_section({})))
        hi_bis = CollecteToolHandler(store, lieu_i.id, contrib_i.id, store.get_or_start_session(lieu_i.id, contrib_i.id),
                                     Role.FONDATEUR, mode_entretien="campagne", campagne_id=tl_campagne.id)
        s = hi_bis.get_current_section({})
        check("reprise plus tard : l'adresse confirmée n'est pas redemandée, le nom si",
              "adresse" not in _ids(s) and "nom_lieu" in _ids(s))
        autodiag_like = CollecteToolHandler(store, lieu_i.id, contrib_i.id,
                                            store.get_or_start_session(lieu_i.id, contrib_i.id), Role.FONDATEUR,
                                            mode_entretien="histoire")
        check("hors de ces campagnes : rien à confirmer", autodiag_like._champs_a_confirmer == set())

        h.execute("save_answer", {"champ_id": "motif_teletravail", "valeur": "éventuellement"})
        check("réponse oui/non/éventuellement recalée sur l'option",
              store.get_answers(lieu.id, contributeur.id)["motif_teletravail"] == "Éventuellement")
        check("répondant compté dans la campagne",
              (lieu.id, contributeur.id) in store.get_repondants_campagne(tl_campagne.id))

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
