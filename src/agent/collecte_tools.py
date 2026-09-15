"""Tools Claude pour l'agent de collecte : démarrage/reprise de session,
lecture de la section courante (déjà résolue), sauvegarde des réponses et
des notes libres. Toute la logique conditionnelle est déléguée à
`questionnaire.resolver` — l'agent ne voit jamais le schéma brut.

La progression (module courant, section courante, sections déjà terminées)
est chargée depuis la session persistée à l'initialisation, ce qui permet une
reprise exacte après interruption — voir `db.store.SessionEntretien`.
"""

from __future__ import annotations

import unicodedata
from typing import Optional

from ..db.store import SessionEntretien, Store
from ..questionnaire.resolver import (
    country_code_for,
    field_is_active,
    next_incomplete_section,
    next_module,
    resolve_section_fields,
    section_is_complete,
)
from ..questionnaire.schema import QUESTIONNAIRE, Role, all_fields, get_field, get_module, get_section

PRIORITY_MODULE_ID = "__priorite__"

# Sigles/abréviations du jargon tiers-lieux fréquemment employés à l'oral
# mais absents tels quels des libellés du schéma (qui les épellent en
# toutes lettres) — sans ça, un recouvrement de mots simple ne peut jamais
# relier "ETP" à "équivalents temps plein", exactement le cas qui a motivé
# cet outil (un effectif mentionné en passant, jamais rattaché au bon champ).
_SYNONYMES_CHAMPS = {
    "etp": "equivalent temps plein effectif salarie",
    "ca": "chiffre affaires",
    "asbl": "association sans but lucratif statut juridique",
    "scic": "societe cooperative interet collectif statut juridique",
    "scop": "societe cooperative participative statut juridique",
}


def _normaliser(texte: str) -> str:
    """Minuscules, accents retirés, sigles courants développés — pour que le
    recouvrement de mots dans find_matching_field ne dépende pas d'une
    orthographe ou d'une casse exactement identique entre la question posée
    à l'agent et le libellé du champ."""
    sans_accents = unicodedata.normalize("NFKD", texte.lower()).encode("ascii", "ignore").decode()
    mots = sans_accents.split()
    developpes = []
    for m in mots:
        developpes.append(m)
        if m in _SYNONYMES_CHAMPS:
            developpes.append(_SYNONYMES_CHAMPS[m])
    return " ".join(developpes)

TOOL_DEFINITIONS = [
    {
        "name": "get_current_section",
        "description": (
            "Renvoie la section actuellement à traiter dans l'entretien (titre, "
            "introduction, et la liste des questions actives pour ce répondant "
            "précis — déjà filtrées selon son rôle, le pays du lieu, et les "
            "réponses déjà données). Appeler ce tool au début de la conversation "
            "et après chaque changement de section. Le champ 'milieu', quand une "
            "adresse belge est déjà connue, peut porter une clé 'suggestion' "
            "(commune + milieu probable d'après des données officielles) — "
            "toujours une proposition à faire confirmer, jamais à poser comme un "
            "fait acquis."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_answer",
        "description": (
            "Enregistre la réponse d'un champ du schéma pour ce répondant. "
            "N'appeler que pour un champ effectivement retourné par "
            "get_current_section. Après l'appel, vérifier si la section est "
            "complète (le résultat l'indique) avant de continuer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "champ_id": {"type": "string", "description": "id exact du champ, tel que renvoyé par get_current_section"},
                "valeur": {"description": "valeur donnée par le répondant (texte, nombre, booléen, ou liste pour un choix multiple)"},
                "confidentiel": {"type": "boolean", "description": "true si le répondant souhaite que cette donnée reste confidentielle (par défaut la valeur par défaut du champ s'applique)"},
            },
            "required": ["champ_id", "valeur"],
        },
    },
    {
        "name": "save_free_text_note",
        "description": (
            "Capture un témoignage, une anecdote ou un ressenti qui sort du "
            "cadre des champs structurés du schéma — à utiliser librement dès "
            "que le répondant partage quelque chose d'intéressant qui ne rentre "
            "dans aucun champ précis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texte": {"type": "string"},
                "section_id": {
                    "type": "string",
                    "description": (
                        "section en cours, si pertinent. Utiliser \"bonne_pratique\" à la place "
                        "quand le texte capturé est un retour d'expérience concret et réutilisable "
                        "par un autre lieu (montage financier, partenariat, dispositif de "
                        "gouvernance...), plutôt qu'une anecdote générique."
                    ),
                },
            },
            "required": ["texte"],
        },
    },
    {
        "name": "find_matching_field",
        "description": (
            "Cherche si une information donnée SPONTANÉMENT par le répondant, en dehors du fil "
            "normal de la section en cours (une donnée précise glissée en passant pendant qu'il "
            "parle d'autre chose — un effectif, une date, un statut, un montant), correspond à un "
            "champ précis du schéma, même hors de la section en cours. Renvoie une courte liste de "
            "champs candidats (id + libellé) dont le libellé se rapproche des mots-clés donnés. "
            "N'appeler QUE pour vérifier une correspondance sur une info déjà donnée — jamais pour "
            "explorer le schéma ou décider quoi demander ensuite (get_current_section reste la "
            "seule source pour ça). Si un champ correspond clairement, enregistre-le avec "
            "save_answer (ça fonctionne même hors section en cours) en plus, si pertinent, d'une "
            "note libre pour le contexte qualitatif qui ne rentre dans aucun champ."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mots_cles": {
                    "type": "string",
                    "description": "quelques mots décrivant le sujet de l'info (ex. \"nombre d'ETP\", \"date d'ouverture\")",
                },
            },
            "required": ["mots_cles"],
        },
    },
    {
        "name": "rechercher_connaissances_existantes",
        "description": (
            "Cherche si quelque chose est déjà documenté sur CE lieu dans la base de connaissances "
            "de la plateforme (articles Trois-Tiers, rapports déposés par des admins, retours "
            "d'expérience d'autres entretiens) — à appeler UNE FOIS, tôt dans l'entretien, dès que "
            "le nom du lieu est connu. Renvoie les 3 passages les plus proches par similarité "
            "sémantique, MÊME s'ils ne parlent pas vraiment de ce lieu (recherche non filtrée) — "
            "c'est à toi de juger si un extrait renvoyé parle bien de CE lieu précis avant de t'en "
            "servir : un nom de lieu très générique ou un extrait qui parle visiblement d'autre "
            "chose ne doit jamais être présenté. Un extrait pertinent reste une SUGGESTION à faire "
            "confirmer, jamais un fait imposé ni enregistré directement : présente-le comme "
            "\"d'après nos données, ... — c'est bien ça ?\" et enregistre ce que le répondant "
            "confirme ou corrige avec save_answer, pas la suggestion telle quelle. Rien de "
            "pertinent ? Dis simplement que tu pars de zéro pour ce lieu, sans insister ni "
            "réessayer avec d'autres mots-clés."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nom_lieu": {"type": "string", "description": "nom du lieu tel que donné par le répondant"},
            },
            "required": ["nom_lieu"],
        },
    },
    {
        "name": "rechercher_web",
        "description": (
            "Recherche sur le web public (au-delà de la plateforme) — à utiliser avec parcimonie, "
            "typiquement quand `rechercher_connaissances_existantes` n'a rien donné de pertinent ET "
            "qu'une information basique manque encore (adresse, site du lieu). Renvoie jusqu'à 3 "
            "résultats (titre, url, extrait) — des pistes à examiner et proposer au répondant pour "
            "CONFIRMATION, jamais des faits à enregistrer directement : n'invente jamais une "
            "adresse précise à partir d'un simple extrait de résultat, demande toujours "
            "confirmation avant `save_answer`. Peut renvoyer une liste vide (recherche non "
            "disponible, ou rien de pertinent) — dans ce cas, continue normalement en posant la "
            "question au répondant, sans réessayer avec d'autres mots-clés."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "requête de recherche, ex. \"Ma Ferme tiers-lieu Belgique\"",
                },
            },
            "required": ["requete"],
        },
    },
    {
        "name": "skip_optional_module",
        "description": (
            "À appeler si le répondant décline explicitement de continuer avec "
            "le module optionnel proposé (Impact ou Diagnostic). Passe à la "
            "suite ou termine l'entretien s'il n'y a plus de module."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"module_id": {"type": "string", "enum": ["impact", "diagnostic"]}},
            "required": ["module_id"],
        },
    },
]


class CollecteToolHandler:
    """Lie les tools ci-dessus à une session concrète (lieu + contributeur + rôle).

    La progression est initialisée depuis `session` (chargée par
    `store.get_or_start_session`), pas recalculée par déduction — c'est ce qui
    garantit une reprise exacte, y compris pour une section dont tous les
    champs seraient optionnels (qui serait sinon considérée "complète" à tort
    dès qu'on la regarde)."""

    def __init__(self, store: Store, tiers_lieu_id: str, contributeur_id: str, session: SessionEntretien, role: Role,
                 mode_entretien: str = "histoire"):
        self.store = store
        self.tiers_lieu_id = tiers_lieu_id
        self.contributeur_id = contributeur_id
        self.session_id = session.id
        self.role = role
        self.mode_entretien = mode_entretien
        self._module_id: Optional[str] = session.module_courant
        self._section_id: Optional[str] = session.section_courante
        self._completed_section_ids: set = set(session.completed_sections or [])
        if self._module_id is None:
            self._enter_module(QUESTIONNAIRE[0].id, persist=False)
        # Champs de campagnes prioritaires actives (recensement ciblé avec
        # fenêtre temporelle, configuré par un admin) : proposés avant la
        # progression normale du questionnaire, tant qu'il en reste
        # d'inactif pour ce contributeur. Recalculé une fois par session
        # (pas besoin de suivre l'évolution des campagnes en cours de route).
        self._priority_field_ids: list = self._compute_priority_field_ids()
        # Choix explicite du répondant en début d'entretien ("Rendre visible
        # des besoins actuels") : mêmes champs que la section diagnostic
        # normale (aucune duplication de schéma), juste proposés en premier
        # via le même mécanisme de section synthétique que les campagnes —
        # pas un chemin de code séparé.
        if mode_entretien == "besoins":
            besoins_section = get_section("diagnostic", "diagnostic_besoins_futurs")
            besoins_ids = [f.id for f in (besoins_section.fields if besoins_section else [])
                           if f.id not in self._priority_field_ids]
            self._priority_field_ids = besoins_ids + self._priority_field_ids
        self._priority_active: bool = bool(self._priority_field_ids)
        # Questions "libre::" (collées par un admin, hors schéma) répondues
        # pendant CETTE session — sans schéma derrière, get_answers() ne les
        # verra jamais (réponse capturée en note libre, pas en reponses
        # structurées), donc rien d'autre ne marque qu'elles sont déjà
        # traitées d'un appel à l'autre.
        self._libres_repondues: set = set()

    def campagne_completion(self) -> Optional[dict]:
        """% de complétion du formulaire de campagne prioritaire en cours —
        None si le mode n'est pas "campagne" ou qu'aucune campagne n'est
        active, pour que l'appelant n'affiche une barre de progression que
        quand elle porte sur un formulaire borné et concret. Pour
        l'entretien général ("histoire"/"besoins"), le % équivalent calculé
        sur tout le schéma (126 questions) n'a pas de ligne d'arrivée
        naturelle et se lit comme décourageant plutôt qu'utile — pas affiché
        du tout dans ce cas plutôt que d'induire en erreur sur ce qu'il
        mesure. Seuls les champs actuellement actifs comptent dans le total
        (même logique que resolver.completion_stats) : un champ de suivi
        conditionnel pas encore débloqué ne doit pas pénaliser le score."""
        if self.mode_entretien != "campagne" or not self._priority_field_ids:
            return None
        answers = self._current_answers()
        total = 0
        repondus = 0
        for champ_id in self._priority_field_ids:
            if not champ_id.startswith("libre::"):
                f = get_field(champ_id)
                if f is None or not field_is_active(f, answers, self.role):
                    continue
            total += 1
            if self._priority_field_done(champ_id, answers):
                repondus += 1
        if total == 0:
            return None
        return {"total": total, "repondus": repondus, "pourcentage": round(100 * repondus / total)}

    def _compute_priority_field_ids(self) -> list:
        ids: list = []
        for campagne in self.store.get_active_campagnes_prioritaires():
            for champ_id in campagne.champ_ids:
                if champ_id in ids:
                    continue
                if champ_id.startswith("libre::") or get_field(champ_id) is not None:
                    ids.append(champ_id)
        return ids

    def _current_answers(self) -> dict:
        return self.store.get_answers(self.tiers_lieu_id, self.contributeur_id)

    def _country_code(self) -> Optional[str]:
        answers = self._current_answers()
        return country_code_for(answers.get("pays"))

    def _persist_progress(self, statut: str = "en_cours") -> None:
        self.store.update_session_progress(
            self.session_id, self._module_id, self._section_id,
            sorted(self._completed_section_ids), statut=statut,
        )

    def _enter_module(self, module_id: str, persist: bool = True) -> None:
        """Positionne la session sur la première section active et non terminée
        de ce module (ou aucune section si le module est déjà entièrement fait)."""
        self._module_id = module_id
        answers = self._current_answers()
        section = next_incomplete_section(
            get_module(module_id), answers, self.role, self._country_code(), self._completed_section_ids,
            seed=self.contributeur_id,
        )
        self._section_id = section.id if section else None
        if persist:
            self._persist_progress()

    def _priority_field_done(self, champ_id: str, answers: dict) -> bool:
        """Une question "libre::" (collée par un admin, hors schéma) n'a pas
        de champ structuré derrière : sa réponse part en note libre et ne
        peut donc pas être détectée via `answers` — on la suit nous-mêmes,
        pour la session en cours seulement (voir _libres_repondues)."""
        if champ_id.startswith("libre::"):
            return champ_id in self._libres_repondues
        return answers.get(champ_id) is not None

    def _priority_section(self) -> Optional[dict]:
        """Section synthétique construite à la volée à partir des campagnes
        prioritaires actives — pas une modification du schéma statique."""
        answers = self._current_answers()
        restants = [cid for cid in self._priority_field_ids if not self._priority_field_done(cid, answers)]
        if not restants:
            self._priority_active = False
            return None
        fields = []
        for champ_id in restants:
            if champ_id.startswith("libre::"):
                question = champ_id[len("libre::"):].strip()
                if not question:
                    continue
                fields.append({
                    "id": champ_id, "label": question, "type": "textarea",
                    "options": None, "required": False, "help_text": None, "max_choices": None,
                })
                continue
            f = get_field(champ_id)
            # field_is_active (pas juste allowed_for) : une campagne peut
            # référencer un champ dont la condition dépend d'un autre champ de
            # la même campagne (ex. une question de cadrage "oui/non" suivie
            # de champs de détail visibles seulement si la réponse est "oui")
            # — sans ce filtre, tous les champs de la campagne seraient
            # proposés d'un coup, condition ou pas.
            if f is None or not field_is_active(f, answers, self.role):
                continue
            fields.append({
                "id": f.id, "label": f.label, "type": f.type.value,
                "options": f.resolved_options(self._country_code()),
                "required": f.required, "help_text": f.help_text, "max_choices": f.max_choices,
            })
        if not fields:
            self._priority_active = False
            return None
        return {
            "module_id": PRIORITY_MODULE_ID,
            "module_title": "Collecte prioritaire",
            "module_optional": False,
            "section_id": PRIORITY_MODULE_ID,
            "section_title": "Informations prioritaires du moment",
            "intro": ("Un recensement ciblé est en cours en ce moment : ces informations sont "
                      "particulièrement utiles à collecter en priorité."),
            "fields": fields,
        }

    def get_current_section(self, _input: dict) -> dict:
        if self._priority_active:
            section = self._priority_section()
            if section is not None:
                return section
        if self._section_id is None:
            return self._advance_module(self._module_id)
        module = get_module(self._module_id)
        section = get_section(self._module_id, self._section_id)
        answers = self._current_answers()
        resolved = resolve_section_fields(section, answers, self.role, self._country_code())
        # Un champ déjà répondu (par ce contributeur, ou par un précédent —
        # `answers` fusionne les deux) ne doit jamais être reproposé : l'agent
        # ne voit ici que ce qui reste réellement à demander.
        a_demander = [rf for rf in resolved if answers.get(rf.id) is None]
        if not a_demander and section_is_complete(section, answers, self.role, self._country_code()):
            # Tout est déjà répondu (reprise après interruption, ou lieu déjà
            # documenté par quelqu'un d'autre) : on avance directement plutôt
            # que de renvoyer une section sans aucune question à poser.
            self._completed_section_ids.add(self._section_id)
            next_section = next_incomplete_section(
                module, answers, self.role, self._country_code(), self._completed_section_ids,
                seed=self.contributeur_id,
            )
            if next_section:
                self._section_id = next_section.id
                self._persist_progress()
                return self.get_current_section({})
            return self._advance_module(self._module_id)
        champs = []
        for rf in a_demander:
            champ = {
                "id": rf.id,
                "label": rf.field.label,
                "type": rf.field.type.value,
                "options": rf.options,
                "required": rf.field.required,
                "help_text": rf.field.help_text,
                "max_choices": rf.field.max_choices,
            }
            if rf.id == "milieu" and answers.get("adresse"):
                # Suggestion à CONFIRMER par le répondant, jamais un
                # remplissage silencieux — voir degurba.py sur pourquoi
                # (tentative précédente par géocodage abandonnée pour avoir
                # écrit des valeurs fausses sans supervision).
                from ..degurba import suggerer_milieu
                suggestion = suggerer_milieu(answers["adresse"])
                if suggestion:
                    champ["suggestion"] = suggestion
            champs.append(champ)
        return {
            "module_id": self._module_id,
            "module_title": module.title,
            "module_optional": module.optional,
            "section_id": section.id,
            "section_title": section.title,
            "intro": section.intro,
            "fields": champs,
        }

    def save_answer(self, tool_input: dict) -> dict:
        champ_id = tool_input["champ_id"]
        valeur = tool_input["valeur"]
        confidentiel = bool(tool_input.get("confidentiel", False))
        if champ_id.startswith("libre::"):
            # Question collée par un admin (campagne prioritaire), hors
            # schéma : pas de champ structuré pour la stocker, on la capture
            # comme une note libre plutôt qu'une réponse.
            question = champ_id[len("libre::"):].strip()
            texte = f"{question}\n→ {valeur}" if question else str(valeur)
            self.store.save_free_text_note(self.tiers_lieu_id, self.contributeur_id, PRIORITY_MODULE_ID, texte)
            self._libres_repondues.add(champ_id)
        else:
            self.store.save_answer(self.tiers_lieu_id, self.contributeur_id, champ_id, valeur, confidentiel)
            if champ_id in ("pays", "region") and valeur:
                # Synchronise vers la fiche du lieu elle-même (tiers_lieux.pays/
                # region), pas seulement la réponse structurée — sans ça, un lieu
                # créé via l'entretien (pas importé) n'a jamais ces colonnes
                # renseignées : filtres Pays/Région de l'Annuaire inopérants pour
                # lui, alors même que la réponse existe bien (vécu : "Chateau du
                # Feÿ" invisible dès qu'un filtre pays était actif, malgré un
                # entretien complet). Même mécanisme que l'import CommunEcter/CSV,
                # simplement déclenché ici par l'entretien plutôt qu'un script.
                self.store.update_tiers_lieu(self.tiers_lieu_id, **{champ_id: valeur})
            elif champ_id == "adresse" and valeur:
                # Géocode l'adresse texte en lat/lon (Nominatim) et les pose
                # sur la fiche du lieu — sans ça, un lieu créé via l'entretien
                # n'a jamais de coordonnées (contrairement à un import
                # CommunEcter), donc n'apparaît jamais sur la carte de
                # l'Annuaire (vécu : aucun des lieux français, entrés
                # uniquement via l'entretien, n'avait de coordonnées). Ne
                # bloque jamais l'enregistrement de la réponse en cas d'échec
                # réseau ou d'adresse introuvable (geocoder_adresse renvoie
                # None plutôt que de lever).
                from ..geocoding import geocoder_adresse
                pays_connu = self._current_answers().get("pays")
                coords = geocoder_adresse(valeur, pays_connu)
                if coords:
                    self.store.update_tiers_lieu(
                        self.tiers_lieu_id, latitude=coords[0], longitude=coords[1],
                    )

        if self._priority_active and champ_id in self._priority_field_ids:
            section = self._priority_section()
            result = {"saved": True, "champ_id": champ_id, "section_complete": section is None}
            if section is None:
                result["next_section"] = self.get_current_section({})
            return result

        section = get_section(self._module_id, self._section_id)
        answers = self._current_answers()
        complete = section_is_complete(section, answers, self.role, self._country_code())
        result = {"saved": True, "champ_id": champ_id, "section_complete": complete}
        if complete:
            self._completed_section_ids.add(self._section_id)
            next_section = next_incomplete_section(
                get_module(self._module_id), answers, self.role, self._country_code(), self._completed_section_ids,
                seed=self.contributeur_id,
            )
            if next_section:
                self._section_id = next_section.id
                self._persist_progress()
                result["next_section"] = self.get_current_section({})
            else:
                result.update(self._advance_module(self._module_id))
        else:
            self._persist_progress()
        return result

    def _advance_module(self, current_module_id: str) -> dict:
        nxt = next_module(current_module_id)
        if nxt is None:
            self._module_id = current_module_id
            self._section_id = None
            self._persist_progress(statut="terminee")
            return {"module_complete": True, "questionnaire_termine": True}
        self._enter_module(nxt.id)
        return {
            "module_complete": True,
            "next_module_proposed": {"id": nxt.id, "title": nxt.title, "optional": nxt.optional},
        }

    def save_free_text_note(self, tool_input: dict) -> dict:
        self.store.save_free_text_note(
            self.tiers_lieu_id, self.contributeur_id, tool_input.get("section_id"), tool_input["texte"]
        )
        return {"saved": True}

    def find_matching_field(self, tool_input: dict) -> dict:
        """Recherche par mots-clés (recouvrement de mots normalisés, pas
        d'embeddings — surdimensionné pour vérifier une correspondance
        ponctuelle) parmi TOUS les champs du schéma actifs pour ce rôle,
        indépendamment de la section en cours. Volontairement une recherche
        à la demande plutôt qu'exposer le schéma complet en continu : l'agent
        ne le consulte que quand une info semble correspondre à une question
        précise déjà connue, jamais pour explorer ce qui reste à demander."""
        # Longueur minimale 4 des deux côtés : sans elle, un mot très court
        # d'un libellé ("en", "la", "qui"...) matche comme sous-chaîne de
        # presque n'importe quel mot plus long de la requête, noyant les
        # vrais candidats sous des correspondances sans rapport.
        mots = {m for m in _normaliser(tool_input["mots_cles"]).split() if len(m) >= 4}
        candidats = []
        for _module, _section, f in all_fields():
            if not f.allowed_for(self.role):
                continue
            libelle_mots = {m for m in _normaliser(f.label).split() if len(m) >= 4}
            score = sum(
                2 if m == lm else (1 if len(m) >= 6 and len(lm) >= 6 and (m in lm or lm in m) else 0)
                for m in mots for lm in libelle_mots
            )
            if score > 0:
                candidats.append((score, f))
        candidats.sort(key=lambda t: t[0], reverse=True)
        return {
            "champs": [{"id": f.id, "label": f.label} for _score, f in candidats[:5]],
        }

    def rechercher_connaissances_existantes(self, tool_input: dict) -> dict:
        """Recherche sémantique (Voyage + Chroma, même index que la
        Bibliothèque) sur le nom du lieu dans TOUTE la base de connaissances
        — articles Trois-Tiers, rapports déposés, bonnes pratiques d'autres
        entretiens. But : éviter qu'un répondant reparte de zéro pour un
        lieu déjà documenté ailleurs sur la plateforme, sans jamais imposer
        cette info (voir la règle dédiée dans collecte_agent.SYSTEM_PROMPT —
        toujours une suggestion à confirmer). Dégrade en liste vide si
        VOYAGE_API_KEY n'est pas configuré ou en cas d'erreur réseau : ce
        croisement reste un bonus, jamais un prérequis pour continuer
        l'entretien."""
        try:
            from .embeddings import VoyageEmbedder
            from .vectorstore import ChromaStore

            embedder = VoyageEmbedder()
            embedding = embedder.embed_query(tool_input["nom_lieu"])
            hits = ChromaStore().query(embedding, top_k=3)
        except Exception:
            return {"resultats": []}
        # Pas de seuil numérique sur la distance : l'échelle réelle rendue
        # par Chroma/Voyage n'est pas une similarité cosinus bornée [0,1]
        # exploitable telle quelle (une correspondance exacte peut afficher
        # une distance proche de 1, pas de 0) — un seuil arbitraire écartait
        # à tort de vrais résultats pertinents. Les k plus proches sont
        # toujours renvoyés ; c'est à l'agent de juger si le texte renvoyé
        # parle vraiment de CE lieu avant de le présenter (voir la règle
        # dédiée dans collecte_agent.SYSTEM_PROMPT).
        return {
            "resultats": [
                {"source": h["metadata"].get("source_file", "source inconnue"), "extrait": h["text"]}
                for h in hits
            ],
        }

    def rechercher_web(self, tool_input: dict) -> dict:
        """Recherche web publique (API Brave Search) — voir web_crawl.
        rechercher_web pour la dégradation silencieuse si non configuré."""
        from .web_crawl import rechercher_web as _rechercher_web

        return {"resultats": _rechercher_web(tool_input["requete"])}

    def skip_optional_module(self, tool_input: dict) -> dict:
        module_id = tool_input["module_id"]
        return self._advance_module(module_id)

    def execute(self, tool_name: str, tool_input: dict) -> dict:
        handler = getattr(self, tool_name, None)
        if handler is None:
            return {"error": f"tool inconnu: {tool_name}"}
        return handler(tool_input)
