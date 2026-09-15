"""Interface Streamlit : entretien de collecte, annuaire/cartographie, et
(à venir) assistant RAG. Authentification par email sans mot de passe —
via Supabase OTP si `SUPABASE_URL`/`SUPABASE_KEY` sont configurés, sinon un
mode développement local (identification simple, sans vérification) pour
travailler sans compte Supabase.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pydeck as pdk
import streamlit as st
from dotenv import load_dotenv

from src.agent.collecte_agent import CollecteAgent, opening_message
from src.agent.collecte_tools import CollecteToolHandler
from src.annuaire import (
    SECTIONS_SYNTHESE,
    build_fiche_lieu,
    category_chips_html,
    default_visual,
    field_label,
    lieux_avec_coordonnees,
    photo_html,
    source_items_for_section,
    texte_en_points,
    vignette_html,
)
from src.auth_session import clear_session_cookie, read_session_cookie, save_session_cookie
from src.db.factory import get_admin_store, get_store
from src.db.store import Litige
from src.i18n import language_toggle, t
from src.questionnaire.schema import QUESTIONNAIRE, CATEGORIES_POSSIBLES, Role, all_fields
from src.theme import apply_theme
from src.voice_input import bouton_dictee, consume_voice_transcript

ROLES_INTERNES = {"fondateur", "equipe", "steward"}

RAG_DISPONIBLE = bool(os.environ.get("VOYAGE_API_KEY"))

load_dotenv()
st.set_page_config(page_title="Lieux hybrides et territoires", layout="wide")
apply_theme()
language_toggle()

# Contournement d'authentification STRICTEMENT réservé au développement local.
# ⚠️ Ne JAMAIS définir LOCAL_DEV_AUTOLOGIN dans les secrets Streamlit Cloud (ou
# tout environnement accessible publiquement) — quiconque ouvrirait l'app
# aurait alors un accès admin complet sans vérification d'email.
LOCAL_DEV_AUTOLOGIN = os.environ.get("LOCAL_DEV_AUTOLOGIN", "").lower() in ("1", "true", "yes")
LOCAL_DEV_ADMIN_EMAIL = os.environ.get("LOCAL_DEV_ADMIN_EMAIL", "admin@localhost")

SUPABASE_CONFIGURED = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def _supabase_client():
    """Un seul client Supabase par session Streamlit, réutilisé à chaque
    rerun — indispensable pour que la session posée par verify_otp() reste
    active (un client recréé à chaque rerun repartirait anonyme, et les
    policies RLS `auth.role() = 'authenticated'` rejetteraient tout)."""
    if "supabase_client" not in st.session_state:
        from supabase import create_client
        st.session_state["supabase_client"] = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
        )
    return st.session_state["supabase_client"]


def auth_screen() -> str | None:
    """Renvoie l'identifiant utilisateur une fois authentifié, sinon None
    (et affiche l'écran de connexion)."""
    if "user_id" in st.session_state:
        return st.session_state["user_id"]

    if LOCAL_DEV_AUTOLOGIN:
        # Connexion admin immédiate, sans passer par Supabase Auth — utilise
        # get_admin_store() (clé service_role, contourne RLS) plutôt qu'un
        # client anonyme qui serait de toute façon rejeté par les policies.
        st.session_state["user_id"] = LOCAL_DEV_ADMIN_EMAIL
        st.session_state["user_email"] = LOCAL_DEV_ADMIN_EMAIL
        st.session_state["use_admin_store"] = True
        return st.session_state["user_id"]

    if not SUPABASE_CONFIGURED:
        # Mode dev sans Supabase : pas de vraie sécurité de toute façon, donc
        # un cookie suffit à éviter de retaper son email à chaque visite.
        saved_email = read_session_cookie()
        if saved_email and "dev_cookie_declined" not in st.session_state:
            st.session_state["user_id"] = saved_email
            st.rerun()

        st.title(t("auth.title"))
        st.info(
            "Mode développement local : aucun projet Supabase configuré "
            "(`SUPABASE_URL`/`SUPABASE_KEY` absents de `.env`). L'identification "
            "ci-dessous n'est pas vérifiée — pratique pour tester, à remplacer "
            "par le vrai flux Supabase en production."
        )
        with st.form("dev_login_form"):
            email = st.text_input(t("auth.email_label"))
            submitted = st.form_submit_button("Continuer")
        if submitted and email:
            st.session_state["user_id"] = email
            st.session_state["user_email"] = email
            save_session_cookie(email)
            st.rerun()
        return None

    client = _supabase_client()

    # Restaure une session déjà ouverte (cookie posé lors d'une connexion
    # précédente) avant d'afficher le moindre formulaire — évite de redemander
    # un email à chaque visite. `cookie_restore_failed` empêche de reboucler
    # indéfiniment si le refresh_token est expiré ou invalide. `just_logged_out`
    # (posé par le bouton "Se déconnecter", consommé une seule fois ici) évite
    # une reconnexion automatique juste après : le composant cookie répond de
    # façon asynchrone, et un rerun immédiat après la suppression peut encore
    # relire l'ancien refresh_token avant que le navigateur n'ait fini de le
    # supprimer — constaté en production (déconnexion suivie d'une reconnexion
    # automatique silencieuse).
    just_logged_out = st.session_state.pop("just_logged_out", False)
    if not just_logged_out and "otp_sent_to" not in st.session_state and "cookie_restore_failed" not in st.session_state:
        refresh_token = read_session_cookie()
        if refresh_token:
            try:
                result = client.auth.refresh_session(refresh_token)
            except Exception:
                result = None
            if result and result.user:
                st.session_state["user_id"] = result.user.id
                st.session_state["user_email"] = result.user.email
                if result.session and result.session.refresh_token:
                    save_session_cookie(result.session.refresh_token)
                st.rerun()
            else:
                st.session_state["cookie_restore_failed"] = True

    st.title(t("auth.title"))

    if "otp_sent_to" not in st.session_state:
        with st.form("otp_request_form"):
            email = st.text_input(t("auth.email_label"))
            submitted = st.form_submit_button(t("auth.send_code"))
        if submitted and email:
            try:
                client.auth.sign_in_with_otp({"email": email})
                st.session_state["otp_sent_to"] = email
                st.rerun()
            except Exception as exc:
                message = str(exc)
                if "security purposes" in message or "rate limit" in message.lower():
                    st.warning(
                        "Une demande a déjà été envoyée récemment pour cet email — "
                        "Supabase impose un délai anti-spam d'environ 60 secondes entre "
                        "deux demandes. Patientez une minute sans recliquer, puis réessayez "
                        "une seule fois."
                    )
                else:
                    st.error(f"Échec de l'envoi du code de connexion : {message}")
        return None

    st.write(t("auth.code_sent", email=st.session_state["otp_sent_to"]))
    with st.form("otp_verify_form"):
        code = st.text_input(t("auth.code_label"))
        col1, col2 = st.columns(2)
        with col1:
            verify = st.form_submit_button(t("auth.verify"))
        with col2:
            change_email = st.form_submit_button(t("auth.change_email"))
    if change_email:
        st.session_state.pop("otp_sent_to", None)
        st.rerun()
    if verify and code:
        try:
            result = client.auth.verify_otp({
                "email": st.session_state["otp_sent_to"], "token": code.strip(), "type": "email",
            })
        except Exception as exc:
            st.error(f"Code invalide ou expiré : {exc}")
            return None
        if result.user:
            st.session_state.pop("otp_sent_to", None)
            st.session_state["user_id"] = result.user.id
            st.session_state["user_email"] = result.user.email
            if result.session and result.session.refresh_token:
                save_session_cookie(result.session.refresh_token)
            st.rerun()
        else:
            st.error(t("auth.invalid_code"))
    return None


ROLE_LABELS = {
    "fondateur": "Fondateur·rice / porteur de projet",
    "equipe": "Équipe opérationnelle",
    "partenaire": "Partie prenante externe",
    "usager": "Usager régulier",
    "steward": "Steward (je continue à nourrir ce lieu)",
    "autre": "Autre",
}


def _admin_store_or_error(silent: bool = False):
    """get_admin_store(), mais affiche un message clair dans l'UI plutôt que
    de laisser planter l'onglet si SUPABASE_SERVICE_KEY manque — ce repli
    silencieux (avant : écriture vers une base SQLite locale jamais relue)
    est exactement ce qui a fait "disparaître" un lieu coché pour le
    Portfolio en production. Renvoie None si indisponible ; l'appelant doit
    vérifier avant d'utiliser le store retourné.

    `silent=True` pour un appel de lecture fait pour TOUT visiteur d'une
    fiche (ex. résoudre la liste des contributeurs) : un visiteur non-admin
    ne peut rien faire de ce message et ne devrait pas voir une bannière
    d'erreur rouge à chaque ouverture de fiche pour un problème de
    configuration qui ne le concerne pas."""
    try:
        return get_admin_store()
    except RuntimeError as exc:
        if not silent:
            st.error(str(exc))
        return None


def contribution_selector(store, user_id: str):
    """Sélection du lieu/rôle pour l'Entretien — affichée dans le corps de
    l'onglet lui-même (pas dans la barre latérale) : ce choix ne conditionne
    QUE cet onglet (Assistant RAG, Annuaire, Administration n'en ont pas
    besoin), et le montrer dans la barre latérale le faisait apparaître sur
    tous les onglets sans raison, y compris ceux où il n'a aucun effet."""
    st.subheader(t("contribution.title"))
    # Tous les lieux recensés (pas seulement les siens) : n'importe quel
    # utilisateur connecté peut devenir contributeur/steward d'un lieu créé
    # par quelqu'un d'autre (cf. bouton "Continuer à nourrir" de l'Annuaire).
    tous_les_lieux = store.list_tiers_lieux()
    noms_existants = sorted(l.nom for l in tous_les_lieux)

    preselect_lieu = st.session_state.pop("preselect_lieu", None)
    preselect_role = st.session_state.pop("preselect_role", None)

    option_nouveau_lieu = t("contribution.nouveau_lieu_option")
    options_lieu = [option_nouveau_lieu] + noms_existants
    index_lieu = options_lieu.index(preselect_lieu) if preselect_lieu in options_lieu else 0
    col_lieu, col_role = st.columns(2)
    with col_lieu:
        choix = st.selectbox(t("contribution.lieu_label"), options=options_lieu, index=index_lieu)
        if choix == option_nouveau_lieu:
            nom_lieu = st.text_input(t("contribution.nom_nouveau_lieu"))
        else:
            nom_lieu = choix

    role_options = [r.value for r in Role]
    index_role = role_options.index(preselect_role) if preselect_role in role_options else 0
    with col_role:
        role = st.selectbox(
            t("contribution.role_label"),
            options=role_options,
            index=index_role,
            format_func=lambda r: t(f"role.{r}"),
        )
    return nom_lieu, role


def entretien_tab(store, user_id: str):
    st.title(t("entretien.title"))
    nom_lieu, role = contribution_selector(store, user_id)
    if not nom_lieu:
        st.info(t("contribution.choisir_pour_demarrer"))
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY n'est pas configuré (voir .env.example).")
        return

    # tiers_lieu/contributeur ne sont résolus qu'à la création de la session
    # (pas à chaque message : chaque envoi redéclenche tout le script, et les
    # re-résoudre à chaque fois ajoutait 2 aller-retours réseau à chaque
    # message sur Supabase, pour rien la plupart du temps). Le blocage d'un
    # contributeur reste appliqué : c'est la lecture agrégée (get_answers /
    # get_all_answers_by_contributeur, filtrée par bloque) qui l'exclut
    # réellement des synthèses, pas cette vérification d'accueil — un blocage
    # décidé en cours de session prend effet à la prochaine session plutôt
    # qu'au message suivant, ce qui est un compromis acceptable.
    session_key = f"agent::{nom_lieu}::{role}"
    mode_key = f"mode_entretien::{session_key}"
    if session_key not in st.session_state and mode_key not in st.session_state:
        st.subheader("Par où commencer ?")
        campagnes_actives = store.get_active_campagnes_prioritaires()
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📖 Nourrir l'histoire du lieu", use_container_width=True,
                         help="Genèse, défis, description, fonctionnement — l'entretien complet, comme d'habitude."):
                st.session_state[mode_key] = "histoire"
                st.rerun()
        with col2:
            label_campagne = "📋 Remplir une campagne en cours" if campagnes_actives else "📋 Aucune campagne active"
            if st.button(label_campagne, use_container_width=True, disabled=not campagnes_actives,
                         help="Répondre en priorité à un recensement ciblé actuellement ouvert par l'équipe."):
                st.session_state[mode_key] = "campagne"
                st.rerun()
        with col3:
            if st.button("📣 Rendre visibles vos besoins actuels", use_container_width=True,
                         help="Exprimer directement de quoi le lieu aurait besoin — utilisé dans l'Annuaire et "
                              "pour la curation du Portfolio."):
                st.session_state[mode_key] = "besoins"
                st.rerun()
        return
    mode_entretien = st.session_state.get(mode_key, "histoire")

    if session_key not in st.session_state:
        tiers_lieu = store.get_or_create_tiers_lieu(user_id, nom_lieu)
        contributeur = store.get_or_create_contributeur(user_id, tiers_lieu.id, role)
        if contributeur.bloque:
            st.error(
                "Votre contribution à ce lieu a été suspendue par un administrateur ou un steward "
                "de ce lieu, suite à un signalement. Contactez l'équipe si vous pensez qu'il s'agit "
                "d'une erreur."
            )
            return

        # Le nom du lieu est déjà connu (saisi dans la barre latérale) : on le
        # pré-remplit comme réponse pour que l'entretien ne redemande jamais
        # "quel est le nom de votre lieu ?" en première question.
        if store.get_answers(tiers_lieu.id, contributeur.id).get("nom_lieu") is None:
            store.save_answer(tiers_lieu.id, contributeur.id, "nom_lieu", tiers_lieu.nom)
        session = store.get_or_start_session(tiers_lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, tiers_lieu.id, contributeur.id, session, Role(role),
                                       mode_entretien=mode_entretien)
        agent = CollecteAgent(handler, store=store, tiers_lieu_id=tiers_lieu.id)
        st.session_state[session_key] = {"agent": agent, "history": []}
        # Premier appel LLM (résumé d'ouverture) : sans spinner, la page
        # restait visuellement figée le temps de cet appel (plusieurs
        # secondes), juste après avoir choisi/créé le lieu — perçu comme un
        # gel plutôt qu'un chargement.
        with st.spinner("Préparation de l'entretien..."):
            opening = agent.send(opening_message(
                store, tiers_lieu.id, nom_lieu=tiers_lieu.nom,
                contributeur_id=contributeur.id, role_label=ROLE_LABELS[role],
                mode_entretien=mode_entretien,
            ))
        st.session_state[session_key]["history"].append(("assistant", opening))

    state = st.session_state[session_key]
    for speaker, text in state["history"]:
        with st.chat_message(speaker):
            st.write(text)

    # En deux temps (message ajouté + rerun immédiat, appel LLM au rerun
    # suivant) — voir la même note dans rag_tab : sans ça, la réponse de
    # l'utilisateur ne s'affichait elle-même qu'une fois la réplique de
    # l'agent obtenue, plusieurs secondes plus tard.
    lang_code = "fr-FR" if st.session_state.get("ui_lang", "fr") == "fr" else "en-US"
    voice_text = consume_voice_transcript()
    bouton_dictee(lang_code, label=t("voice.dicter_reponse"))
    user_text = st.chat_input(t("chat.entretien_placeholder")) or voice_text
    if user_text:
        state["history"].append(("user", user_text))
        state["reponse_en_attente"] = user_text
        st.rerun()

    if state.get("reponse_en_attente"):
        reponse_en_attente = state["reponse_en_attente"]
        with st.spinner("L'agent réfléchit..."):
            reply = state["agent"].send(reponse_en_attente)
        state["history"].append(("assistant", reply))
        state["reponse_en_attente"] = None
        st.rerun()


def _auto_enrich_one(store, lieu) -> None:
    """Ré-enrichissement automatique et silencieux d'UN SEUL lieu : plus de
    bouton manuel. `enrich_lieu` est idempotent (compare le hash des réponses
    source), donc peu coûteux dans le cas courant (déjà à jour) — appelé à
    l'ouverture de la fiche d'un lieu, jamais pour toute la grille d'un coup
    (24 lieux × 2 requêtes + hash à chaque affichage de l'Annuaire rendait la
    page très lente)."""
    if not (os.environ.get("ANTHROPIC_API_KEY") and RAG_DISPONIBLE):
        return
    from src.agent.enrichissement import enrich_lieu
    try:
        enrich_lieu(store, lieu.id, force=False, nom_lieu=lieu.nom)
    except Exception:
        pass  # une synthèse en échec ne doit jamais bloquer l'affichage de la fiche


@st.dialog("Fiche du lieu", width="large")
def _fiche_dialog(store, fiche, est_admin: bool, user_id: str):
    lieu = fiche["tiers_lieu"]
    if "fiche_enrichie" not in st.session_state:
        st.session_state["fiche_enrichie"] = set()
    if lieu.id not in st.session_state["fiche_enrichie"]:
        # Généralement rapide (enrich_lieu compare un hash et ne fait rien
        # si les réponses n'ont pas changé) — mais quand un appel LLM part
        # réellement, ça prend plusieurs secondes sans qu'aucun indicateur
        # ne le montrait jusqu'ici, donnant l'impression que la fiche entière
        # est devenue lente.
        with st.spinner("Mise à jour de la synthèse..."):
            _auto_enrich_one(store, lieu)
        st.session_state["fiche_enrichie"].add(lieu.id)
    derive = store.get_lieu_derive(lieu.id)
    donnees = derive.donnees if derive else {}

    col_vignette, col_info = st.columns([1, 2.5])
    with col_vignette:
        if derive and derive.photo_url:
            st.markdown(photo_html(derive.photo_url, hauteur="10rem"), unsafe_allow_html=True)
        else:
            emoji, couleur = default_visual(lieu.nom, donnees)
            st.markdown(vignette_html(emoji, couleur, hauteur="10rem"), unsafe_allow_html=True)
    with col_info:
        st.markdown(f"### {lieu.nom}")
        st.caption(
            f"{lieu.pays or 'pays non renseigné'} — {lieu.region or 'région non renseignée'} · "
            f"{fiche['nombre_contributeurs']} contributeur(s)"
        )
        if donnees.get("categories"):
            st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
        if derive:
            st.write(donnees.get("resume", ""))
            if derive.lien_externe:
                st.markdown(f"[🔗 Fiche externe]({derive.lien_externe})")
        else:
            st.info("Pas encore de synthèse générée pour ce lieu — répondez à quelques questions "
                     "dans l'onglet Entretien pour qu'elle apparaisse ici.")

    if st.button("🌱 Revendiquer le suivi de ce lieu (steward)", key=f"nourrir_{lieu.id}",
                 use_container_width=True):
        st.session_state["preselect_lieu"] = lieu.nom
        st.session_state["preselect_role"] = "steward"
        st.toast(f"« {lieu.nom} » sélectionné — rendez-vous dans l'onglet Entretien.", icon="🌱")

    if derive:
        st.divider()
        # Une section sans aucune source déclarée (sources[cle] vide) n'est
        # que la formule de remplissage que le prompt d'enrichissement
        # demande explicitement pour homogénéiser la longueur (ex. "Aucun
        # partenariat... n'est mentionné") — ne rien afficher plutôt que du
        # bruit sans valeur informative, cohérent avec le principe
        # déclaré/déduit : rien de déclaré, rien à montrer comme fait.
        # Un seul chargement pour tout le lieu, réutilisé pour les jusqu'à 11
        # sections (voir la note dans source_items_for_section).
        notes_lieu = store.get_free_text_notes(lieu.id)
        reponses_lieu = store.get_all_answers_by_contributeur(lieu.id)
        sections_avec_sources = []
        for cle, titre in SECTIONS_SYNTHESE[1:]:  # sans "resume", déjà affiché
            sources = source_items_for_section(cle, derive, notes_lieu, reponses_lieu)
            if sources:
                sections_avec_sources.append((cle, titre, sources))

        if sections_avec_sources:
            cols = st.columns(3)
            for i, (cle, titre, sources) in enumerate(sections_avec_sources):
                texte = donnees.get(cle) or "—"
                with cols[i % 3]:
                    st.markdown(f"**{titre}**")
                    st.caption(texte_en_points(texte))
                    with st.popover("Sources", use_container_width=True):
                        for s in sources:
                            st.markdown(f"**{s['label']}** : {s['valeur']}")
        else:
            st.caption("Pas encore assez d'informations déclarées pour détailler ce lieu par thème.")

        with st.expander("Modifier le lien externe / la photo"):
            with st.form(f"liens_{lieu.id}"):
                nouveau_lien = st.text_input("Lien externe (ex. fiche tiers-lieux.xyz)",
                                              value=derive.lien_externe or "")
                nouvelle_photo = st.text_input("URL de la photo",
                                                value=derive.photo_url or "")
                if st.form_submit_button("Enregistrer"):
                    store.update_lieu_derive_liens(lieu.id, nouveau_lien or None, nouvelle_photo or None)
                    st.rerun()

    with st.expander("Voir toutes les réponses brutes et témoignages"):
        for label, entries in fiche["par_champ"].items():
            valeurs = ", ".join(str(e["valeur"]) for e in entries)
            st.markdown(f"**{label}** : {valeurs}")
        if fiche["temoignages"]:
            st.markdown("**Témoignages libres**")
            for t in fiche["temoignages"]:
                st.markdown(f"> {t['texte']}")

    if est_admin:
        st.divider()
        _admin_portfolio_form(store, lieu, derive)

    # RLS ne laisse un utilisateur authentifié voir que ses PROPRES lignes
    # contributeurs (policy "user_id = auth.uid()") — list_contributeurs doit
    # donc passer par le store service_role pour voir tous les contributeurs
    # d'un lieu, sans quoi la liste de modération ne montrerait jamais que
    # soi-même.
    admin_store_moderation = _admin_store_or_error(silent=not est_admin)
    contributeurs_lieu = admin_store_moderation.list_contributeurs(lieu.id) if admin_store_moderation else []
    mon_contributeur_interne = next(
        (c for c in contributeurs_lieu if c.user_id == user_id and c.role in ROLES_INTERNES and not c.bloque),
        None,
    )
    if est_admin or mon_contributeur_interne:
        st.divider()
        _historique_et_moderation(store, lieu, contributeurs_lieu, est_admin, user_id)


def _historique_et_moderation(store, lieu, contributeurs_lieu: list, est_admin: bool, user_id: str) -> None:
    with st.expander("Historique & modération"):
        st.markdown("**Contributeurs de ce lieu**")
        for c in contributeurs_lieu:
            col1, col2 = st.columns([4, 1])
            with col1:
                suffixe = " (vous)" if c.user_id == user_id else ""
                statut = " · 🚫 bloqué" if c.bloque else ""
                st.write(f"{ROLE_LABELS.get(c.role, c.role)} — `{c.user_id}`{suffixe}{statut}")
            with col2:
                if c.user_id == user_id:
                    pass
                elif c.bloque:
                    if st.button("Débloquer", key=f"unblock_{c.id}"):
                        admin_store = _admin_store_or_error()
                        if admin_store:
                            admin_store.set_contributeur_bloque(c.id, False)
                            st.rerun()
                else:
                    if st.button("Bloquer", key=f"block_{c.id}"):
                        admin_store = _admin_store_or_error()
                        if admin_store:
                            admin_store.set_contributeur_bloque(c.id, True, bloque_par=user_id)
                            st.rerun()

        st.markdown("**Signaler un litige**")
        options_cible = [None] + [c.id for c in contributeurs_lieu]
        labels_cible = {c.id: f"{ROLE_LABELS.get(c.role, c.role)} — {c.user_id}" for c in contributeurs_lieu}
        with st.form(f"litige_{lieu.id}", clear_on_submit=True):
            description = st.text_area("Description du désaccord")
            cible = st.selectbox("Contributeur concerné (optionnel)", options=options_cible,
                                  format_func=lambda cid: "—" if cid is None else labels_cible.get(cid, cid))
            if st.form_submit_button("Signaler"):
                if not description.strip():
                    st.error("Décrivez le désaccord avant de signaler.")
                else:
                    admin_store = _admin_store_or_error()
                    if admin_store:
                        admin_store.save_litige(Litige(
                            tiers_lieu_id=lieu.id, description=description.strip(),
                            signale_par=user_id, contributeur_vise_id=cible,
                        ))
                        st.success("Litige signalé.")
                        st.rerun()

        litiges = store.list_litiges(lieu.id)
        if litiges:
            st.markdown("**Litiges**")
            for lit in litiges:
                col1, col2 = st.columns([4, 1])
                with col1:
                    marque = "🟢 résolu" if lit.statut == "resolu" else "🔴 ouvert"
                    st.write(f"{marque} — {lit.description}")
                with col2:
                    if est_admin and lit.statut == "ouvert":
                        if st.button("Résoudre", key=f"resoudre_{lit.id}"):
                            admin_store = _admin_store_or_error()
                            if admin_store:
                                admin_store.resoudre_litige(lit.id)
                                st.rerun()

        st.markdown("**Historique récent**")
        historique = store.get_historique(lieu.id, limite=30)
        if not historique:
            st.caption("Aucun historique pour l'instant.")
        for h in historique:
            role = h.get("contributeur_role") or "?"
            champ = h.get("champ_id") or "note libre"
            statut_contrib = " 🚫" if h.get("contributeur_bloque") else ""
            st.caption(f"{h.get('cree_le', '')} — {role}{statut_contrib} — {champ} : {h.get('valeur')}")


def annuaire_tab(store, est_admin: bool, user_id: str):
    st.title(t("lieux_hybrides.title"))
    st.caption(t("lieux_hybrides.caption"))
    # Ordre alphabétique par défaut plutôt que l'ordre d'insertion en base,
    # peu significatif pour qui parcourt la liste.
    lieux = sorted(store.list_tiers_lieux(), key=lambda l: l.nom.lower())
    if not lieux:
        st.info("Aucun lieu recensé pour l'instant.")
        return

    # La grille n'a besoin que de list_tiers_lieux + un batch de lieu_derive
    # (2 requêtes au total) — PAS de build_annuaire/build_fiche_lieu (qui
    # ajoutait 2 requêtes par lieu, pour des réponses brutes/témoignages qui
    # ne sont utiles que dans la fiche d'UN lieu ouvert, jamais dans la
    # grille). C'est cette fiche complète, calculée pour 24+ lieux à chaque
    # affichage, qui rendait l'Annuaire lent — elle n'est désormais calculée
    # que pour le lieu réellement ouvert dans le popup.
    derive_par_lieu = store.get_lieu_derive_batch([l.id for l in lieux])

    coords = lieux_avec_coordonnees(store)
    if coords:
        df_coords = pd.DataFrame(coords)
        lat_centre = df_coords["lat"].mean()
        lon_centre = df_coords["lon"].mean()
        # Zoom calé sur l'étendue réelle des lieux plutôt qu'une valeur fixe
        # (vue par défaut trop large ou trop resserrée selon les données) :
        # formule standard "fit bounds" (256px = 360° au niveau 0), avec une
        # marge de 30% pour ne pas coller les points au bord de la carte.
        etendue = max(
            df_coords["lat"].max() - df_coords["lat"].min(),
            df_coords["lon"].max() - df_coords["lon"].min(),
            0.02,
        )
        zoom = max(3.0, min(math.log2(757 / etendue), 14.0))

        couche_lieux = pdk.Layer(
            "ScatterplotLayer",
            data=df_coords,
            id="lieux",
            get_position=["lon", "lat"],
            get_fill_color=[74, 222, 128, 210],
            get_radius=600,
            # Rayon plancher en pixels (indépendant du zoom) : à faible zoom,
            # 600m à l'échelle réelle devient quelques pixels à peine, trop
            # petit pour être cliqué de façon fiable.
            radius_min_pixels=6,
            radius_max_pixels=24,
            pickable=True,
            auto_highlight=True,
        )
        vue = pdk.ViewState(latitude=lat_centre, longitude=lon_centre, zoom=zoom)
        # map_provider="carto" : fond de carte par défaut de pydeck, sans
        # jeton Mapbox à configurer (contrairement à map_style="mapbox://...").
        deck = pdk.Deck(
            layers=[couche_lieux], initial_view_state=vue,
            map_provider="carto", map_style="light",
            tooltip={"text": "{nom}"},
        )
        # on_select="rerun" + id sur la couche : un clic renvoie le lieu
        # sélectionné, réutilisé pour ouvrir la même fiche que le clic sur
        # une carte de la grille (annuaire_open_lieu_id), sans dupliquer le
        # popup dans un second mécanisme d'affichage.
        evenement = st.pydeck_chart(
            deck, on_select="rerun", selection_mode="single-object", key="annuaire_map",
        )
        objets_selectionnes = evenement.selection.get("objects", {}).get("lieux", [])
        # La sélection du widget carte reste posée d'un rerun à l'autre (pas
        # d'événement ponctuel comme un clic de bouton) : sans le comparer à
        # la dernière traitée, chaque rerun (dialogue fermé, filtre changé...)
        # rouvrirait la même fiche en boucle, provoquant une boucle infinie.
        if objets_selectionnes:
            lieu_selectionne_id = objets_selectionnes[0]["id"]
            if st.session_state.get("_derniere_selection_carte") != lieu_selectionne_id:
                st.session_state["_derniere_selection_carte"] = lieu_selectionne_id
                st.session_state["annuaire_open_lieu_id"] = lieu_selectionne_id
                st.rerun()

    recherche = st.text_input(
        "Rechercher", placeholder="🔍 Nom, ville, région...", label_visibility="collapsed",
    )
    col_pays, col_region, col_categories = st.columns(3)
    with col_pays:
        options_pays = sorted({l.pays for l in lieux if l.pays})
        filtre_pays = st.multiselect("Pays", options=options_pays)
    with col_region:
        options_region = sorted({l.region for l in lieux if l.region})
        filtre_region = st.multiselect("Région", options=options_region)
    with col_categories:
        filtre_categories = st.multiselect("Catégorie", options=CATEGORIES_POSSIBLES)

    lieux_affiches = lieux
    if recherche.strip():
        q = recherche.strip().lower()
        lieux_affiches = [
            l for l in lieux_affiches
            if q in l.nom.lower() or q in (l.region or "").lower() or q in (l.pays or "").lower()
        ]
    if filtre_pays:
        lieux_affiches = [l for l in lieux_affiches if l.pays in filtre_pays]
    if filtre_region:
        lieux_affiches = [l for l in lieux_affiches if l.region in filtre_region]
    if filtre_categories:
        lieux_affiches = [
            l for l in lieux_affiches
            if (lambda d: d and set(d.donnees.get("categories") or []) & set(filtre_categories))(
                derive_par_lieu.get(l.id)
            )
        ]
    st.caption(f"{len(lieux_affiches)} lieu(x) affiché(s)")

    if "annuaire_open_lieu_id" in st.session_state:
        lieu_id = st.session_state.pop("annuaire_open_lieu_id")
        lieu_ouvert = next((l for l in lieux if l.id == lieu_id), None)
        if lieu_ouvert:
            with st.spinner("Chargement de la fiche..."):
                fiche = build_fiche_lieu(store, lieu_ouvert)
            _fiche_dialog(store, fiche, est_admin, user_id)

    cols_par_ligne = 4
    for i in range(0, len(lieux_affiches), cols_par_ligne):
        cols = st.columns(cols_par_ligne)
        for col, lieu in zip(cols, lieux_affiches[i:i + cols_par_ligne]):
            derive = derive_par_lieu.get(lieu.id)
            donnees = derive.donnees if derive else {}
            with col:
                with st.container(border=True):
                    if derive and derive.photo_url:
                        st.markdown(photo_html(derive.photo_url), unsafe_allow_html=True)
                    else:
                        emoji, couleur = default_visual(lieu.nom, donnees)
                        st.markdown(vignette_html(emoji, couleur), unsafe_allow_html=True)
                    if donnees.get("categories"):
                        st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
                    if st.button(lieu.nom, key=f"open_{lieu.id}", use_container_width=True):
                        st.session_state["annuaire_open_lieu_id"] = lieu.id
                        st.rerun()
                    st.caption(lieu.pays or "—")


def _admin_portfolio_form(store, lieu, derive) -> None:
    st.markdown("**Administration — Portfolio**")
    if derive is None:
        st.caption("Une synthèse doit d'abord être générée pour ce lieu avant de pouvoir "
                    "l'inclure au Portfolio.")
        return

    # Case à cocher hors formulaire, sauvegardée immédiatement via on_change —
    # dans un st.form, elle restait sans effet tant que le bouton "Enregistrer"
    # n'était pas cliqué séparément (facile à manquer, et c'est bien ce qui
    # s'est produit en pratique : aucun lieu n'avait jamais inclus_portfolio à
    # true en base malgré des cases cochées). L'inclusion est un simple
    # bascule ; seul le texte de campagne, plus long à saisir, garde un
    # formulaire pour éviter un rerun à chaque frappe.
    def _bascule_inclusion() -> None:
        cle = f"portfolio_inclus_{lieu.id}"
        nouvel_etat = st.session_state[cle]
        admin_store = _admin_store_or_error()
        if admin_store is None:
            # Écriture impossible (SUPABASE_SERVICE_KEY manquant) : on annule
            # visuellement la case plutôt que de la laisser cochée sans rien
            # avoir sauvegardé — une case cochée à tort qui semble "prise en
            # compte" est exactement ce qui a masqué ce bug en production.
            st.session_state[cle] = not nouvel_etat
            return
        admin_store.update_portfolio_entry(
            lieu.id, nouvel_etat, derive.campagne_texte, derive.campagne_objectif, derive.campagne_contact,
        )

    st.checkbox(
        "Inclure ce lieu dans le Portfolio public", value=bool(derive.inclus_portfolio),
        key=f"portfolio_inclus_{lieu.id}", on_change=_bascule_inclusion,
        help="Sauvegardé immédiatement, sans passer par le bouton Enregistrer ci-dessous.",
    )

    with st.form(f"portfolio_campagne_{lieu.id}"):
        campagne_texte = st.text_area("Texte de campagne (appel, contexte des besoins)",
                                       value=derive.campagne_texte or "")
        col1, col2 = st.columns(2)
        with col1:
            campagne_objectif = st.text_input("Objectif (ex. montant recherché)",
                                                value=derive.campagne_objectif or "")
        with col2:
            campagne_contact = st.text_input("Contact", value=derive.campagne_contact or "")
        if st.form_submit_button("Enregistrer la campagne"):
            admin_store = _admin_store_or_error()
            if admin_store:
                admin_store.update_portfolio_entry(
                    lieu.id, bool(derive.inclus_portfolio), campagne_texte or None,
                    campagne_objectif or None, campagne_contact or None,
                )
                st.success("Campagne mise à jour.")
                st.rerun()


def _condition_text(condition) -> str | None:
    if condition is None:
        return None
    op_labels = {"eq": "=", "ne": "≠", "in": "∈", "contains": "contient", "truthy": "renseigné"}
    label = op_labels.get(condition.operator, condition.operator)
    if condition.operator == "truthy":
        return f"{condition.field_id} {label}"
    return f"{condition.field_id} {label} {condition.value!r}"


def _tableau_repondants_campagne(admin_store, champ_ids: list) -> None:
    """Tableau des répondants à une campagne prioritaire (email, lieu, rôle,
    et leurs réponses aux champs de la campagne) — tous lieux confondus,
    puisqu'une campagne prioritaire n'est pas limitée à un seul lieu."""
    champs_schema = [cid for cid in champ_ids if not cid.startswith("libre::")]
    champs_libres = [cid for cid in champ_ids if cid.startswith("libre::")]
    if champs_libres:
        st.caption(
            "Questions libres collées dans cette campagne (réponses visibles par lieu dans "
            "« Données brutes » ci-dessous, pas dans ce tableau) : "
            + " · ".join(field_label(cid) for cid in champs_libres)
        )

    lignes = admin_store.get_reponses_pour_champs(champs_schema) if champs_schema else []
    if not lignes:
        if not champs_libres:
            st.caption("Aucune réponse pour l'instant.")
        return

    # Regroupe par (lieu, contributeur) : plusieurs lignes brutes (une par
    # champ) deviennent une seule ligne de tableau avec une colonne par champ.
    par_repondant: dict = {}
    for l in lignes:
        cle = (l["tiers_lieu_id"], l["contributeur_id"])
        par_repondant.setdefault(cle, {})[l["champ_id"]] = l["valeur"]

    tiers_lieu_ids = {tlid for tlid, _ in par_repondant}
    noms_lieux = {l.id: l.nom for l in admin_store.list_tiers_lieux() if l.id in tiers_lieu_ids}

    contributeurs_par_lieu: dict = {}
    for tlid in tiers_lieu_ids:
        for c in admin_store.list_contributeurs(tlid):
            contributeurs_par_lieu[c.id] = c

    user_ids = {c.user_id for c in contributeurs_par_lieu.values()}
    emails = admin_store.map_user_emails(list(user_ids))

    lignes_tableau = []
    for (tlid, cid), reponses in par_repondant.items():
        contributeur = contributeurs_par_lieu.get(cid)
        ligne = {
            "Lieu": noms_lieux.get(tlid, "—"),
            "Rôle": ROLE_LABELS.get(contributeur.role, contributeur.role) if contributeur else "—",
            "Email": emails.get(contributeur.user_id, "—") if contributeur else "—",
        }
        for champ_id in champs_schema:
            valeur = reponses.get(champ_id)
            ligne[field_label(champ_id)] = ", ".join(valeur) if isinstance(valeur, list) else (valeur or "—")
        lignes_tableau.append(ligne)

    st.dataframe(pd.DataFrame(lignes_tableau), use_container_width=True, hide_index=True)


def administration_tab(store, user_id: str) -> None:
    st.subheader("Administration")
    admin_store = _admin_store_or_error()
    if admin_store is None:
        return

    with st.expander("Comptes administrateurs", expanded=False):
        # list_admin_emails() appelle l'API Admin Auth de Supabase
        # (auth.admin.list_users()), qui exige la clé service_role — jamais
        # disponible sur `store` (RLS-scoped), d'où "User not allowed" si on
        # l'appelle dessus par erreur.
        emails = admin_store.list_admin_emails()
        st.write(", ".join(emails) if emails else "Aucun admin listé.")
        with st.form("add_admin_form", clear_on_submit=True):
            nouvel_email = st.text_input("Email à promouvoir administrateur")
            if st.form_submit_button("Ajouter"):
                if admin_store.add_admin_by_email(nouvel_email.strip()):
                    st.success(f"{nouvel_email} est désormais administrateur.")
                    st.rerun()
                else:
                    st.error("Aucun compte trouvé avec cet email (l'utilisateur doit s'être déjà connecté "
                              "au moins une fois).")

    with st.expander("Campagnes prioritaires (recensement ciblé)", expanded=False):
        st.caption("Pendant leur fenêtre active, les champs listés sont proposés en priorité dans "
                    "l'entretien, avant la suite normale du questionnaire.")
        campagnes = store.list_campagnes_prioritaires()
        if campagnes:
            for c in campagnes:
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(f"**{c.titre}** · {c.date_debut[:10]} → {c.date_fin[:10]} "
                                f"· {len(c.champ_ids)} champ(s)")
                    if c.description:
                        st.caption(c.description)
                with col2:
                    if st.button("Supprimer", key=f"del_campagne_{c.id}"):
                        admin_store.delete_campagne_prioritaire(c.id)
                        st.rerun()
                with st.expander(f"Voir les répondants — {c.titre}"):
                    _tableau_repondants_campagne(admin_store, c.champ_ids)
        else:
            st.caption("Aucune campagne prioritaire pour l'instant.")

        tous_les_champs = {f.id: f"{f.id} — {f.label}" for _, _, f in all_fields()}
        with st.form("nouvelle_campagne_form", clear_on_submit=True):
            titre = st.text_input("Titre de la campagne")
            description = st.text_area("Description (optionnel)")
            champ_ids = st.multiselect("Champs du questionnaire existant", options=list(tous_les_champs.keys()),
                                        format_func=lambda cid: tous_les_champs[cid])
            questions_libres_brut = st.text_area(
                "Questions personnalisées (hors questionnaire, une par ligne)",
                help="Collées telles quelles, sans passer par le schéma — utile pour une question "
                     "ponctuelle propre à cette campagne. L'agent les posera comme les autres, et "
                     "la réponse sera capturée en note libre pour le lieu concerné.",
            )
            col1, col2 = st.columns(2)
            with col1:
                date_debut = st.date_input("Début")
            with col2:
                date_fin = st.date_input("Fin")
            if st.form_submit_button("Créer la campagne"):
                questions_libres = [f"libre::{q.strip()}" for q in questions_libres_brut.splitlines() if q.strip()]
                tous_champ_ids = champ_ids + questions_libres
                if not titre or not tous_champ_ids:
                    st.error("Titre et au moins un champ (du questionnaire ou personnalisé) sont requis.")
                else:
                    from src.db.store import CampagnePrioritaire
                    admin_store.save_campagne_prioritaire(CampagnePrioritaire(
                        titre=titre, description=description or None, champ_ids=tous_champ_ids,
                        date_debut=date_debut.isoformat(), date_fin=date_fin.isoformat(), cree_par=user_id,
                    ))
                    st.success("Campagne créée.")
                    st.rerun()

    with st.expander("Données brutes : imports et saisies utilisateurs", expanded=False):
        st.caption(
            "Notes libres (imports CSV/CommunECter, anecdotes conversationnelles) et réponses "
            "structurées d'un lieu, éditables ou supprimables directement — modifiez une cellule "
            "puis « Enregistrer », ou supprimez une ligne via l'icône 🗑️ qui apparaît à sa gauche."
        )
        tous_les_lieux_admin = sorted(store.list_tiers_lieux(), key=lambda l: l.nom.lower())
        if not tous_les_lieux_admin:
            st.caption("Aucun lieu recensé pour l'instant.")
        else:
            lieu_choisi_nom = st.selectbox(
                "Lieu", options=[l.nom for l in tous_les_lieux_admin], key="admin_donnees_lieu",
            )
            lieu_admin = next(l for l in tous_les_lieux_admin if l.nom == lieu_choisi_nom)

            st.markdown("**Notes libres** *(imports CSV/CommunECter identifiés par leur source ; "
                        "sans source = capturé pendant l'entretien)*")
            notes = admin_store.get_free_text_notes(lieu_admin.id)
            if notes:
                df_notes = pd.DataFrame([
                    {"id": n["id"], "source": n.get("section_id") or "conversationnel", "texte": n["texte"]}
                    for n in notes
                ])
                edite_notes = st.data_editor(
                    df_notes, key=f"editor_notes_{lieu_admin.id}", use_container_width=True,
                    hide_index=True, num_rows="dynamic",
                    column_config={"id": None, "source": st.column_config.TextColumn(disabled=True)},
                )
                if st.button("Enregistrer les modifications", key=f"save_notes_{lieu_admin.id}"):
                    texte_avant = {n["id"]: n["texte"] for n in notes}
                    ids_apres = set(edite_notes["id"].dropna())
                    for note_id in set(texte_avant) - ids_apres:
                        admin_store.delete_free_text_note(note_id)
                    for _, row in edite_notes.iterrows():
                        if pd.notna(row["id"]) and row["texte"] != texte_avant.get(row["id"]):
                            admin_store.update_free_text_note(row["id"], row["texte"])
                    st.success("Notes mises à jour.")
                    st.rerun()
            else:
                st.caption("Aucune note libre pour ce lieu.")

            st.markdown("**Réponses structurées** *(saisies via l'entretien)*")
            reponses_par_contrib = admin_store.get_all_answers_by_contributeur(lieu_admin.id)
            contribs_admin = {c.id: c for c in admin_store.list_contributeurs(lieu_admin.id)}
            lignes_reponses = []
            for contributeur_id, reponses in reponses_par_contrib.items():
                role = contribs_admin[contributeur_id].role if contributeur_id in contribs_admin else "?"
                for champ_id, valeur in reponses.items():
                    lignes_reponses.append({
                        "contributeur_id": contributeur_id, "champ_id": champ_id,
                        "rôle": ROLE_LABELS.get(role, role), "champ": field_label(champ_id),
                        "valeur": ", ".join(valeur) if isinstance(valeur, list) else str(valeur if valeur is not None else ""),
                    })
            if lignes_reponses:
                df_reponses_admin = pd.DataFrame(lignes_reponses)
                edite_reponses = st.data_editor(
                    df_reponses_admin, key=f"editor_reponses_{lieu_admin.id}", use_container_width=True,
                    hide_index=True, num_rows="dynamic",
                    column_config={
                        "contributeur_id": None, "champ_id": None,
                        "rôle": st.column_config.TextColumn(disabled=True),
                        "champ": st.column_config.TextColumn(disabled=True),
                    },
                )
                if st.button("Enregistrer les modifications", key=f"save_reponses_{lieu_admin.id}"):
                    avant = {(l["contributeur_id"], l["champ_id"]): l["valeur"] for l in lignes_reponses}
                    apres_cles = set(zip(edite_reponses["contributeur_id"], edite_reponses["champ_id"]))
                    for (cid, chid) in set(avant) - apres_cles:
                        admin_store.delete_answer(lieu_admin.id, cid, chid)
                    for _, row in edite_reponses.iterrows():
                        cle = (row["contributeur_id"], row["champ_id"])
                        if cle not in avant or row["valeur"] == avant[cle]:
                            continue
                        # Reconstruit le type d'origine (liste/bool/nombre) à partir
                        # de la valeur affichée en texte, pour ne pas corrompre les
                        # champs multi_choice/boolean/number en les réenregistrant
                        # comme de simples chaînes.
                        original = reponses_par_contrib[row["contributeur_id"]][row["champ_id"]]
                        if isinstance(original, list):
                            nouvelle_valeur = [v.strip() for v in row["valeur"].split(",") if v.strip()]
                        elif isinstance(original, bool):
                            nouvelle_valeur = row["valeur"].strip().lower() in ("true", "vrai", "oui", "1")
                        elif isinstance(original, (int, float)):
                            try:
                                nouvelle_valeur = float(row["valeur"]) if "." in row["valeur"] else int(row["valeur"])
                            except ValueError:
                                nouvelle_valeur = row["valeur"]
                        else:
                            nouvelle_valeur = row["valeur"]
                        admin_store.save_answer(lieu_admin.id, row["contributeur_id"], row["champ_id"], nouvelle_valeur)
                    st.success("Réponses mises à jour.")
                    st.rerun()
            else:
                st.caption("Aucune réponse structurée pour ce lieu.")

    with st.expander("Synthèses des lieux (enrichissement IA)", expanded=False):
        st.caption(
            "Régénère le résumé, les enjeux, besoins, mots-clés et catégories de chaque lieu à partir "
            "de ses réponses actuelles. Seuls les lieux dont les réponses ont changé depuis le dernier "
            "enrichissement sont réellement retraités (comparaison par empreinte des réponses) — relancer "
            "souvent ne coûte donc rien pour les lieux déjà à jour. C'est aussi la seule façon de mettre "
            "à jour la recherche sémantique de la Bibliothèque : elle est stockée sur le disque local du "
            "serveur, jamais synchronisée automatiquement — un script lancé depuis un autre ordinateur "
            "n'y contribue pas, contrairement à ce bouton qui s'exécute ici, sur le serveur de l'app."
        )
        force_tous = st.checkbox(
            "Retraiter aussi les lieux déjà à jour (force)", value=False,
            help="Utile après une modification du prompt d'enrichissement lui-même, pas pour un usage courant.",
        )
        if st.button("Régénérer les synthèses"):
            from src.agent.enrichissement import enrich_lieu

            lieux_admin = admin_store.list_tiers_lieux()
            progress = st.progress(0.0)
            statut = st.empty()
            enrichis, inchanges, erreurs = 0, 0, []
            for i, lieu in enumerate(lieux_admin):
                statut.caption(f"{lieu.nom}...")
                try:
                    _, updated = enrich_lieu(admin_store, lieu.id, force=force_tous, nom_lieu=lieu.nom)
                    if updated:
                        enrichis += 1
                    else:
                        inchanges += 1
                except Exception as exc:
                    erreurs.append(f"{lieu.nom} : {exc}")
                progress.progress((i + 1) / len(lieux_admin))
            statut.empty()
            progress.empty()
            message = f"{enrichis} lieu(x) régénéré(s), {inchanges} déjà à jour."
            if erreurs:
                st.warning(message + f" {len(erreurs)} erreur(s) :\n" + "\n".join(erreurs))
            else:
                st.success(message)

    with st.expander("Recherche web : sites des lieux", expanded=False):
        st.caption(
            "Scanne la page d'accueil du site externe de chaque lieu (déjà connu via l'import "
            "CommunECter pour la plupart) pour en extraire ce que le questionnaire ne couvre pas "
            "encore — capturé en note libre, exploité au prochain « Régénérer les synthèses » "
            "ci-dessus. Un site indisponible ou sans contenu utile n'interrompt jamais le scan des "
            "autres lieux. Toujours manuel : contrairement aux réponses déjà en base, un site web "
            "réel est imprévisible (lent, mal formé, hors ligne) et mérite d'être supervisé."
        )
        if st.button("Scanner les sites des lieux référencés"):
            from src.agent.web_crawl import extraire_et_enregistrer
            from src.db.supabase_store import SupabaseStore

            if isinstance(admin_store, SupabaseStore):
                from src.db.migrate_sqlite_to_supabase import get_or_create_service_user
                owner_user_id = get_or_create_service_user(admin_store.client, "web-crawl-lieux")
            else:
                owner_user_id = "web-crawl-lieux"

            a_scanner = []
            for lieu in admin_store.list_tiers_lieux():
                derive = admin_store.get_lieu_derive(lieu.id)
                if derive and derive.lien_externe:
                    a_scanner.append((lieu, derive.lien_externe))

            if not a_scanner:
                st.caption("Aucun lieu n'a de site externe renseigné pour l'instant.")
            else:
                progress = st.progress(0.0)
                statut = st.empty()
                enregistres, rien_dutile, erreurs = 0, 0, []
                for i, (lieu, url) in enumerate(a_scanner):
                    statut.caption(f"{lieu.nom} ({url})...")
                    contributeur = admin_store.get_or_create_contributeur(owner_user_id, lieu.id, Role.AUTRE.value)
                    resultat = extraire_et_enregistrer(admin_store, lieu.id, contributeur.id, lieu.nom, url)
                    if resultat == "enregistre":
                        enregistres += 1
                    elif resultat == "rien_d_utile":
                        rien_dutile += 1
                    else:
                        erreurs.append(f"{lieu.nom} : {resultat}")
                    progress.progress((i + 1) / len(a_scanner))
                statut.empty()
                progress.empty()
                message = f"{enregistres} lieu(x) avec du contenu extrait, {rien_dutile} sans contenu utile."
                if erreurs:
                    st.warning(message + f" {len(erreurs)} erreur(s) :\n" + "\n".join(erreurs))
                else:
                    st.success(message)

    with st.expander("Schéma de l'entretien (lecture seule)", expanded=False):
        for module in QUESTIONNAIRE:
            st.markdown(f"#### {module.title} {'· optionnel' if module.optional else '· obligatoire'}")
            for section in module.sections:
                cond = _condition_text(section.condition)
                titre_section = f"{section.title}" + (f" — actif si {cond}" if cond else "")
                with st.expander(titre_section):
                    for f in section.fields:
                        roles = ", ".join(r.value for r in f.roles) if f.roles else "tous rôles"
                        fcond = _condition_text(f.condition)
                        ligne = f"`{f.id}` — {f.label} ({f.type.value}, {roles}"
                        ligne += ", requis)" if f.required else ")"
                        if fcond:
                            ligne += f" — actif si {fcond}"
                        st.markdown(ligne)


def _sauvegarder_conversation_bibliotheque(store, user_id: str) -> None:
    """Auto-save après chaque échange — jamais bloquant : une conversation
    non sauvegardée (table absente avant migration_003, erreur réseau...)
    ne doit jamais interrompre la Bibliothèque elle-même, seul l'historique
    en pâtit."""
    from src.db.store import ConversationBibliotheque

    historique = st.session_state.get("rag_history", [])
    if not historique:
        return
    premiere_question = next((texte for role, texte in historique if role == "user"), "Conversation")
    titre = (premiere_question[:60] + "…") if len(premiere_question) > 60 else premiere_question
    try:
        conv_id = store.save_conversation_bibliotheque(ConversationBibliotheque(
            id=st.session_state.get("rag_conversation_id", ""),
            user_id=user_id, titre=titre,
            messages=[{"role": role, "content": texte} for role, texte in historique],
        ))
        st.session_state["rag_conversation_id"] = conv_id
    except Exception:
        pass


def _ouvrir_conversation_bibliotheque(store, conversation_id: str) -> None:
    conv = store.get_conversation_bibliotheque(conversation_id)
    if conv is None:
        return
    st.session_state["rag_history"] = [(m["role"], m["content"]) for m in conv.messages]
    st.session_state["rag_conversation_id"] = conv.id
    # Reconstruit un contexte simplifié (texte seul, sans les blocs tool_use/
    # tool_result des échanges passés) plutôt que l'état exact de l'API — un
    # nouvel appel de tool se refait naturellement si besoin pour la
    # question suivante ; largement suffisant pour que l'agent continue la
    # conversation de façon cohérente.
    if "rag_agent" in st.session_state:
        st.session_state["rag_agent"].messages = [
            {"role": m["role"], "content": m["content"]} for m in conv.messages
        ]


def rag_tab(store, user_id: str):
    st.title(t("bibliotheque.title"))
    st.caption(t("bibliotheque.caption"))
    if not RAG_DISPONIBLE:
        st.info(
            "VOYAGE_API_KEY n'est pas configuré (voir .env.example) : l'assistant "
            "RAG a besoin des embeddings Voyage AI pour rechercher dans le corpus "
            "documentaire. Configurez la clé, déposez des fichiers dans data/raw/, "
            "lancez `python -m src.ingest.build_index`, puis revenez ici."
        )
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY n'est pas configuré (voir .env.example).")
        return

    if "rag_agent" not in st.session_state:
        from src.agent.rag_agent import RagAgent
        from src.agent.rag_tools import RagToolHandler

        try:
            with st.spinner("Chargement de la bibliothèque..."):
                st.session_state["rag_agent"] = RagAgent(RagToolHandler(store))
            st.session_state["rag_history"] = []
        except Exception as exc:
            # L'initialisation de ChromaDB (index vectoriel local) peut échouer
            # sur certains environnements (ex. état du disque après un reboot) —
            # ne doit jamais faire planter tout le script (et donc les autres
            # onglets, qui s'exécutent dans le même passage) pour un onglet
            # secondaire.
            st.error(f"Bibliothèque temporairement indisponible : {exc}")
            return

    with st.expander(t("bibliotheque.conversations_titre"), expanded=False):
        if st.button(t("bibliotheque.nouvelle_conversation")):
            st.session_state["rag_history"] = []
            st.session_state["rag_agent"].messages = []
            st.session_state.pop("rag_conversation_id", None)
            st.rerun()
        conversations = store.list_conversations_bibliotheque(user_id)
        if not conversations:
            st.caption(t("bibliotheque.aucune_conversation"))
        for conv in conversations:
            col_titre, col_ouvrir, col_suppr = st.columns([6, 2, 1])
            with col_titre:
                st.caption(f"{conv.titre or 'Conversation'} · {(conv.maj_le or '')[:16]}")
            with col_ouvrir:
                if st.button("Ouvrir", key=f"ouvrir_conv_{conv.id}", use_container_width=True):
                    _ouvrir_conversation_bibliotheque(store, conv.id)
                    st.rerun()
            with col_suppr:
                if st.button("🗑️", key=f"suppr_conv_{conv.id}"):
                    store.delete_conversation_bibliotheque(conv.id)
                    st.rerun()

    for speaker, text in st.session_state["rag_history"]:
        with st.chat_message(speaker):
            st.write(text)

    # En deux temps (message ajouté + rerun IMMÉDIAT, puis appel LLM dans le
    # rerun suivant) plutôt qu'un seul passage qui ajoute le message ET
    # attend la réponse avant de rafraîchir l'affichage : sans ça, la
    # question de l'utilisateur ne s'affichait elle-même qu'une fois la
    # réponse complète obtenue, donnant l'impression que tout le site est
    # lent alors que c'est seulement l'appel LLM qui prend plusieurs secondes.
    lang_code = "fr-FR" if st.session_state.get("ui_lang", "fr") == "fr" else "en-US"
    voice_question = consume_voice_transcript()
    bouton_dictee(lang_code, label=t("voice.dicter_question"))
    question = st.chat_input(t("chat.bibliotheque_placeholder")) or voice_question
    if question:
        st.session_state["rag_history"].append(("user", question))
        st.session_state["rag_question_en_attente"] = question
        st.rerun()

    if st.session_state.get("rag_question_en_attente"):
        question_en_attente = st.session_state["rag_question_en_attente"]
        with st.spinner("Recherche en cours..."):
            reply = st.session_state["rag_agent"].send(question_en_attente)
        st.session_state["rag_history"].append(("assistant", reply))
        st.session_state["rag_question_en_attente"] = None
        _sauvegarder_conversation_bibliotheque(store, user_id)
        st.rerun()


_session_refresh_faite = False  # module-level : remis à False à chaque script run (Streamlit ré-exécute
                                  # tout le module à chaque rerun), pas à chaque appel de _resolve_store


def _garder_session_supabase_active(client) -> None:
    """Le jeton d'accès Supabase (JWT) expire par défaut après ~1h. La
    librairie rafraîchit automatiquement la session dans get_session() si
    elle est expirée ou proche de l'être (via le refresh_token déjà posé en
    cookie à la connexion) — mais seulement si get_session() est appelée.
    Rien dans l'app ne l'appelait après la connexion initiale, donc un
    onglet resté ouvert plus d'une heure voyait toute requête Supabase
    suivante échouer avec "JWT expired" (PGRST303), constaté en production
    sur la Bibliothèque. Appelé ici, à chaque résolution de store (donc à
    chaque rendu de page), pour que ça n'arrive plus.

    Le garde-fou module-level est indispensable : _resolve_store() est
    appelée PLUSIEURS FOIS dans un même passage de script (une fois dans
    main() pour sonder si la section admin doit apparaître, une fois de
    plus dans la fonction de la page sélectionnée) — sans lui, save_cookie()
    (donc le composant cookie) était invoqué deux fois avec la même clé fixe
    dans le même run, ce que Streamlit interdit (StreamlitDuplicateElementKey,
    constaté en production sur la Bibliothèque)."""
    global _session_refresh_faite
    if _session_refresh_faite:
        return
    _session_refresh_faite = True
    try:
        session = client.auth.get_session()
    except Exception:
        return
    if session and session.refresh_token:
        save_session_cookie(session.refresh_token)


def _resolve_store(user_id: str):
    if st.session_state.get("use_admin_store"):
        return get_admin_store()
    supabase_client = st.session_state.get("supabase_client") if SUPABASE_CONFIGURED else None
    if supabase_client is not None:
        _garder_session_supabase_active(supabase_client)
    return get_store(client=supabase_client)


def _est_admin(store, user_id: str) -> bool:
    # En LOCAL_DEV_AUTOLOGIN, le store est déjà admin (service_role) : pas de
    # table `admins` à consulter, l'accès complet est déjà acquis par construction.
    return bool(st.session_state.get("use_admin_store")) or store.is_admin(user_id)


def _rendre_isole(nom_page: str, fonction, *args) -> None:
    # Chaque page est rendue défensivement : une erreur y reste locale,
    # affichée sur place, sans jamais empêcher les autres pages de
    # fonctionner normalement (héritage de l'ancien découpage en onglets,
    # où st.tabs() exécutait tout dans le même passage de script — avec
    # st.navigation(), chaque page a déjà son propre passage isolé, mais on
    # garde ce filet dans le doute plutôt que de laisser une trace brute).
    try:
        fonction(*args)
    except Exception as exc:
        st.error(f"« {nom_page} » a rencontré une erreur : {exc}")


# --- Pages nécessitant une connexion : chacune vérifie l'authentification
# elle-même (auth_screen() est idempotent — renvoie immédiatement l'id déjà
# en session_state si une page précédente s'est déjà authentifiée) plutôt que
# de la gater au niveau de st.navigation(), pour qu'Observatoire et Portfolio
# restent accessibles sans connexion dans le même menu de navigation.

def page_entretien() -> None:
    user_id = auth_screen()
    if not user_id:
        return
    store = _resolve_store(user_id)
    _rendre_isole("Compléter l'histoire", entretien_tab, store, user_id)


def page_bibliotheque() -> None:
    user_id = auth_screen()
    if not user_id:
        return
    store = _resolve_store(user_id)
    _rendre_isole("Bibliothèque", rag_tab, store, user_id)


def page_lieux_hybrides() -> None:
    user_id = auth_screen()
    if not user_id:
        return
    store = _resolve_store(user_id)
    est_admin = _est_admin(store, user_id)
    _rendre_isole("Lieux hybrides", annuaire_tab, store, est_admin, user_id)


def page_administration() -> None:
    user_id = auth_screen()
    if not user_id:
        return
    store = _resolve_store(user_id)
    if not _est_admin(store, user_id):
        st.error("Cette page est réservée aux administrateurs.")
        return
    _rendre_isole("Administration", administration_tab, store, user_id)


def main():
    # Administration est une page comme les autres (rendue dans la zone
    # principale, pas coincée dans la colonne étroite de la barre latérale —
    # un expander y suffisait pour un lien, pas pour des formulaires entiers)
    # mais reléguée à sa propre section de navigation, séparée de la section
    # principale, plutôt que mélangée à Compléter l'histoire / Bibliothèque /
    # Lieux hybrides — visible seulement pour un admin déjà identifié.
    #
    # Ce "sondage" d'admin AVANT st.navigation() peut être en retard d'un
    # rerun sur le tout premier passage d'une session (même limite que pour
    # le bloc compte plus bas) : la section Administration n'apparaît qu'au
    # rerun suivant la connexion, jamais avant.
    pages = {
        "": [
            st.Page(page_entretien, title=t("nav.entretien"), icon="📝",
                    url_path="entretien", default=True),
            st.Page(page_bibliotheque, title=t("nav.bibliotheque"), icon="📚", url_path="bibliotheque"),
            st.Page(page_lieux_hybrides, title=t("nav.lieux_hybrides"), icon="🏘️", url_path="lieux-hybrides"),
            st.Page("pages/1_Observatoire.py", title=t("nav.observatoire"), icon="📊"),
            st.Page("pages/2_Portfolio.py", title=t("nav.portfolio"), icon="✨"),
        ],
    }
    user_id_sonde = st.session_state.get("user_id")
    if user_id_sonde and _est_admin(_resolve_store(user_id_sonde), user_id_sonde):
        pages[t("nav.compte")] = [
            st.Page(page_administration, title=t("nav.administration"), icon="⚙️", url_path="administration"),
        ]

    pg = st.navigation(pages)
    pg.run()

    # Barre latérale "compte" : rendue après pg.run() (pas avant), pour que
    # user_id reflète bien ce que la page sélectionnée vient de résoudre via
    # auth_screen() sur CE passage — le lire avant pg.run() affichait un
    # instant sans bouton "Se déconnecter" ni email, le temps d'un rerun de
    # rattrapage (LOCAL_DEV_AUTOLOGIN notamment, qui ne force pas de rerun).
    user_id = st.session_state.get("user_id")
    if user_id:
        with st.sidebar:
            if st.session_state.get("use_admin_store"):
                st.warning(t("sidebar.admin_local_mode"))
            st.caption(t("sidebar.connected_as", email=st.session_state.get("user_email") or user_id))
            if st.button(t("sidebar.logout"), use_container_width=True):
                clear_session_cookie()
                for key in ("user_id", "user_email", "otp_sent_to", "cookie_restore_failed",
                            "use_admin_store", "supabase_client"):
                    st.session_state.pop(key, None)
                st.session_state["just_logged_out"] = True
                st.rerun()


if __name__ == "__main__":
    main()
