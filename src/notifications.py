"""Notifications email via Resend : connexion d'un utilisateur (admin@troistiers.space)
et formulaire de campagne entamé à mi-chemin (pa@troistiers.space).

Best-effort : l'envoi ne doit jamais faire planter la connexion ou l'entretien
en cours. Un échec (clé absente, Resend indisponible) est journalisé puis
avalé — voir _envoyer()."""

from __future__ import annotations

import html
import logging
import os

import requests

_log = logging.getLogger("space2.notifications")

_RESEND_API_URL = "https://api.resend.com/emails"
_EXPEDITEUR_PAR_DEFAUT = "Space2 <notifications@troistiers.space>"

ADMIN_EMAIL = "admin@troistiers.space"
PA_EMAIL = "pa@troistiers.space"


def _envoyer(destinataire: str, sujet: str, corps_html: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        _log.warning("[notif] RESEND_API_KEY absente — email à %s non envoyé (%s)", destinataire, sujet)
        return
    expediteur = os.environ.get("RESEND_FROM_EMAIL", _EXPEDITEUR_PAR_DEFAUT)
    try:
        reponse = requests.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": expediteur, "to": [destinataire], "subject": sujet, "html": corps_html},
            timeout=10,
        )
        reponse.raise_for_status()
    except Exception:
        _log.exception("[notif] échec de l'envoi à %s (%s)", destinataire, sujet)


def notifier_connexion(email_utilisateur: str) -> None:
    """Appelée juste après une connexion réussie (code OTP vérifié) — voir
    auth_screen() dans app.py. Déclenchée uniquement sur une vraie saisie de
    code, pas sur la reprise silencieuse de session via cookie à chaque
    ouverture d'onglet, pour ne pas spammer admin@ à chaque visite."""
    e = html.escape(email_utilisateur)
    _envoyer(ADMIN_EMAIL, f"Connexion Space2 : {email_utilisateur}",
             f"<p><strong>{e}</strong> vient de se connecter à Space2.</p>")


def notifier_mi_chemin_campagne(*, nom_lieu: str, role_label: str, campagne_titre: str,
                                 pourcentage: int, reponses: list[tuple[str, str]]) -> None:
    """Appelée une seule fois par session, la première fois que la
    progression d'un formulaire de campagne dépasse 50% — voir
    _maj_completion() dans app.py. `reponses` : paires (libellé, valeur)
    déjà données, en texte brut (pas de synthèse IA), pour donner à pa un
    aperçu concret du projet sans attendre la fin du formulaire."""
    lignes = "".join(
        f"<li><strong>{html.escape(label)}</strong> : {html.escape(str(valeur))}</li>"
        for label, valeur in reponses
    )
    nom = html.escape(nom_lieu)
    role = html.escape(role_label)
    titre = html.escape(campagne_titre)
    corps = (
        f"<p><strong>{nom}</strong> ({role}) a dépassé {pourcentage}% du formulaire "
        f"de la campagne « {titre} ».</p>"
        f"<p>Réponses données jusqu'ici :</p><ul>{lignes}</ul>"
    )
    _envoyer(PA_EMAIL, f"Campagne « {campagne_titre} » : {nom_lieu} à {pourcentage}%", corps)
