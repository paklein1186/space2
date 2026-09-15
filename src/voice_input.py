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
suivre le protocole interne (non garanti stable) de communication JS/Python
de Streamlit. À la place, le transcript final est transmis en rechargeant
la page avec un paramètre d'URL (`st.query_params`), une technique qui ne
dépend que d'API Streamlit publiques et documentées.

Le bouton lui-même est injecté DANS la page hôte (window.parent.document),
pas affiché dans l'iframe de son propre `components.html` : un premier
essai rendait un bouton normal dans le flux du script, qui atterrissait
n'importe où au-dessus de la barre de saisie (elle-même toujours ancrée en
bas par Streamlit, indépendamment de l'endroit du script où st.chat_input
est appelé) — visuellement décroché du champ de texte plutôt qu'intégré à
côté, comme sur Claude ou ChatGPT. Injecter dans `stBottomBlockContainer`
(testid stable, déjà utilisé ailleurs dans ce projet pour le CSS de thème)
et positionner en `position: fixed` relativement au bouton d'envoi natif
(`stChatInputSubmitButton`) place le micro juste à côté — vérifié : cet
ajout survit aux reruns Streamlit (React ne remonte que le sous-arbre du
widget chat_input lui-même, pas les nœuds ajoutés en sibling dans son
conteneur), sans dépendre de classes CSS générées (non stables d'une
version à l'autre), seulement de data-testid officiels."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

QUERY_PARAM = "voix"


def bouton_dictee(lang: str = "fr-FR", *, label: str = "Dicter la réponse") -> None:
    """Injecte (ou réinjecte, à chaque rerun) le bouton micro à côté du
    bouton d'envoi natif de st.chat_input, dans la page hôte. Une fois la
    dictée terminée, recharge la page avec le transcript dans l'URL (lu et
    consommé ensuite via consume_voice_transcript(), à appeler côté Python
    avant de rendre le champ de saisie concerné). Sans effet si la page
    n'a pas encore de st.chat_input rendu (ex. premier passage)."""
    html = f"""
    <script>
    (function() {{
      const parentDoc = window.parent.document;
      const chatInput = parentDoc.querySelector('[data-testid="stChatInput"]');
      const bottomContainer = parentDoc.querySelector('[data-testid="stBottomBlockContainer"]');
      if (!chatInput || !bottomContainer) return;

      const ancien = parentDoc.getElementById('lh-voice-btn-fixed');
      if (ancien) ancien.remove();
      const ancienStatus = parentDoc.getElementById('lh-voice-status-fixed');
      if (ancienStatus) ancienStatus.remove();
      if (window.parent.__lhVoiceInterval) {{
        clearInterval(window.parent.__lhVoiceInterval);
      }}

      const btn = parentDoc.createElement('button');
      btn.id = 'lh-voice-btn-fixed';
      btn.type = 'button';
      btn.title = {label!r};
      btn.textContent = '🎙️';
      btn.style.cssText = [
        'position:fixed', 'z-index:999', 'width:2.1rem', 'height:2.1rem', 'padding:0',
        'border-radius:999px', 'border:1px solid rgba(148,163,184,0.45)',
        'background:var(--sp-bg-elevated, transparent)', 'color:inherit',
        'cursor:pointer', 'font-size:1.05rem', 'line-height:1',
        'display:flex', 'align-items:center', 'justify-content:center',
      ].join(';');

      const status = parentDoc.createElement('div');
      status.id = 'lh-voice-status-fixed';
      status.style.cssText = [
        'position:fixed', 'z-index:999', 'font-size:0.78rem', 'opacity:0.9',
        'white-space:nowrap', 'max-width:min(60vw,320px)', 'overflow:hidden',
        'text-overflow:ellipsis', 'text-align:right', 'pointer-events:none',
        'color:inherit',
      ].join(';');

      bottomContainer.style.position = bottomContainer.style.position || 'relative';
      bottomContainer.appendChild(btn);
      bottomContainer.appendChild(status);

      function reposition() {{
        const submit = chatInput.querySelector('[data-testid="stChatInputSubmitButton"]');
        const ref = (submit || chatInput).getBoundingClientRect();
        const top = ref.top + ref.height / 2 - btn.offsetHeight / 2;
        const left = ref.left - btn.offsetWidth - 8;
        btn.style.top = top + 'px';
        btn.style.left = left + 'px';
        status.style.top = (top - 22) + 'px';
        status.style.left = Math.max(8, left - 260) + 'px';
        status.style.width = '260px';
      }}
      reposition();
      window.parent.__lhVoiceInterval = setInterval(reposition, 800);

      const Recognition = window.parent.SpeechRecognition || window.parent.webkitSpeechRecognition;
      if (!Recognition) {{
        btn.disabled = true;
        btn.style.opacity = '0.4';
        btn.style.cursor = 'not-allowed';
        btn.title = 'Dictée non disponible sur ce navigateur (essayez Chrome, Edge ou Opera)';
        return;
      }}
      const recognition = new Recognition();
      recognition.lang = '{lang}';
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      let listening = false;
      let statusTimeout = null;

      function showStatus(text, holdMs) {{
        status.textContent = text;
        if (statusTimeout) clearTimeout(statusTimeout);
        if (holdMs) {{
          statusTimeout = setTimeout(function() {{ status.textContent = ''; }}, holdMs);
        }}
      }}

      recognition.onstart = function() {{
        listening = true;
        btn.textContent = '🔴';
        showStatus('Écoute... (recliquez pour arrêter)');
      }};
      recognition.onerror = function(event) {{
        const messages = {{
          'not-allowed': "Micro refusé — autorisez l'accès au micro pour ce site.",
          'network': 'Service de reconnaissance vocale (Google) injoignable — bloqueur/proxy ?',
          'no-speech': 'Rien entendu — réessayez.',
        }};
        showStatus(messages[event.error] || ('Erreur : ' + event.error), 6000);
      }};
      recognition.onend = function() {{
        listening = false;
        btn.textContent = '🎙️';
      }};
      recognition.onresult = function(event) {{
        let transcript = '';
        for (let i = 0; i < event.results.length; i++) {{
          transcript += event.results[i][0].transcript;
        }}
        showStatus(transcript);
        const last = event.results[event.results.length - 1];
        if (last.isFinal && transcript.trim()) {{
          const url = new URL(window.parent.location.href);
          url.searchParams.set('{QUERY_PARAM}', transcript.trim());
          window.parent.location.href = url.toString();
        }}
      }};
      btn.addEventListener('click', function() {{
        if (listening) {{
          recognition.stop();
        }} else {{
          recognition.start();
        }}
      }});
    }})();
    </script>
    """
    components.html(html, height=1)


def consume_voice_transcript() -> str | None:
    """Si l'URL contient le paramètre déposé par bouton_dictee() (rechargement
    suite à une dictée terminée), le renvoie et le retire aussitôt de l'URL —
    pour ne pas le retraiter à chaque rerun suivant (ex. un rerun déclenché
    par l'envoi normal d'un message juste après)."""
    transcript = st.query_params.get(QUERY_PARAM)
    if transcript:
        del st.query_params[QUERY_PARAM]
    return transcript or None
