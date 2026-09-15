"""Entrée vocale pour les champs de discussion (entretien, bibliothèque) —
utilise l'API navigateur Web Speech (reconnaissance faite par le navigateur
lui-même, gratuite, aucune clé ni service tiers), disponible sur les
navigateurs à moteur Chromium (Chrome, Edge, Opera...) ; Firefox et Safari
ne l'implémentent pas ou partiellement, d'où la détection et le repli en
bouton désactivé ci-dessous plutôt qu'un bouton silencieusement mort.

Pas de composant Streamlit bidirectionnel custom : une tentative précédente
(bibliothèque tierce streamlit-mic-recorder) s'est heurtée à une
incompatibilité avec la version de Streamlit utilisée ici, pour la même
classe de raison qui rend ce genre de composant fragile en général — il doit
suivre le protocole interne (non garanti stable) de communication
JS/Python de Streamlit. À la place, le transcript final est transmis en
rechargeant la page avec un paramètre d'URL (`st.query_params`), une
technique qui ne dépend que d'API Streamlit publiques et documentées."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

QUERY_PARAM = "voix"


def bouton_dictee(lang: str = "fr-FR", *, label: str = "Dicter la réponse") -> None:
    """Affiche un bouton micro compact (icône seule, pas un gros pavé) juste
    au-dessus du champ de saisie, qui déclenche la reconnaissance vocale du
    navigateur ; une fois la dictée terminée, recharge la page avec le
    transcript dans l'URL (lu et consommé ensuite via consume_voice_transcript(),
    à appeler côté Python avant de rendre le champ de saisie concerné).

    Composant volontairement petit (bouton rond icône seule + une ligne de
    statut compacte en dessous, dans le flux normal) : un `components.html`
    est rendu dans son propre iframe qui rogne tout ce qui dépasse sa
    hauteur, donc un texte de statut en superposition au-dessus du bouton
    (essayé d'abord) se retrouvait invisible, coupé par le bord de l'iframe —
    la ligne de statut doit rester DANS la hauteur réservée, pas par-dessus."""
    html = f"""
    <div style="display:flex; flex-direction:column; align-items:flex-end; font-family:inherit;">
      <button id="lh-voice-btn" type="button" title="{label}" style="
        display:flex; align-items:center; justify-content:center;
        width:2.1rem; height:2.1rem; padding:0; flex:none;
        border-radius:999px; border:1px solid rgba(148,163,184,0.4);
        background:transparent; color:inherit; font-size:1.05rem; line-height:1; cursor:pointer;">
        <span id="lh-voice-icon">🎙️</span>
      </button>
      <div id="lh-voice-status" style="
        font-size:0.75rem; opacity:0.85; white-space:nowrap; max-width:260px;
        overflow:hidden; text-overflow:ellipsis; text-align:right; margin-top:2px; height:1.1em;"></div>
    </div>
    <script>
    (function() {{
      const btn = document.getElementById("lh-voice-btn");
      const icon = document.getElementById("lh-voice-icon");
      const status = document.getElementById("lh-voice-status");
      const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Recognition) {{
        btn.disabled = true;
        btn.style.opacity = "0.4";
        btn.style.cursor = "not-allowed";
        btn.title = "Dictée non disponible sur ce navigateur (essayez Chrome, Edge ou Opera)";
        return;
      }}
      const recognition = new Recognition();
      recognition.lang = "{lang}";
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      let listening = false;
      let statusTimeout = null;

      function showStatus(text, holdMs) {{
        status.textContent = text;
        if (statusTimeout) clearTimeout(statusTimeout);
        if (holdMs) {{
          statusTimeout = setTimeout(function() {{ status.textContent = ""; }}, holdMs);
        }}
      }}

      recognition.onstart = function() {{
        listening = true;
        icon.textContent = "🔴";
        showStatus("Écoute... (recliquez pour arrêter)");
      }};
      recognition.onerror = function(event) {{
        const messages = {{
          "not-allowed": "Micro refusé — autorisez l'accès au micro pour ce site.",
          "network": "Reconnaissance vocale indisponible (problème réseau côté navigateur — "
                    + "vérifiez un bloqueur de pub/traqueurs ou un proxy qui filtrerait "
                    + "les services Google, requis par cette API navigateur).",
          "no-speech": "Rien entendu — réessayez.",
        }};
        showStatus(messages[event.error] || ("Erreur de reconnaissance : " + event.error), 6000);
      }};
      recognition.onend = function() {{
        listening = false;
        icon.textContent = "🎙️";
      }};
      recognition.onresult = function(event) {{
        let transcript = "";
        for (let i = 0; i < event.results.length; i++) {{
          transcript += event.results[i][0].transcript;
        }}
        showStatus(transcript);
        const last = event.results[event.results.length - 1];
        if (last.isFinal && transcript.trim()) {{
          const target = window.parent || window;
          const url = new URL(target.location.href);
          url.searchParams.set("{QUERY_PARAM}", transcript.trim());
          target.location.href = url.toString();
        }}
      }};
      btn.addEventListener("click", function() {{
        if (listening) {{
          recognition.stop();
        }} else {{
          recognition.start();
        }}
      }});
    }})();
    </script>
    """
    components.html(html, height=58)


def consume_voice_transcript() -> str | None:
    """Si l'URL contient le paramètre déposé par bouton_dictee() (rechargement
    suite à une dictée terminée), le renvoie et le retire aussitôt de l'URL —
    pour ne pas le retraiter à chaque rerun suivant (ex. un rerun déclenché
    par l'envoi normal d'un message juste après)."""
    transcript = st.query_params.get(QUERY_PARAM)
    if transcript:
        del st.query_params[QUERY_PARAM]
    return transcript or None
