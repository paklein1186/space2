"""Page publique : fiche d'UN lieu en lecture seule, atteinte via un lien de
partage (?lieu=<id>) posé sur le bouton "🔗 Partager" de la fiche dans
l'Annuaire (connecté). Aucune connexion requise — même principe que
l'Observatoire et le Portfolio : n'importe qui recevant ce lien voit la
même synthèse qu'un contributeur connecté, sans les sections de
modération/administration ni les réponses brutes nominatives.

Sélectionnée via st.Page dans src/app.py (menu de navigation unifié) : le
set_page_config()/apply_theme()/load_dotenv() de app.py s'appliquent déjà
avant que cette page ne s'exécute, donc pas besoin de les refaire ici — les
répéter lèverait une erreur (set_page_config ne peut être appelé qu'une
fois par run)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from src.annuaire import render_fiche_header, render_fiche_sections
from src.db.factory import get_admin_store, get_store


def _store_pour_lecture_publique():
    """Même repli que l'Observatoire (voir sa propre note) : get_all_answers_
    by_contributeur() filtre d'abord par contributeurs non bloqués, une
    lecture que RLS n'autorise qu'à voir ses PROPRES lignes — pour un
    visiteur anonyme, ça viderait les réponses de tout le monde par excès
    de prudence. Seules des synthèses déjà publiques (lieu_derive) quittent
    cette page, jamais de donnée nominative, donc contourner RLS ici reste
    sûr. Repli sur le store public si la clé service_role n'est pas
    configurée."""
    try:
        return get_admin_store()
    except RuntimeError:
        return get_store()


lieu_id = st.query_params.get("lieu")
if not lieu_id:
    st.title("Fiche d'un lieu")
    st.info("Aucun lieu spécifié — ce lien doit être ouvert via le bouton « 🔗 Partager » "
            "d'une fiche dans l'Annuaire.")
    st.stop()

store = _store_pour_lecture_publique()
lieux = {l.id: l for l in store.list_tiers_lieux()}
lieu = lieux.get(lieu_id)
if lieu is None:
    st.title("Fiche d'un lieu")
    st.error("Ce lieu est introuvable — le lien est peut-être incorrect ou le lieu a été supprimé.")
    st.stop()

derive = store.get_lieu_derive(lieu.id)
st.caption("Fiche publique, en lecture seule — partagée depuis l'Annuaire.")
render_fiche_header(lieu, derive)
render_fiche_sections(store, lieu, derive)
