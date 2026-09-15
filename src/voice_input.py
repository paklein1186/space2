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
    """Affiche un bouton micro qui déclenche la reconnaissance vocale du
    navigateur ; une fois la dictée terminée, recharge la page avec le
    transcript dans l'URL (lu et consommé ensuite via consume_voice_transcript(),
    à appeler côté Python avant de rendre le champ de saisie concerné)."""
    html = f"""
    <div style="margin-bottom:0.5rem; font-family:inherit;">
      <button id="lh-voice-btn" type="button" style="
        display:flex; align-items:center; gap:0.4rem; padding:0.4rem 0.8rem;
        border-radius:10px; border:1px solid rgba(148,163,184,0.35);
        background:transparent; color:inherit; font:inherit; cursor:pointer;">
        <span id="lh-voice-icon">🎙️</span>
        <span id="lh-voice-label">{label}</span>
      </button>
      <div id="lh-voice-status" style="font-size:0.8rem; opacity:0.7; margin-top:0.25rem; min-height:1.1em;"></div>
    </div>
    <script>
    (function() {{
      const btn = document.getElementById("lh-voice-btn");
      const label = document.getElementById("lh-voice-label");
      const icon = document.getElementById("lh-voice-icon");
      const status = document.getElementById("lh-voice-status");
      const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const baseLabel = {label!r};
      if (!Recognition) {{
        btn.disabled = true;
        btn.style.opacity = "0.5";
        btn.style.cursor = "not-allowed";
        label.textContent = "Dictée non disponible sur ce navigateur";
        status.textContent = "Essayez avec Chrome, Edge ou Opera.";
        return;
      }}
      const recognition = new Recognition();
      recognition.lang = "{lang}";
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      let listening = false;

      recognition.onstart = function() {{
        listening = true;
        icon.textContent = "🔴";
        label.textContent = "Écoute... (cliquez pour arrêter)";
        status.textContent = "";
      }};
      recognition.onerror = function(event) {{
        status.textContent = event.error === "not-allowed"
          ? "Micro refusé — autorisez l'accès au micro pour ce site."
          : "Erreur de reconnaissance : " + event.error;
      }};
      recognition.onend = function() {{
        listening = false;
        icon.textContent = "🎙️";
        label.textContent = baseLabel;
      }};
      recognition.onresult = function(event) {{
        let transcript = "";
        for (let i = 0; i < event.results.length; i++) {{
          transcript += event.results[i][0].transcript;
        }}
        status.textContent = transcript;
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
    components.html(html, height=72)


def consume_voice_transcript() -> str | None:
    """Si l'URL contient le paramètre déposé par bouton_dictee() (rechargement
    suite à une dictée terminée), le renvoie et le retire aussitôt de l'URL —
    pour ne pas le retraiter à chaque rerun suivant (ex. un rerun déclenché
    par l'envoi normal d'un message juste après)."""
    transcript = st.query_params.get(QUERY_PARAM)
    if transcript:
        del st.query_params[QUERY_PARAM]
    return transcript or None
