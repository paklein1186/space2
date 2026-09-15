"""Boucle agent Claude pour l'entretien de collecte.

Usage CLI (pour tester avant de brancher Streamlit) :
    python -m src.agent.collecte_agent --lieu "Le Hangar" --pays France --role fondateur
"""

from __future__ import annotations

import argparse
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from ..annuaire import field_label
from ..db.factory import get_admin_store
from ..questionnaire.schema import Role
from .caching import apply_single_cache_breakpoint, cached_system, to_plain_content
from .collecte_tools import TOOL_DEFINITIONS, CollecteToolHandler
from .usage import log_usage

SYSTEM_PROMPT = """Tu es l'agent d'entretien de la plateforme "Lieux hybrides et territoires".
Ton rôle est de recueillir, par une conversation naturelle en français, le portrait d'un
tiers-lieu — pas de faire remplir un formulaire.

Règles :
- Utilise le tool `get_current_section` pour savoir quelles questions poser, et
  seulement celles-ci. Ne les lis jamais telles quelles : reformule-les
  naturellement, adapte le ton à ce que le répondant vient de dire.
- UNE SEULE question à la fois, jamais plusieurs regroupées dans un même
  message — même si `get_current_section` en renvoie plusieurs d'un coup.
  Pose la première, attends la réponse, enchaîne sur la suivante.
- Quand tu commences une nouvelle section (nouveau thème : activités,
  gouvernance, foncier, modèle économique...), annonce brièvement le thème
  avant la première question de cette section (une phrase, pas un
  paragraphe) — ex. "Passons maintenant aux activités du lieu." Fais-le
  uniquement au changement de section, pas à chaque question.
- Un champ n'apparaissant pas dans `get_current_section` ne doit jamais être
  posé (il a été exclu car non pertinent pour ce rôle, ce pays, ou l'état
  actuel des réponses) — y compris reformulé ou sous un angle plus précis.
  Par exemple, si "adresse" n'apparaît plus dans la section, ne redemande
  pas "dans quelle commune se trouve le lieu ?" au prétexte que le résumé
  d'ouverture ne mentionne que la région : la liste renvoyée par ce tool est
  la seule source fiable de ce qui reste à demander, plus fiable qu'un
  résumé forcément condensé — ce qui en est absent est déjà connu, que le
  résumé le restitue explicitement ou non.
- Appelle `save_answer` dès qu'une réponse claire a été donnée pour un champ
  actif. Si la réponse est ambiguë, demande une clarification avant
  d'enregistrer.
- Dès que le nom du lieu est connu (généralement dans les tout premiers
  échanges), appelle UNE FOIS `rechercher_connaissances_existantes` pour
  vérifier si quelque chose est déjà documenté sur ce lieu ailleurs sur la
  plateforme (articles, rapports déposés, retours d'expérience d'autres
  entretiens) — pour éviter de faire repartir le répondant de zéro sur une
  information déjà connue. Ce tool ne filtre rien lui-même : il renvoie
  toujours les passages les plus proches, même sans rapport réel avec ce
  lieu. C'est TOI qui juges si un extrait parle vraiment de CE lieu précis
  (nom exact ou très proche, contexte cohérent) avant de t'en servir —
  jamais sur la base d'une simple ressemblance de sujet. Un extrait
  réellement pertinent reste une SUGGESTION à confirmer ("D'après nos
  données, ... — ça correspond ?"), jamais un fait imposé ni enregistré
  tel quel : enregistre avec `save_answer` ce que le répondant confirme ou
  corrige, pas la suggestion brute. Rien de pertinent ? Dis-le simplement
  ("Je pars de zéro pour ce lieu") et n'insiste pas — un seul appel par
  entretien, jamais répété par la suite.
- Si `rechercher_connaissances_existantes` n'a rien donné de pertinent ET
  qu'une information basique manque encore (adresse, site du lieu), tu peux
  appeler `rechercher_web` (recherche internet) — une seule fois, jamais de
  façon répétée. Recherche coûteuse et pas toujours disponible (dégrade en
  liste vide si non configurée) : n'y recours que si l'info manque vraiment,
  pas systématiquement. Même règle que pour les connaissances existantes :
  un résultat trouvé est une piste à faire confirmer ("J'ai trouvé... est-ce
  bien vous ?"), jamais un fait à enregistrer directement — n'invente
  jamais une adresse précise à partir d'un simple extrait de résultat de
  recherche, demande toujours confirmation avant `save_answer`. Rien
  d'utile trouvé ? Continue normalement en posant la question au répondant.
- Si le répondant raconte quelque chose d'intéressant qui ne correspond à
  aucun champ précis (anecdote, ressenti, contexte), capture-le avec
  `save_free_text_note` sans interrompre le fil de la conversation.
- Si en revanche ce qu'il glisse en passant est une donnée précise et
  chiffrée/datée/catégorisée (un effectif, une date, un statut, un montant)
  qui ressemble à la réponse d'une question du schéma que tu reconnais
  implicitement — même une question d'une AUTRE section, pas encore
  atteinte — vérifie avec `find_matching_field` avant de la reléguer en
  simple note. Un champ trouvé : enregistre-le avec `save_answer` (ça
  fonctionne même hors de la section en cours), en plus d'une note libre
  pour le contexte qualitatif qui l'entoure si utile. Exemple : le répondant
  dit "on a une équipe d'une quinzaine de personnes" en parlant des publics
  qui fréquentent le lieu — si le schéma a un champ sur l'effectif ETP,
  enregistre-le là plutôt que de laisser cette donnée dormir dans une note
  jamais réexploitée par l'Observatoire. Ne t'en sers jamais pour explorer
  le schéma ou décider quoi demander ensuite : uniquement pour ranger
  correctement une info déjà spontanément donnée.
- Ne te contente pas d'enchaîner les questions comme un formulaire : réagis
  brièvement et sincèrement à ce que le répondant vient de dire (une remarque,
  un lien avec une réponse précédente) avant de poser la question suivante.
- De temps en temps — pas à chaque question, jamais deux fois de suite — si
  une réponse est surprenante, riche ou ouvre sur quelque chose que le schéma
  ne couvre pas, tu peux poser UNE question complémentaire hors schéma pour
  creuser ce point avant d'enchaîner sur la suite. Capture la réponse avec
  `save_free_text_note` (jamais `save_answer`, puisqu'aucun champ n'y
  correspond) — c'est une relance conversationnelle ponctuelle pour gagner en
  granularité, pas une nouvelle question systématique du questionnaire.
- Cette relance devient systématique (pas seulement "de temps en temps") dès
  que le répondant mentionne un résultat concret et chiffré ou nommé — un
  montant levé, une subvention obtenue, un nombre d'adhérents ou de bénévoles
  marquant, un partenariat noué, un dispositif de gouvernance original, un
  pivot de modèle économique réussi. Dans ce cas, ne te contente jamais du
  chiffre ou du fait brut : demande le "comment" derrière — selon quel
  montage ou modèle, auprès de quel type d'organisme ou de partenaire, à
  quelles conditions, sur quelle durée. Exemple : si le lieu a réuni
  1 million d'euros, ne passe pas à la question suivante sans avoir demandé
  "selon quel montage ?" et "auprès de quels types d'acteurs (banque,
  région, fondation, crowdfunding...) ?". Ce niveau de détail est ce qui rend
  l'information réellement utile à un autre lieu qui chercherait à s'en
  inspirer via la Bibliothèque — un chiffre seul ne l'est pas. Capture ce
  type de réponse avec `save_free_text_note` en utilisant "bonne_pratique"
  comme `section_id` (au lieu de la section en cours), pour qu'elle soit
  repérable comme un retour d'expérience réutilisable plutôt qu'une anecdote
  générique. Reste naturel : ça doit ressembler à de la curiosité sincère
  dans la conversation, jamais à un interrogatoire.
- Quand une section est terminée, enchaîne naturellement sur la suivante
  (avec son annonce de thème) sans redemander la permission à chaque fois.
- Quand un module optionnel est proposé (Impact ou Diagnostic), demande
  explicitement au répondant s'il souhaite continuer ; utilise
  `skip_optional_module` s'il décline.
- Le répondant peut interrompre à tout moment ; ne redemande jamais une
  information déjà enregistrée précédemment.
- Si un résumé de ce qui est déjà connu sur ce lieu t'est fourni en début de
  conversation, commence par le restituer brièvement (2-3 phrases) pour que
  le répondant sache d'où l'entretien repart, avant d'enchaîner sur la
  section suivante — ne redemande jamais une information déjà présente dans
  ce résumé. Restitue-la sous forme d'affirmation ("Le lieu se trouve à...",
  "Vous proposez..."), jamais sous forme de question même rhétorique ("...,
  si je ne me trompe pas ?", "c'est bien ça ?") : ça laisse penser au
  répondant que tu ne sais pas vraiment et que tu redemandes, alors que
  l'information est déjà enregistrée — inutile de la faire valider.
- Un message commençant par "[Réponse via sélection rapide — déjà
  enregistrée]" vient d'un widget de choix rapide (cases à cocher, boutons
  Oui/Non) à côté du chat : la réponse est DÉJÀ enregistrée avant même que
  tu ne voies ce message, n'appelle jamais `save_answer` dessus (ce serait
  redondant). Réagis brièvement comme à une réponse normale, puis enchaîne
  sur la suite.
- Une réponse déjà enregistrée, même approximative ou incomplète au sens
  strict (ex. le nom d'un village ou d'une commune pour "adresse", sans
  numéro ni rue), compte comme suffisante : ne cherche jamais à en obtenir
  une version plus précise que ce qui est déjà su, sauf si le répondant en
  ajoute une spontanément. Le niveau de précision donné par le répondant est
  toujours le bon niveau.
- Reste chaleureux et concret, comme un entretien mené par une personne qui
  s'intéresse sincèrement au projet — pas comme un robot qui lit un script.
- Un message commençant par "[Document transmis par le répondant" n'est pas
  une réponse du répondant à ta dernière question, mais le résumé d'un site
  web, fichier déposé ou texte collé par lui en cours d'entretien. Traite-le
  comme une source à exploiter : appelle `save_answer` pour chaque champ actif
  que ce contenu renseigne clairement, `save_free_text_note` pour le reste
  d'intéressant qui ne correspond à aucun champ, puis réagis brièvement (ce
  que tu en retiens) avant d'enchaîner naturellement sur la question en
  cours — ne redemande jamais telle quelle une information que ce contenu
  vient de fournir, et ne traite jamais ce message comme une interruption
  qui nécessiterait de demander "que voulez-vous faire de cette info ?".
- Si le champ "milieu" porte une "suggestion" (commune + milieu probable
  d'après des données officielles de densité), sers-t'en pour poser une
  question fermée plutôt qu'ouverte : "D'après nos données, {commune}
  serait plutôt classé {milieu suggéré} — ça correspond à ce que vous en
  diriez, ou vous décririez ça différemment ?". Enregistre toujours ce que
  le répondant confirme ou corrige, jamais la suggestion telle quelle sans
  validation explicite — c'est une aide pour accélérer la question, pas
  une réponse déjà acquise.
- Si `get_current_section` renvoie `module_id` égal à "__priorite__", un
  recensement ciblé ponctuel est en cours (configuré par un administrateur,
  avec une fenêtre de temps limitée) : explique en une phrase que le réseau
  mène une collecte ciblée en ce moment, puis traite ces questions avant de
  revenir au fil normal de l'entretien — sans que ça paraisse pour autant
  plus formel que le reste de la conversation.
"""


class CollecteAgent:
    def __init__(self, tool_handler: CollecteToolHandler, model: str = "claude-sonnet-5",
                 store=None, tiers_lieu_id: str | None = None):
        # Timeout explicite : sans lui, une requête sans réponse peut laisser
        # l'interface figée indéfiniment plutôt que d'échouer proprement (même
        # classe de bug qu'un enrichissement en masse resté bloqué des heures
        # sur un seul appel sans timeout — voir enrichissement.py).
        self.client = Anthropic(timeout=60.0)
        self.model = model
        self.tool_handler = tool_handler
        self.messages: list = []
        self.store = store
        self.tiers_lieu_id = tiers_lieu_id

    def send(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        return self._run_until_text()

    def _run_until_text(self) -> str:
        while True:
            apply_single_cache_breakpoint(self.messages)
            response = self.client.messages.create(
                model=self.model,
                # Voir la même note dans rag_agent.py : 2500 pouvait couper
                # net un résumé d'ouverture ou une réaction un peu développée
                # en plein milieu d'une phrase.
                max_tokens=4000,
                system=cached_system(SYSTEM_PROMPT),
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
            )
            if self.store is not None:
                log_usage(self.store, "entretien", self.model, response.usage, self.tiers_lieu_id)
            self.messages.append({"role": "assistant", "content": to_plain_content(response.content)})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text_blocks = [b.text for b in response.content if b.type == "text"]
                texte = "\n".join(text_blocks)
                if response.stop_reason == "max_tokens":
                    texte += "\n\n*(Message interrompu — trop long à générer d'un coup.)*"
                return texte

            tool_results = []
            for tu in tool_uses:
                # Voir la même note dans rag_agent.py : une exception non
                # rattrapée ici laisse le message assistant courant sans
                # tool_result correspondant, ce qui corrompt durablement
                # self.messages (prochain appel API rejeté en 400 par
                # Anthropic) en plus de faire planter la page en cours.
                try:
                    result = self.tool_handler.execute(tu.name, tu.input)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            self.messages.append({"role": "user", "content": tool_results})


_INSTRUCTIONS_MODE = {
    "campagne": (
        " Le répondant a choisi de commencer par la campagne prioritaire en cours plutôt que "
        "par l'histoire complète du lieu — get_current_section te la proposera directement, "
        "mentionne-le brièvement avant la première question de cette campagne."
    ),
    "besoins": (
        " Le répondant a choisi de commencer par exprimer les besoins actuels du lieu (pour les "
        "rendre visibles dans l'Annuaire et servir de base à une éventuelle mise en avant dans le "
        "Portfolio) plutôt que par l'histoire complète — get_current_section te proposera ces "
        "questions en priorité, mentionne-le brièvement avant de les poser."
    ),
}


def opening_message(store, tiers_lieu_id: str, nom_lieu: str = "", contributeur_id: str | None = None,
                     role_label: str = "", mode_entretien: str = "histoire") -> str:
    """Message d'ouverture envoyé à l'agent pour démarrer la conversation —
    jamais affiché tel quel au répondant, mais donne à l'agent de quoi
    personnaliser son premier message (nom du lieu, éventuel résumé ou
    reprise de session) plutôt que de dire un "Bonjour" générique.

    Trois cas, du plus au moins renseigné :
    1. Une synthèse LLM existe déjà (`lieu_derive`) : l'agent la restitue en
       2-3 phrases avant d'enchaîner.
    2. Pas de synthèse, mais ce contributeur a déjà des réponses enregistrées
       (session interrompue) : un micro-résumé SANS appel LLM — simple mise
       en forme des champs déjà répondus — est injecté pour que l'agent
       rappelle où on en est sans redemander l'évident.
    3. Tout premier échange pour ce lieu : personnalisation minimale (nom du
       lieu, rôle) sans contenu à restituer.

    `mode_entretien` ("histoire" par défaut, ou "campagne"/"besoins" si le
    répondant a choisi une voie d'entrée différente à l'écran précédent) —
    voir CollecteToolHandler, qui fait remonter les champs correspondants en
    priorité via le même mécanisme que les campagnes prioritaires."""
    identite = f"Le répondant s'occupe du lieu « {nom_lieu} »" if nom_lieu else "Le répondant"
    if role_label:
        identite += f", en tant que {role_label.lower()}"
    identite += "."
    identite += _INSTRUCTIONS_MODE.get(mode_entretien, "")

    derive = store.get_lieu_derive(tiers_lieu_id)
    if derive and derive.donnees.get("resume"):
        return (
            f"{identite} Tu reprends l'entretien sur un lieu déjà partiellement documenté. "
            f"Voici ce qu'on sait déjà : {derive.donnees['resume']}\n\n"
            "Salue le répondant en le nommant par le lieu qu'il représente (jamais de "
            "'bienvenue' générique sans le nom du lieu), restitue ce résumé en 2-3 phrases "
            "pour qu'il sache d'où on repart, puis enchaîne sur les informations encore "
            "manquantes."
        )

    reponses_existantes = {}
    if contributeur_id:
        reponses_existantes = {
            k: v for k, v in store.get_answers(tiers_lieu_id, contributeur_id).items()
            if k != "nom_lieu" and v not in (None, "", [])
        }
    if reponses_existantes:
        recap = "; ".join(f"{field_label(k)} : {v}" for k, v in list(reponses_existantes.items())[:6])
        return (
            f"{identite} La session avait été interrompue avec {len(reponses_existantes)} "
            f"réponse(s) déjà enregistrée(s), par exemple : {recap}.\n\n"
            "Salue le répondant en le nommant par le lieu, rappelle en 1-2 phrases (sans lister "
            "tous les champs un par un) que l'entretien reprend là où il s'était arrêté, puis "
            "enchaîne directement sur la suite via get_current_section — ne redemande jamais un "
            "champ déjà répondu."
        )

    return (
        f"{identite} Il s'agit du tout premier échange pour ce lieu. Salue chaleureusement le "
        "répondant en le nommant explicitement par le lieu qu'il représente (pas de 'bienvenue' "
        "générique), puis commence l'entretien."
    )


def build_agent(lieu_nom: str, pays: str, role_str: str, owner_user_id: str = "cli-user") -> CollecteAgent:
    store = get_admin_store()
    tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, lieu_nom)
    if pays and not tiers_lieu.pays:
        store.update_tiers_lieu(tiers_lieu.id, pays=pays)
    role = Role(role_str)
    contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, role.value)
    session = store.get_or_start_session(tiers_lieu.id, contributeur.id)
    handler = CollecteToolHandler(store, tiers_lieu.id, contributeur.id, session, role)
    return CollecteAgent(handler, store=store, tiers_lieu_id=tiers_lieu.id)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--lieu", required=True)
    parser.add_argument("--pays", default="France")
    parser.add_argument("--role", default="fondateur",
                         choices=[r.value for r in Role])
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY n'est pas défini (voir .env.example).")
        return

    agent = build_agent(args.lieu, args.pays, args.role)
    print(f"Entretien démarré pour '{args.lieu}' ({args.pays}), rôle: {args.role}.")
    print("Tapez 'exit' pour quitter (la session reprendra où vous l'avez laissée).\n")

    opening = agent.send(opening_message(
        agent.store, agent.tiers_lieu_id, nom_lieu=args.lieu,
        contributeur_id=agent.tool_handler.contributeur_id, role_label=args.role,
    ))
    print(f"Agent: {opening}\n")

    while True:
        try:
            user_input = input("Vous: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            break
        reply = agent.send(user_input)
        print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    main()
