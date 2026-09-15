"""Vue agrégée en lecture seule : pour chaque tiers-lieu, une fiche de
synthèse qui compile les contributions de tous les répondants (tous rôles
confondus), avec la provenance de chaque élément qualitatif, plus les
coordonnées pour une carte. Ne collecte rien — lit uniquement ce que
l'agent de collecte / le pipeline d'enrichissement ont déjà produit.
"""

from __future__ import annotations

import hashlib

import streamlit as st

from .db.store import Store
from .questionnaire.schema import all_fields

# Palette de secours pour la vignette d'un lieu sans photo — couleur stable
# par lieu (dérivée du nom), pas aléatoire à chaque rechargement.
_PALETTE = ["#E07A5F", "#3D5A80", "#81B29A", "#F2CC8F", "#6D597A", "#B56576", "#457B9D"]
_EMOJI_PAR_MOT_CLE = [
    (("aliment", "nourric", "maraîch", "agricole", "ferme"), "🌾"),
    (("fabric", "numérique", "fablab", "makerspace", "atelier"), "🛠️"),
    (("cultur", "art", "spectacle", "musique"), "🎨"),
    (("coworking", "bureau", "travail"), "💼"),
    (("insertion", "formation", "emploi"), "🎓"),
    (("social", "solidaire", "cohésion"), "🤝"),
    (("écolog", "circulaire", "recycl", "durab"), "♻️"),
]


def default_visual(nom_lieu: str, donnees: dict | None = None) -> tuple[str, str]:
    """Vignette par défaut (emoji + couleur) quand aucune photo n'est
    renseignée — stable par lieu, dérivée de son nom et de ses mots-clés."""
    couleur = _PALETTE[int(hashlib.sha256(nom_lieu.encode("utf-8")).hexdigest(), 16) % len(_PALETTE)]
    texte_reference = ""
    if donnees:
        texte_reference = (str(donnees.get("activites", "")) + " " +
                            " ".join(donnees.get("mots_cles") or [])).lower()
    for mots, emoji in _EMOJI_PAR_MOT_CLE:
        if any(m in texte_reference for m in mots):
            return emoji, couleur
    return "🏘️", couleur


def vignette_html(emoji: str, couleur: str, hauteur: str = "9rem") -> str:
    return (
        f'<div style="width:100%;height:{hauteur};border-radius:8px;background:{couleur};'
        f'display:flex;align-items:center;justify-content:center;font-size:2.2rem;">{emoji}</div>'
    )


def photo_html(url: str, hauteur: str = "9rem") -> str:
    """Rendu HTML brut plutôt que st.image() : object-fit:cover force une
    hauteur/largeur identique pour toutes les vignettes de la galerie
    (Annuaire, Portfolio, popup), quel que soit le format d'origine de la
    photo — st.image() seul affiche chaque image à son ratio propre, ce qui
    donnait une grille aux hauteurs de carte irrégulières.

    Ces trois fonctions (vignette_html, photo_html, category_chips_html)
    vivent ici plutôt que dans app.py : app.py exécute st.set_page_config()
    à l'import, donc l'importer depuis src/pages/2_Portfolio.py (une page
    Streamlit distincte) relancerait toute son exécution — annuaire.py, lui,
    est un module pur, importable en toute sécurité par app.py ET par
    chaque page, ce qui garantit une seule et même apparence de galerie
    partout plutôt que deux implémentations HTML dupliquées à maintenir en
    parallèle."""
    return (
        f'<img src="{url}" style="width:100%;height:{hauteur};border-radius:8px;'
        f'object-fit:cover;display:block;" />'
    )


_CATEGORY_COLORS = {
    "Alimentaire": "#C97A3D", "Culturel": "#8B4B6B", "Éducation": "#3D6E8C", "Santé": "#4F7A52",
}


def texte_en_points(texte: str) -> str:
    """Reformate un texte de synthèse en liste à puces plutôt qu'un seul
    paragraphe dense : le prompt d'enrichissement homogénéise la LONGUEUR de
    chaque section (150-220 caractères), pas sa forme — le résultat est
    souvent une suite de faits juxtaposés séparés par des points, plus
    lisible une fois éclatée en puces qu'en bloc continu. Purement un
    réaffichage : ne modifie ni ne réenrichit la donnée elle-même."""
    if not texte or texte == "—":
        return texte
    phrases = [p.strip() for p in texte.replace("\n", " ").split(". ")]
    phrases = [p if p.endswith((".", "!", "?")) else p + "." for p in phrases if p]
    if len(phrases) <= 1:
        return texte
    return "\n".join(f"- {p}" for p in phrases)


def category_chips_html(categories: list) -> str:
    if not categories:
        return ""
    chips = "".join(
        f'<span style="background:{_CATEGORY_COLORS.get(c, "#888")};color:#fff;font-size:0.72rem;'
        f'padding:2px 8px;border-radius:10px;margin-right:4px;display:inline-block;'
        f'margin-bottom:4px;">{c}</span>'
        for c in categories
    )
    return f'<div style="margin:4px 0;">{chips}</div>'


_LABELS_BY_FIELD_ID = {f.id: f.label for _, _, f in all_fields()}

# Ordre et libellés d'affichage des sections homogénéisées de l'Annuaire —
# doit correspondre à agent.enrichissement.CHAMPS_LONGUEUR_CIBLE + resume.
SECTIONS_SYNTHESE = [
    ("resume", "Résumé"),
    ("activites", "Activités"),
    ("publics", "Publics"),
    ("territoire", "Territoire"),
    ("gouvernance", "Gouvernance"),
    ("ressources", "Ressources"),
    ("besoins", "Besoins"),
    ("modele_economique", "Modèle économique"),
    ("partenaires", "Partenaires"),
    ("competences", "Compétences"),
    ("projets", "Projets"),
    ("enjeux", "Enjeux"),
]


def field_label(champ_id: str) -> str:
    if champ_id.startswith("libre::"):
        return champ_id[len("libre::"):].strip() or champ_id
    return _LABELS_BY_FIELD_ID.get(champ_id, champ_id)


def build_fiche_lieu(store: Store, tiers_lieu) -> dict:
    """Compile une fiche de synthèse multi-répondants pour un lieu donné."""
    par_contributeur = store.get_all_answers_by_contributeur(tiers_lieu.id)
    notes = store.get_free_text_notes(tiers_lieu.id)

    par_champ: dict = {}
    for contributeur_id, reponses in par_contributeur.items():
        for champ_id, valeur in reponses.items():
            par_champ.setdefault(champ_id, []).append({
                "contributeur_id": contributeur_id,
                "valeur": valeur,
            })

    return {
        "tiers_lieu": tiers_lieu,
        "nombre_contributeurs": len(par_contributeur),
        "par_champ": {
            field_label(champ_id): entries for champ_id, entries in par_champ.items()
        },
        "temoignages": [
            {"section": n.get("section_id"), "texte": n["texte"]} for n in notes
        ],
    }


def source_items_for_section(section_key: str, lieu_derive, notes: list, par_contributeur: dict) -> list:
    """Résout les identifiants de provenance d'une section de synthèse
    (lieu_derive.sources[section_key], ex. ["milieu", "note_2"]) vers leur
    contenu brut affichable dans le popup de sources.

    `notes`/`par_contributeur` sont pré-chargés par l'appelant (une seule
    fois pour tout le lieu) plutôt que refetchés ici : cette fonction est
    appelée une fois par section affichée (jusqu'à 11 fois pour un même
    lieu) — les refetcher à chaque appel multipliait les allers-retours
    réseau par 11 pour rien, l'une des causes de la lenteur de la fiche."""
    if not lieu_derive or not lieu_derive.sources:
        return []
    ids = lieu_derive.sources.get(section_key, [])
    if not ids:
        return []

    items = []
    for source_id in ids:
        if source_id.startswith("note_"):
            try:
                idx = int(source_id.split("_", 1)[1])
            except ValueError:
                continue
            if 0 <= idx < len(notes):
                items.append({"type": "note", "label": "Note libre", "valeur": notes[idx]["texte"]})
        else:
            for contributeur_id, reponses in par_contributeur.items():
                if source_id in reponses:
                    items.append({
                        "type": "reponse",
                        "label": field_label(source_id),
                        "valeur": reponses[source_id],
                        "contributeur_id": contributeur_id,
                    })
    return items


def build_annuaire(store: Store) -> list:
    """Fiches de synthèse pour tous les lieux recensés (toutes personnes confondues)."""
    lieux = store.list_tiers_lieux()
    return [build_fiche_lieu(store, lieu) for lieu in lieux]


def render_fiche_header(lieu, derive, nombre_contributeurs: int | None = None) -> None:
    """Vignette/photo + nom + pays/région + catégories + résumé — partie
    commune au dialogue de fiche de l'Annuaire (connecté) et à la page de
    partage publique (sans connexion), pour ne pas dupliquer ce rendu."""
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
        suffixe_contrib = f" · {nombre_contributeurs} contributeur(s)" if nombre_contributeurs is not None else ""
        st.caption(
            f"{lieu.pays or 'pays non renseigné'} — {lieu.region or 'région non renseignée'}{suffixe_contrib}"
        )
        if donnees.get("categories"):
            st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
        if derive:
            st.write(donnees.get("resume", ""))
            if derive.lien_externe:
                st.markdown(f"[🔗 Fiche externe]({derive.lien_externe})")
        else:
            st.info("Pas encore de synthèse générée pour ce lieu.")


def render_fiche_sections(store: Store, lieu, derive) -> None:
    """Grille « Activités / Publics / Territoire... » avec sources — même
    contenu, même mise en page dans le dialogue Annuaire et la page de
    partage publique. Ne montre jamais les réponses brutes/témoignages
    (contrairement au dialogue Annuaire, réservé aux utilisateurs connectés) :
    ici, seules les synthèses déjà curées par l'enrichissement IA sont
    affichées, jamais le détail nominatif des réponses."""
    if not derive:
        return
    st.divider()
    donnees = derive.donnees
    notes_lieu = store.get_free_text_notes(lieu.id)
    reponses_lieu = store.get_all_answers_by_contributeur(lieu.id)
    sections_avec_sources = []
    for cle, titre in SECTIONS_SYNTHESE[1:]:  # sans "resume", déjà affiché par render_fiche_header
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


def lieux_avec_coordonnees(store: Store) -> list:
    return [
        {"id": l.id, "nom": l.nom, "lat": l.latitude, "lon": l.longitude}
        for l in store.list_tiers_lieux()
        if l.latitude is not None and l.longitude is not None
    ]
