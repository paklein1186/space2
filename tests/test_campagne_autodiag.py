"""Campagne Autodiagnostic (src/questionnaire/campagne_autodiag.py) et règles
associées, sans réseau ni appel LLM :
- toutes ses questions existent dans le schéma ;
- le pays est demandé en premier, puis les choix s'adaptent au pays
  (statut juridique, question wallonne réservée à la Belgique) ;
- un pays déjà connu pour le lieu n'est pas redemandé ;
- les choix multiples sont stockés en liste, quelle que soit la forme reçue ;
- l'entretien général ne pousse aucune campagne.

Usage : python3 -m tests.test_campagne_autodiag
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import PRIORITY_MODULE_ID, CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.questionnaire import campagne_autodiag
from src.questionnaire.schema import FieldType, Role, get_field


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def _handler(store, nom, mode="campagne", campagne_id=None):
    lieu = store.get_or_create_tiers_lieu("user-" + nom, nom)
    contributeur = store.get_or_create_contributeur("user-" + nom, lieu.id, Role.FONDATEUR.value)
    session = store.get_or_start_session(lieu.id, contributeur.id)
    return lieu, contributeur, CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.FONDATEUR,
                                                   mode_entretien=mode, campagne_id=campagne_id)


def _champ(section, champ_id):
    return next((f for f in section["fields"] if f["id"] == champ_id), None)


def main():
    manquants = [cid for cid in campagne_autodiag.CHAMP_IDS if get_field(cid) is None]
    check("toutes les questions de la campagne existent dans le schéma", manquants == [])
    check("aucune question en double", len(set(campagne_autodiag.CHAMP_IDS)) == len(campagne_autodiag.CHAMP_IDS))
    check("le pays est la première question", campagne_autodiag.CHAMP_IDS[0] == "pays")
    nb_multi = sum(get_field(c).type == FieldType.MULTI_CHOICE for c in campagne_autodiag.CHAMP_IDS)
    check(f"des questions à choix multiples ({nb_multi})", nb_multi >= 10)

    maintenant = datetime.now(timezone.utc)
    debut, fin = (maintenant - timedelta(days=1)).isoformat(), (maintenant + timedelta(days=30)).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "autodiag.sqlite3"))
        campagne = campagne_autodiag.creer_ou_mettre_a_jour(store, debut, fin)
        check("campagne créée avec son code", campagne.code == "autodiag")
        campagne_bis = campagne_autodiag.creer_ou_mettre_a_jour(store, debut, fin)
        check("relancer la création met à jour au lieu de dupliquer",
              campagne_bis.id == campagne.id and len(store.list_campagnes_prioritaires()) == 1)

        # --- lieu belge ---
        _, _, h = _handler(store, "Lieu Belge", campagne_id=campagne.id)
        s = h.get_current_section({})
        check("section prioritaire de la campagne", s["section_id"] == PRIORITY_MODULE_ID)
        check("première question : le pays", s["fields"][0]["id"] == "pays")
        check("question wallonne masquée tant que le pays est inconnu", _champ(s, "laureat_appel_rw") is None)
        h.execute("save_answer", {"champ_id": "pays", "valeur": "Belgique"})
        s = h.get_current_section({})
        statut = _champ(s, "statut_juridique")
        check("Belgique : statuts belges proposés (ASBL)", "ASBL" in statut["options"])
        check("Belgique : pas de statut français", "Association loi 1901" not in statut["options"])
        check("Belgique : question wallonne proposée", _champ(s, "laureat_appel_rw") is not None)
        acteurs = _champ(s, "acteurs_mobilises")
        check("Belgique : acteurs du territoire belges (CPAS)",
              any("CPAS" in o for o in acteurs["options"]))

        # --- lieu français ---
        _, _, h = _handler(store, "Lieu Francais", campagne_id=campagne.id)
        h.execute("save_answer", {"champ_id": "pays", "valeur": "France"})
        s = h.get_current_section({})
        statut = _champ(s, "statut_juridique")
        check("France : statuts français proposés (association loi 1901)", "Association loi 1901" in statut["options"])
        check("France : pas d'ASBL", "ASBL" not in statut["options"])
        check("France : pas de question wallonne", _champ(s, "laureat_appel_rw") is None)

        # --- pays déjà connu (autre contributeur, import…) : pas redemandé ---
        lieu, _, _ = _handler(store, "Lieu Connu", mode="histoire")
        autre = store.get_or_create_contributeur("import", lieu.id, Role.AUTRE.value)
        store.save_answer(lieu.id, autre.id, "pays", "Belgique")
        _, _, h = _handler(store, "Lieu Connu", campagne_id=campagne.id)
        s = h.get_current_section({})
        check("pays déjà connu pour le lieu : pas redemandé", _champ(s, "pays") is None)
        check("… et les choix suivent quand même le pays connu",
              "ASBL" in _champ(s, "statut_juridique")["options"])

        # --- choix multiples : toujours stockés en liste ---
        lieu, contributeur, h = _handler(store, "Lieu Multi", campagne_id=campagne.id)
        h.execute("save_answer", {"champ_id": "fonctions_culture",
                                  "valeur": ["Arts plastiques (espace d'expo, installations)",
                                             "festivals et activités festives"]})
        h.execute("save_answer", {"champ_id": "types_soutien_souhaites",
                                  "valeur": "Aide juridique, Communication"})
        h.execute("save_answer", {"champ_id": "besoin_aide_vision", "valeur": "4"})
        r = store.get_answers(lieu.id, contributeur.id)
        check("liste reçue : stockée en liste, orthographe des options recalée",
              r["fonctions_culture"] == ["Arts plastiques (espace d'expo, installations)",
                                         "Festivals et activités festives"])
        check("texte reçu pour un choix multiple : converti en liste d'options",
              r["types_soutien_souhaites"] == ["Communication", "Aide juridique"])
        check("échelle reçue en texte : stockée en nombre", r["besoin_aide_vision"] == 4)
        s = h.get_current_section({})
        prio = _champ(s, "soutiens_prioritaires")
        check("soutiens prioritaires : débloqué après les besoins, 5 choix maximum",
              prio is not None and prio["max_choices"] == 5)

        # --- l'entretien général ne pousse aucune campagne ---
        for mode in ("histoire", "besoins"):
            _, _, h = _handler(store, f"Lieu {mode}", mode=mode)
            s = h.get_current_section({})
            ids = {f["id"] for f in s["fields"]}
            pousse = s["section_id"] == PRIORITY_MODULE_ID and bool(ids & {"fonctions_culture", "raison_etre"})
            check(f"mode {mode} : aucune question de campagne poussée", not pousse)
            check(f"mode {mode} : pas d'avancement de campagne affiché", h.campagne_completion() is None)

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
