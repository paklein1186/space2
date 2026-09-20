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
from .i18n import t, t_categorie
from .questionnaire.schema import all_fields, field_label  # noqa: F401 (field_label ré-exporté)

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
    """`categories` : valeurs canoniques françaises (clé de couleur ET de
    filtre) — seul le texte affiché dans le chip passe par t_categorie(),
    jamais la clé de couleur ni la valeur stockée."""
    if not categories:
        return ""
    chips = "".join(
        f'<span style="background:{_CATEGORY_COLORS.get(c, "#888")};color:#fff;font-size:0.72rem;'
        f'padding:2px 8px;border-radius:10px;margin-right:4px;display:inline-block;'
        f'margin-bottom:4px;">{t_categorie(c)}</span>'
        for c in categories
    )
    return f'<div style="margin:4px 0;">{chips}</div>'


def besoins_chips_html(besoins: list) -> str:
    """Besoins mis en avant par le steward/admin (lieu_derive.besoins_mis_en_
    avant, sous-ensemble curé de types_soutien_souhaites) — couleur distincte
    des catégories (ambre plutôt que la palette par thème) pour se lire
    comme un appel plutôt qu'une classification."""
    if not besoins:
        return ""
    chips = "".join(
        f'<span style="background:#D97706;color:#fff;font-size:0.72rem;'
        f'padding:2px 8px;border-radius:10px;margin-right:4px;display:inline-block;'
        f'margin-bottom:4px;">📣 {b}</span>'
        for b in besoins
    )
    return f'<div style="margin:4px 0;">{chips}</div>'



# Ordre et clés i18n des sections homogénéisées de l'Annuaire — doit
# correspondre à agent.enrichissement.CHAMPS_LONGUEUR_CIBLE + resume. Le
# libellé n'est PAS résolu ici (module chargé une fois à l'import, avant
# qu'une langue soit choisie) : chaque appelant fait t(cle_i18n) au moment
# de l'affichage, pour réagir à la bascule de langue en cours de session.
SECTIONS_SYNTHESE = [
    ("resume", "section.resume"),
    ("activites", "section.activites"),
    ("publics", "section.publics"),
    ("territoire", "section.territoire"),
    ("gouvernance", "section.gouvernance"),
    ("ressources", "section.ressources"),
    ("besoins", "section.besoins"),
    ("modele_economique", "section.modele_economique"),
    ("partenaires", "section.partenaires"),
    ("competences", "section.competences"),
    ("projets", "section.projets"),
    ("enjeux", "section.enjeux"),
]


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
                items.append({"type": "note", "label": t("fiche.note_libre"), "valeur": notes[idx]["texte"]})
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


def donnees_a_afficher(store: Store, derive) -> dict:
    """`derive.donnees`, traduit à la volée en anglais si la langue active
    est l'anglais (mis en cache, voir agent.traduction.traduire_donnees_
    fiche) — sinon le français tel quel. Import différé (traduction.py
    importe enrichissement.py, qui importe annuaire.py : un import en tête
    de module créerait un cycle).

    Si une traduction en cache existe déjà mais est périmée (le français a
    changé depuis), elle est affichée IMMÉDIATEMENT (un "tampon" sur la
    dernière version connue) plutôt que de bloquer l'affichage derrière un
    nouvel appel LLM — la retraduction se lance quand même dans la foulée,
    et un st.rerun() bascule sur la version fraîche dès qu'elle est prête.
    Seule la toute première traduction d'un lieu (aucun cache du tout)
    bloque encore, faute de quoi que ce soit d'autre à montrer."""
    if not derive:
        return {}
    if st.session_state.get("ui_lang", "fr") != "en":
        return derive.donnees

    from .agent.traduction import traduire_donnees_fiche

    a_jour = derive.donnees_en and derive.donnees_en_source_hash == derive.source_hash
    if a_jour:
        return derive.donnees_en

    if not derive.donnees_en:
        with st.spinner(t("fiche.traduction_en_cours")):
            return traduire_donnees_fiche(store, derive)

    # Cache périmé : affiché tel quel, retraduction déclenchée une seule
    # fois par affichage (render_fiche_header ET render_fiche_sections
    # appellent tous deux cette fonction pour la même fiche ouverte). Le
    # hash source fait partie de la clé : si le contenu change ENCORE plus
    # tard, une nouvelle tentative doit pouvoir se relancer plutôt que de
    # rester bloquée sur un marqueur posé pour un hash différent, déjà
    # obsolète lui aussi.
    cle_deja_lancee = f"retraduction_lancee::{derive.tiers_lieu_id}::{derive.source_hash}"
    if not st.session_state.get(cle_deja_lancee):
        st.session_state[cle_deja_lancee] = True
        fraiche = traduire_donnees_fiche(store, derive)
        # `is not derive.donnees` : traduire_donnees_fiche() retourne cet
        # objet précis (même référence) quand elle échoue et retombe sur le
        # français — un rerun basculerait alors vers du français affiché
        # comme si c'était la traduction, pire que garder l'ancien anglais.
        if fraiche is not derive.donnees and fraiche != derive.donnees_en:
            st.session_state.pop(cle_deja_lancee, None)
            st.rerun()
    return derive.donnees_en


def render_fiche_header(store: Store, lieu, derive, nombre_contributeurs: int | None = None) -> None:
    """Vignette/photo + nom + pays/région + catégories + résumé — partie
    commune au dialogue de fiche de l'Annuaire (connecté) et à la page de
    partage publique (sans connexion), pour ne pas dupliquer ce rendu."""
    donnees = donnees_a_afficher(store, derive)
    col_vignette, col_info = st.columns([1, 2.5])
    with col_vignette:
        if derive and derive.photo_url:
            st.markdown(photo_html(derive.photo_url, hauteur="10rem"), unsafe_allow_html=True)
        else:
            emoji, couleur = default_visual(lieu.nom, donnees)
            st.markdown(vignette_html(emoji, couleur, hauteur="10rem"), unsafe_allow_html=True)
    with col_info:
        st.markdown(f"### {lieu.nom}")
        suffixe_contrib = (
            t("fiche.contributeurs_suffixe", n=nombre_contributeurs) if nombre_contributeurs is not None else ""
        )
        st.caption(
            f"{lieu.pays or t('fiche.pays_non_renseigne')} — "
            f"{lieu.region or t('fiche.region_non_renseignee')}{suffixe_contrib}"
        )
        if donnees.get("categories"):
            st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
        if derive and derive.besoins_mis_en_avant:
            st.markdown(besoins_chips_html(derive.besoins_mis_en_avant), unsafe_allow_html=True)
        if derive:
            st.write(donnees.get("resume", ""))
            if derive.lien_externe:
                st.markdown(f"[{t('fiche.lien_externe')}]({derive.lien_externe})")
        else:
            st.info(t("fiche.pas_de_synthese"))


def render_fiche_sections(store: Store, lieu, derive, montrer_sources: bool = True) -> None:
    """Grille « Activités / Publics / Territoire... » — même contenu, même
    mise en page dans le dialogue Annuaire et la page de partage publique.

    `montrer_sources=False` (page de partage publique, sans connexion) :
    n'affiche que les synthèses déjà curées par l'enrichissement IA, jamais
    le popover "Sources" ni les réponses brutes/témoignages sous-jacents —
    et ne va même pas les chercher, pour ne jamais exposer de détail
    nominatif à un visiteur anonyme via ce chemin (get_free_text_notes /
    get_all_answers_by_contributeur passent par le store admin sur cette
    page, voir 3_Fiche.py, donc contournent RLS)."""
    if not derive:
        return
    st.divider()
    donnees = donnees_a_afficher(store, derive)
    sections_avec_sources = []
    if montrer_sources:
        notes_lieu = store.get_free_text_notes(lieu.id)
        reponses_lieu = store.get_all_answers_by_contributeur(lieu.id)
        for cle, titre_key in SECTIONS_SYNTHESE[1:]:  # sans "resume", déjà affiché par render_fiche_header
            sources = source_items_for_section(cle, derive, notes_lieu, reponses_lieu)
            if sources:
                sections_avec_sources.append((cle, titre_key, sources))
    else:
        sections_avec_sources = [
            (cle, titre_key, None) for cle, titre_key in SECTIONS_SYNTHESE[1:] if donnees.get(cle)
        ]

    if sections_avec_sources:
        cols = st.columns(3)
        for i, (cle, titre_key, sources) in enumerate(sections_avec_sources):
            texte = donnees.get(cle) or "—"
            with cols[i % 3]:
                st.markdown(f"**{t(titre_key)}**")
                st.caption(texte_en_points(texte))
                if montrer_sources:
                    with st.popover(t("fiche.sources"), use_container_width=True):
                        for s in sources:
                            st.markdown(f"**{s['label']}** : {s['valeur']}")
    else:
        st.caption(t("fiche.pas_assez_infos"))


def lieux_avec_coordonnees(lieux: list) -> list:
    """`lieux` : la liste déjà filtrée à afficher (recherche/pays/région/
    catégorie) — pas un nouvel appel à store.list_tiers_lieux(), pour que la
    carte reflète les mêmes lieux que la grille en dessous plutôt que
    systématiquement tous les lieux recensés (vécu : filtrer par pays ne
    changeait rien à la carte)."""
    return [
        {"id": l.id, "nom": l.nom, "lat": l.latitude, "lon": l.longitude}
        for l in lieux
        if l.latitude is not None and l.longitude is not None
    ]
