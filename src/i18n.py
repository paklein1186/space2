"""Traduction légère du "chrome" de l'interface (navigation, écran de
connexion, en-têtes de page, barre latérale) — pas le contenu du
questionnaire, ni les échanges avec l'agent, ni les fiches lieu, qui restent
en français pour l'instant : les traduire correctement demanderait soit de
dupliquer l'intégralité du schéma (121 champs) dans chaque langue, soit une
traduction à la volée par LLM à chaque affichage (coût et latence non
négligeables) — un choix d'ampleur différente, à trancher séparément si
besoin, pas embarqué silencieusement ici.

Même mécanique que le thème clair/sombre (src/theme.py) : un simple bouton
en barre latérale, mémorisé dans st.session_state ET dans un cookie (les
pages de src/pages/ sont des scripts indépendants, session_state seul ne
suffit pas à s'y propager de façon fiable)."""

from __future__ import annotations

import streamlit as st

LANG_DEFAULT = "fr"
LANGUAGES = ("fr", "en")

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "nav.entretien": {"fr": "Compléter l'histoire", "en": "Complete the story"},
    "nav.bibliotheque": {"fr": "Bibliothèque", "en": "Library"},
    "nav.lieux_hybrides": {"fr": "Lieux hybrides", "en": "Hybrid spaces"},
    "nav.observatoire": {"fr": "Observatoire", "en": "Observatory"},
    "nav.portfolio": {"fr": "Portfolio", "en": "Portfolio"},
    "nav.fiche": {"fr": "Fiche partagée", "en": "Shared record"},
    "nav.administration": {"fr": "Administration", "en": "Administration"},

    "auth.title": {"fr": "Lieux hybrides et territoires", "en": "Hybrid spaces and territories"},
    "auth.email_label": {"fr": "Votre email", "en": "Your email"},
    "auth.send_code": {"fr": "Recevoir un code de connexion", "en": "Send a login code"},
    "auth.code_sent": {"fr": "Un code a été envoyé à **{email}**.", "en": "A code was sent to **{email}**."},
    "auth.code_label": {"fr": "Code reçu par email", "en": "Code received by email"},
    "auth.verify": {"fr": "Valider", "en": "Verify"},
    "auth.change_email": {"fr": "Changer d'email", "en": "Change email"},
    "auth.invalid_code": {"fr": "Code invalide ou expiré.", "en": "Invalid or expired code."},

    "sidebar.connected_as": {"fr": "Connecté·e : {email}", "en": "Signed in as: {email}"},
    "sidebar.logout": {"fr": "Se déconnecter", "en": "Log out"},
    "sidebar.admin_local_mode": {
        "fr": "Mode admin local (LOCAL_DEV_AUTOLOGIN) — accès complet sans RLS.",
        "en": "Local admin mode (LOCAL_DEV_AUTOLOGIN) — full access, RLS bypassed.",
    },

    "theme.light": {"fr": "☀️ Mode clair", "en": "☀️ Light mode"},
    "theme.dark": {"fr": "🌙 Mode sombre", "en": "🌙 Dark mode"},
    "lang.toggle": {"fr": "🇬🇧 English", "en": "🇫🇷 Français"},

    "entretien.title": {"fr": "Compléter l'histoire", "en": "Complete the story"},
    "bibliotheque.title": {"fr": "Bibliothèque", "en": "Library"},
    "bibliotheque.caption": {
        "fr": "Interrogez en langage naturel l'ensemble des lieux recensés et des documents déposés.",
        "en": "Ask, in plain language, about all the recorded spaces and uploaded documents.",
    },
    "lieux_hybrides.title": {"fr": "Lieux hybrides", "en": "Hybrid spaces"},
    "lieux_hybrides.caption": {
        "fr": "L'annuaire de l'ensemble des tiers-lieux recensés.",
        "en": "The directory of all recorded hybrid spaces.",
    },
    "observatoire.title": {
        "fr": "Observatoire des lieux hybrides et territoires",
        "en": "Observatory of hybrid spaces and territories",
    },
    "observatoire.caption": {
        "fr": "Relevés statistiques, publics, sur l'ensemble des lieux recensés dans l'Annuaire.",
        "en": "Public statistical overview of all the spaces recorded in the Directory.",
    },
    "portfolio.title": {"fr": "Portfolio", "en": "Portfolio"},
    "portfolio.caption": {
        "fr": "Une sélection de lieux et de leurs campagnes de besoins actuelles.",
        "en": "A selection of spaces and their current fundraising/support campaigns.",
    },
    "chat.entretien_placeholder": {"fr": "Votre réponse...", "en": "Your answer..."},
    "chat.bibliotheque_placeholder": {
        "fr": "Posez une question sur les lieux recensés ou les documents déposés...",
        "en": "Ask a question about the recorded spaces or uploaded documents...",
    },
    "voice.dicter_reponse": {"fr": "Dicter la réponse", "en": "Dictate your answer"},
    "voice.dicter_question": {"fr": "Dicter la question", "en": "Dictate your question"},

    "bibliotheque.conversations_titre": {"fr": "Vos conversations", "en": "Your conversations"},
    "bibliotheque.nouvelle_conversation": {"fr": "＋ Nouvelle conversation", "en": "＋ New conversation"},
    "bibliotheque.aucune_conversation": {
        "fr": "Aucune conversation précédente — posez une question pour commencer.",
        "en": "No previous conversation yet — ask a question to get started.",
    },
    "bibliotheque.supprimer_conversation": {"fr": "Supprimer", "en": "Delete"},
    "bibliotheque.questions_frequentes": {"fr": "Questions fréquentes", "en": "Frequently asked"},
    "bibliotheque.question_frequente_1": {
        "fr": "Combien de lieux sont recensés, et où sont-ils situés ?",
        "en": "How many spaces are recorded, and where are they located?",
    },
    "bibliotheque.question_frequente_2": {
        "fr": "Quels sont les besoins les plus fréquents exprimés par les lieux ?",
        "en": "What are the most common needs expressed by the spaces?",
    },
    "bibliotheque.question_frequente_3": {
        "fr": "Quelles bonnes pratiques de financement reviennent souvent ?",
        "en": "Which funding best practices come up often?",
    },
    "bibliotheque.question_frequente_4": {
        "fr": "Qu'est-ce qu'un tiers-lieu hybride ?",
        "en": "What is a hybrid third place?",
    },

    "nav.compte": {"fr": "Compte", "en": "Account"},
    "contribution.title": {"fr": "Votre contribution", "en": "Your contribution"},
    "contribution.lieu_label": {"fr": "Tiers-lieu", "en": "Hybrid space"},
    "contribution.nom_nouveau_lieu": {"fr": "Nom du nouveau lieu", "en": "Name of the new space"},
    "contribution.role_label": {"fr": "Votre rôle vis-à-vis de ce lieu", "en": "Your role regarding this space"},
    "contribution.choisir_pour_demarrer": {
        "fr": "Choisissez ou créez un tiers-lieu ci-dessus pour démarrer.",
        "en": "Choose or create a hybrid space above to get started.",
    },
    "role.fondateur": {"fr": "Fondateur·rice / porteur de projet", "en": "Founder / project lead"},
    "role.equipe": {"fr": "Équipe opérationnelle", "en": "Operational team"},
    "role.partenaire": {"fr": "Partie prenante externe", "en": "External stakeholder"},
    "role.usager": {"fr": "Usager régulier", "en": "Regular user"},
    "role.steward": {
        "fr": "Steward (je continue à nourrir ce lieu)",
        "en": "Steward (I keep contributing to this space)",
    },
    "role.autre": {"fr": "Autre", "en": "Other"},

    "fiche.contributeurs_suffixe": {"fr": " · {n} contributeur(s)", "en": " · {n} contributor(s)"},
    "fiche.pays_non_renseigne": {"fr": "pays non renseigné", "en": "country not specified"},
    "fiche.region_non_renseignee": {"fr": "région non renseignée", "en": "region not specified"},
    "fiche.pas_de_synthese": {
        "fr": "Pas encore de synthèse générée pour ce lieu.",
        "en": "No synthesis generated for this space yet.",
    },
    "fiche.lien_externe": {"fr": "🔗 Fiche externe", "en": "🔗 External record"},
    "fiche.sources": {"fr": "Sources", "en": "Sources"},
    "fiche.note_libre": {"fr": "Note libre", "en": "Free-form note"},
    "fiche.pas_assez_infos": {
        "fr": "Pas encore assez d'informations déclarées pour détailler ce lieu par thème.",
        "en": "Not enough information declared yet to break this space down by theme.",
    },

    "section.resume": {"fr": "Résumé", "en": "Summary"},
    "section.activites": {"fr": "Activités", "en": "Activities"},
    "section.publics": {"fr": "Publics", "en": "Audiences"},
    "section.territoire": {"fr": "Territoire", "en": "Territory"},
    "section.gouvernance": {"fr": "Gouvernance", "en": "Governance"},
    "section.ressources": {"fr": "Ressources", "en": "Resources"},
    "section.besoins": {"fr": "Besoins", "en": "Needs"},
    "section.modele_economique": {"fr": "Modèle économique", "en": "Economic model"},
    "section.partenaires": {"fr": "Partenaires", "en": "Partners"},
    "section.competences": {"fr": "Compétences", "en": "Skills"},
    "section.projets": {"fr": "Projets", "en": "Projects"},
    "section.enjeux": {"fr": "Enjeux", "en": "Challenges"},

    "fiche_dialog.title": {"fr": "Fiche du lieu", "en": "Space record"},
    "fiche_dialog.partager": {"fr": "🔗 Partager", "en": "🔗 Share"},
    "fiche_dialog.lien_public": {
        "fr": "Lien public en lecture seule, sans connexion nécessaire :",
        "en": "Public read-only link, no login needed:",
    },
    "fiche_dialog.revendiquer_steward": {
        "fr": "🌱 Revendiquer le suivi de ce lieu (steward)",
        "en": "🌱 Claim stewardship of this space",
    },
    "fiche_dialog.steward_toast": {
        "fr": "« {nom} » sélectionné — rendez-vous dans l'onglet Entretien.",
        "en": "“{nom}” selected — head to the Interview tab.",
    },
    "fiche_dialog.modifier_lien_photo": {
        "fr": "Modifier le lien externe / la photo",
        "en": "Edit external link / photo",
    },
    "fiche_dialog.lien_externe_input": {
        "fr": "Lien externe (ex. fiche tiers-lieux.xyz)",
        "en": "External link (e.g. tiers-lieux.xyz record)",
    },
    "fiche_dialog.url_photo": {"fr": "URL de la photo", "en": "Photo URL"},
    "fiche_dialog.enregistrer": {"fr": "Enregistrer", "en": "Save"},
    "fiche_dialog.voir_reponses_brutes": {
        "fr": "Voir toutes les réponses brutes et témoignages",
        "en": "View all raw answers and testimonials",
    },
    "fiche_dialog.temoignages_libres": {"fr": "Témoignages libres", "en": "Free-form testimonials"},

    "moderation.historique_titre": {"fr": "Historique & modération", "en": "History & moderation"},
    "moderation.contributeurs_titre": {"fr": "Contributeurs de ce lieu", "en": "Contributors to this space"},
    "moderation.vous_suffixe": {"fr": " (vous)", "en": " (you)"},
    "moderation.bloque_suffixe": {"fr": " · 🚫 bloqué", "en": " · 🚫 blocked"},
    "moderation.debloquer": {"fr": "Débloquer", "en": "Unblock"},
    "moderation.bloquer": {"fr": "Bloquer", "en": "Block"},
    "moderation.signaler_litige_titre": {"fr": "Signaler un litige", "en": "Report a dispute"},
    "moderation.description_desaccord": {"fr": "Description du désaccord", "en": "Description of the disagreement"},
    "moderation.contributeur_concerne": {
        "fr": "Contributeur concerné (optionnel)",
        "en": "Contributor involved (optional)",
    },
    "moderation.signaler": {"fr": "Signaler", "en": "Report"},
    "moderation.decrire_avant_signaler": {
        "fr": "Décrivez le désaccord avant de signaler.",
        "en": "Describe the disagreement before reporting it.",
    },
    "moderation.litige_signale": {"fr": "Litige signalé.", "en": "Dispute reported."},
    "moderation.litiges_titre": {"fr": "Litiges", "en": "Disputes"},
    "moderation.resolu": {"fr": "🟢 résolu", "en": "🟢 resolved"},
    "moderation.ouvert": {"fr": "🔴 ouvert", "en": "🔴 open"},
    "moderation.resoudre": {"fr": "Résoudre", "en": "Resolve"},
    "moderation.historique_recent_titre": {"fr": "Historique récent", "en": "Recent history"},
    "moderation.aucun_historique": {"fr": "Aucun historique pour l'instant.", "en": "No history yet."},
    "moderation.note_libre_champ": {"fr": "note libre", "en": "free-form note"},

    "entretien.anthropic_manquant": {
        "fr": "ANTHROPIC_API_KEY n'est pas configuré (voir .env.example).",
        "en": "ANTHROPIC_API_KEY is not configured (see .env.example).",
    },
    "entretien.par_ou_commencer": {"fr": "Par où commencer ?", "en": "Where to start?"},
    "entretien.mode_histoire_btn": {"fr": "📖 Nourrir l'histoire du lieu", "en": "📖 Build the space's story"},
    "entretien.mode_histoire_caption": {
        "fr": "Genèse, défis, description, fonctionnement — l'entretien complet, comme d'habitude.",
        "en": "Origins, challenges, description, day-to-day — the full interview, as usual.",
    },
    "entretien.mode_campagne_btn": {"fr": "📋 Remplir une campagne en cours", "en": "📋 Fill in an ongoing campaign"},
    "entretien.mode_campagne_btn_vide": {"fr": "📋 Aucune campagne active", "en": "📋 No active campaign"},
    "entretien.mode_campagne_caption": {
        "fr": "Répondre en priorité à un recensement ciblé actuellement ouvert par l'équipe.",
        "en": "Answer, as a priority, a targeted survey the team currently has open.",
    },
    "entretien.mode_besoins_btn": {"fr": "📣 Rendre visibles vos besoins actuels", "en": "📣 Make your current needs visible"},
    "entretien.mode_besoins_caption": {
        "fr": "Exprimer directement de quoi le lieu aurait besoin — utilisé dans l'Annuaire "
              "et pour la curation du Portfolio.",
        "en": "State directly what the space could use — shown in the Directory and used to "
              "curate the Portfolio.",
    },
    "entretien.progression_campagne": {
        "fr": "Formulaire de cette campagne complété à {pourcentage}% ({repondus}/{total} questions)",
        "en": "This campaign's form is {pourcentage}% complete ({repondus}/{total} questions)",
    },
    "entretien.transmettre_source_titre": {
        "fr": "📎 Transmettre un site, un document, ou un texte",
        "en": "📎 Share a site, a document, or some text",
    },
    "entretien.transmettre_source_caption": {
        "fr": "De quoi enrichir l'entretien sans tout retaper : un lien vers votre site, un document "
              "existant (charte, plaquette, rapport...), ou un texte collé. L'agent en tire ce qui est "
              "utile puis poursuit l'entretien avec.",
        "en": "A way to enrich the interview without retyping everything: a link to your site, an "
              "existing document (charter, brochure, report...), or pasted text. The agent picks out "
              "what's useful and continues the interview with it.",
    },
    "entretien.url_a_analyser": {"fr": "URL d'un site à analyser", "en": "URL of a site to analyze"},
    "entretien.analyser_site_btn": {"fr": "Analyser ce site", "en": "Analyze this site"},
    "entretien.recuperation_page": {"fr": "Récupération de la page...", "en": "Fetching the page..."},
    "entretien.echec_recuperation_page": {
        "fr": "Impossible de récupérer cette page : {erreur}",
        "en": "Could not fetch this page: {erreur}",
    },
    "entretien.deposer_document": {
        "fr": "Déposer un document (txt, docx, pdf)", "en": "Upload a document (txt, docx, pdf)",
    },
    "entretien.analyser_document_btn": {"fr": "Analyser ce document", "en": "Analyze this document"},
    "entretien.lecture_document": {"fr": "Lecture du document...", "en": "Reading the document..."},
    "entretien.echec_lecture_document": {
        "fr": "Impossible de lire ce document : {erreur}", "en": "Could not read this document: {erreur}",
    },
    "entretien.coller_texte": {
        "fr": "Coller un texte (extrait d'un document, description existante...)",
        "en": "Paste some text (excerpt from a document, existing description...)",
    },
    "entretien.analyser_texte_btn": {"fr": "Analyser ce texte", "en": "Analyze this text"},
    "entretien.apport_integre": {
        "fr": "**Intégré à l'entretien** — {label}\n\n{resume}",
        "en": "**Added to the interview** — {label}\n\n{resume}",
    },
    "entretien.agent_reflechit": {"fr": "L'agent réfléchit...", "en": "The agent is thinking..."},
    "entretien.reponse_rapide_aucun": {"fr": "(aucun)", "en": "(none)"},
    "entretien.reponse_rapide_oui": {"fr": "Oui", "en": "Yes"},
    "entretien.reponse_rapide_non": {"fr": "Non", "en": "No"},
    "entretien.reponse_rapide_oui_btn": {"fr": "✅ Oui", "en": "✅ Yes"},
    "entretien.reponse_rapide_non_btn": {"fr": "❌ Non", "en": "❌ No"},
    "entretien.reponse_rapide_repondre_btn": {"fr": "Répondre", "en": "Answer"},
    "entretien.reponse_rapide_message": {
        "fr": "⚡ {label} : {valeur}", "en": "⚡ {label}: {valeur}",
    },
    "entretien.panneau_reponse_rapide_titre": {"fr": "⚡ Réponse rapide", "en": "⚡ Quick answer"},

    "annuaire.aucun_lieu": {"fr": "Aucun lieu recensé pour l'instant.", "en": "No spaces recorded yet."},
    "annuaire.rechercher_placeholder": {"fr": "🔍 Nom, ville, région...", "en": "🔍 Name, city, region..."},
    "annuaire.filtre_pays": {"fr": "Pays", "en": "Country"},
    "annuaire.filtre_region": {"fr": "Région", "en": "Region"},
    "annuaire.filtre_categorie": {"fr": "Catégorie", "en": "Category"},
    "annuaire.lieux_affiches": {"fr": "{n} lieu(x) affiché(s)", "en": "{n} space(s) shown"},
    "annuaire.chargement_fiche": {"fr": "Chargement de la fiche...", "en": "Loading the record..."},

    "besoins.titre": {"fr": "Besoins mis en avant", "en": "Highlighted needs"},
    "besoins.aucun_declare": {
        "fr": "Aucun besoin déclaré pour l'instant — répondez à « 📣 Rendre visibles vos besoins "
              "actuels » dans l'entretien pour pouvoir en mettre en avant ici.",
        "en": "No needs declared yet — answer “📣 Make your current needs visible” in the "
              "interview to be able to highlight some here.",
    },
    "besoins.cocher_afficher": {
        "fr": "Cochez ceux à afficher publiquement (Annuaire et Portfolio) — les autres besoins "
              "déclarés restent enregistrés mais ne sont pas montrés.",
        "en": "Check the ones to show publicly (Directory and Portfolio) — other declared needs "
              "stay saved but hidden.",
    },
    "besoins.a_mettre_en_avant": {"fr": "Besoins à mettre en avant", "en": "Needs to highlight"},
    "besoins.mis_a_jour": {"fr": "Besoins mis en avant mis à jour.", "en": "Highlighted needs updated."},

    "portfolio_admin.titre": {"fr": "Administration — Portfolio", "en": "Administration — Portfolio"},
    "portfolio_admin.synthese_requise": {
        "fr": "Une synthèse doit d'abord être générée pour ce lieu avant de pouvoir l'inclure au Portfolio.",
        "en": "A synthesis must be generated for this space before it can be included in the Portfolio.",
    },
    "portfolio_admin.inclure": {"fr": "Inclure ce lieu dans le Portfolio public", "en": "Include this space in the public Portfolio"},
    "portfolio_admin.inclure_help": {
        "fr": "Sauvegardé immédiatement, sans passer par le bouton Enregistrer ci-dessous.",
        "en": "Saved immediately, no need for the Save button below.",
    },
    "portfolio_admin.texte_campagne": {
        "fr": "Texte de campagne (appel, contexte des besoins)", "en": "Campaign text (call, context for the needs)",
    },
    "portfolio_admin.objectif": {"fr": "Objectif (ex. montant recherché)", "en": "Goal (e.g. amount sought)"},
    "portfolio_admin.contact": {"fr": "Contact", "en": "Contact"},
    "portfolio_admin.enregistrer_campagne": {"fr": "Enregistrer la campagne", "en": "Save the campaign"},
    "portfolio_admin.campagne_maj": {"fr": "Campagne mise à jour.", "en": "Campaign updated."},

    "fiche_page.title": {"fr": "Fiche d'un lieu", "en": "A space's record"},
    "fiche_page.aucun_lieu_specifie": {
        "fr": "Aucun lieu spécifié — ce lien doit être ouvert via le bouton « 🔗 Partager » "
              "d'une fiche dans l'Annuaire.",
        "en": "No space specified — this link should be opened via the “🔗 Share” button "
              "on a record in the Directory.",
    },
    "fiche_page.lieu_introuvable": {
        "fr": "Ce lieu est introuvable — le lien est peut-être incorrect ou le lieu a été supprimé.",
        "en": "This space could not be found — the link may be wrong, or the space was deleted.",
    },
    "portfolio.campagne_titre": {"fr": "📣 Campagne en cours", "en": "📣 Ongoing campaign"},
    "portfolio.objectif_label": {"fr": "🎯 **Objectif :** {valeur}", "en": "🎯 **Goal:** {valeur}"},
    "portfolio.contact_label": {"fr": "✉️ **Contact :** {valeur}", "en": "✉️ **Contact:** {valeur}"},
    "portfolio.en_savoir_plus": {"fr": "🔗 En savoir plus", "en": "🔗 Learn more"},
    "portfolio.aucun_lieu": {"fr": "Aucun lieu mis en avant pour l'instant.", "en": "No space highlighted yet."},
    "portfolio.filtrer_categorie": {"fr": "Filtrer par catégorie", "en": "Filter by category"},
    "portfolio.toutes_categories": {"fr": "Toutes les catégories", "en": "All categories"},
    "portfolio.aucun_lieu_categorie": {
        "fr": "Aucun lieu ne correspond à cette catégorie.", "en": "No space matches this category.",
    },

    "observatoire.aucune_donnee": {"fr": "Aucune donnée pour l'instant.", "en": "No data yet."},
    "observatoire.chargement": {"fr": "Chargement des données...", "en": "Loading data..."},
    "observatoire.aucun_lieu_enrichi": {
        "fr": "Aucun lieu enrichi pour l'instant — revenez une fois que des synthèses auront été générées.",
        "en": "No enriched space yet — come back once syntheses have been generated.",
    },
    "observatoire.lieux_recenses": {"fr": "Lieux recensés", "en": "Spaces recorded"},
    "observatoire.pays_representes": {"fr": "Pays représentés", "en": "Countries represented"},
    "observatoire.regions_representees": {"fr": "Régions représentées", "en": "Regions represented"},
    "observatoire.surface_batie": {"fr": "Surface bâtie connue", "en": "Known built surface"},
    "observatoire.surface_batie_help": {
        "fr": "Somme sur les {n} lieu(x) ayant renseigné leur surface — sous-estimée, "
              "la plupart des lieux ne l'ont pas encore déclarée.",
        "en": "Sum over the {n} space(s) that reported their surface — an underestimate, "
              "most spaces have not declared it yet.",
    },
    "observatoire.etp_geres": {"fr": "ETP gérés connus", "en": "Known FTEs managed"},
    "observatoire.etp_geres_help": {
        "fr": "Somme sur les {n} lieu(x) ayant renseigné leurs ETP — sous-estimée, "
              "la plupart des lieux ne l'ont pas encore déclaré.",
        "en": "Sum over the {n} space(s) that reported their FTEs — an underestimate, "
              "most spaces have not declared it yet.",
    },
    "observatoire.repartition_categorie": {"fr": "Répartition par catégorie", "en": "Breakdown by category"},
    "observatoire.aucune_categorie": {
        "fr": "Aucune catégorie attribuée pour l'instant.", "en": "No category assigned yet.",
    },
    "observatoire.repartition_pays": {"fr": "Répartition par pays", "en": "Breakdown by country"},
    "observatoire.pays_non_renseigne": {
        "fr": "Pays non renseigné pour l'instant.", "en": "Country not reported yet.",
    },
    "observatoire.repartition_milieu": {"fr": "Répartition par milieu", "en": "Breakdown by setting"},
    "observatoire.milieu_non_renseigne": {
        "fr": "Milieu non renseigné pour l'instant.", "en": "Setting not reported yet.",
    },
    "observatoire.repartition_region": {"fr": "Répartition par région", "en": "Breakdown by region"},
    "observatoire.region_non_renseignee": {
        "fr": "Région non renseignée pour l'instant.", "en": "Region not reported yet.",
    },
    "observatoire.evolution_reseau": {
        "fr": "Évolution du réseau dans le temps", "en": "The network's growth over time",
    },
    "observatoire.evolution_reseau_caption": {
        "fr": "Nombre de lieux ouverts par année (année extraite de la date déclarée).",
        "en": "Number of spaces opened per year (year extracted from the declared date).",
    },
    "observatoire.base_sur_date_ouverture": {
        "fr": "Basé sur les {n} lieu(x) ayant déclaré une date d'ouverture.",
        "en": "Based on the {n} space(s) that reported an opening date.",
    },
    "observatoire.aucune_date_ouverture": {
        "fr": "Aucune date d'ouverture déclarée pour l'instant.", "en": "No opening date reported yet.",
    },
    "observatoire.statut_juridique": {"fr": "Statut juridique", "en": "Legal status"},
    "observatoire.base_sur_statut": {
        "fr": "Basé sur les {n} lieu(x) ayant déclaré leur statut juridique.",
        "en": "Based on the {n} space(s) that reported their legal status.",
    },
    "observatoire.aucun_statut": {
        "fr": "Aucun statut juridique déclaré pour l'instant.", "en": "No legal status reported yet.",
    },
    "observatoire.frequentation_titre": {
        "fr": "Fréquentation, mobilité et rayonnement", "en": "Attendance, mobility and reach",
    },
    "observatoire.frequentation_caption": {
        "fr": "Indicateurs récemment ajoutés au questionnaire (fréquentation, provenance des usagers, "
              "modes de déplacement) — ils s'affichent automatiquement ici au fur et à mesure que des "
              "lieux y répondent.",
        "en": "Indicators recently added to the questionnaire (attendance, where users come from, "
              "modes of transport) — they appear here automatically as spaces answer them.",
    },
    "observatoire.pas_encore_reponse": {
        "fr": "Pas encore de réponse pour cet indicateur.", "en": "No answer for this indicator yet.",
    },
    "observatoire.n_lieux": {"fr": "n = {n} lieu(x)", "en": "n = {n} space(s)"},
    "observatoire.frequentation_moyenne_titre": {
        "fr": "Fréquentation moyenne sur une bonne semaine", "en": "Average attendance over a typical week",
    },
    "observatoire.passages_semaine": {
        "fr": "Passages / semaine (moyenne des lieux répondants)", "en": "Visits / week (average of responding spaces)",
    },
    "observatoire.evolution_frequentation_titre": {
        "fr": "Évolution de la fréquentation (3 ans)", "en": "Change in attendance (3 years)",
    },
    "observatoire.mode_voiture": {"fr": "Part venant en voiture", "en": "Share arriving by car"},
    "observatoire.mode_velo": {"fr": "Part venant à vélo", "en": "Share arriving by bike"},
    "observatoire.mode_pied": {"fr": "Part venant à pied", "en": "Share arriving on foot"},
    "observatoire.mode_transport_commun": {
        "fr": "Part en transport en commun", "en": "Share arriving by public transport",
    },
    "observatoire.provenance_commune": {
        "fr": "Provenance : commune d'implantation", "en": "Origin: host municipality",
    },
    "observatoire.provenance_limitrophe": {
        "fr": "Provenance : commune limitrophe", "en": "Origin: neighboring municipality",
    },
    "observatoire.provenance_plus_loin": {"fr": "Provenance : plus loin", "en": "Origin: further away"},
    "observatoire.mots_cles_titre": {
        "fr": "Mots-clés les plus fréquents", "en": "Most frequent keywords",
    },
    "observatoire.pas_de_mots_cles": {
        "fr": "Pas encore de mots-clés générés.", "en": "No keywords generated yet.",
    },
    "observatoire.enjeux_besoins_titre": {
        "fr": "Enjeux et besoins par catégorie", "en": "Challenges and needs by category",
    },
    "observatoire.enjeux_besoins_caption": {
        "fr": "Vue qualitative : synthèses des enjeux exprimés, groupées par catégorie.",
        "en": "Qualitative view: syntheses of the challenges expressed, grouped by category.",
    },
    "observatoire.besoins_label": {"fr": "Besoins : {texte}", "en": "Needs: {texte}"},
    "observatoire.lieu_x": {"fr": "{n} lieu(x)", "en": "{n} space(s)"},
    "observatoire.besoins_sphere_titre": {"fr": "Besoins par sphère", "en": "Needs by sphere"},
    "observatoire.besoins_sphere_caption": {
        "fr": "Vue synthétique des besoins déclarés à l'entretien (« 📣 Rendre visibles vos besoins "
              "actuels »), regroupés par grande sphère plutôt que listés un par un — dépliez un besoin "
              "pour voir quels lieux précisément l'ont exprimé.",
        "en": "Synthetic view of the needs declared in the interview (“📣 Make your current needs "
              "visible”), grouped by broad sphere rather than listed one by one — expand a need "
              "to see exactly which spaces expressed it.",
    },
    "observatoire.sociosphere": {"fr": "Sociosphère", "en": "Sociosphere"},
    "observatoire.technosphere": {"fr": "Technosphère", "en": "Technosphere"},
    "observatoire.biosphere": {"fr": "Biosphère", "en": "Biosphere"},
    "observatoire.aucun_besoin_declare": {
        "fr": "Aucun besoin déclaré pour l'instant.", "en": "No need declared yet.",
    },
    "observatoire.aucun_besoin_sphere": {
        "fr": "Aucun besoin déclaré dans cette sphère pour l'instant.", "en": "No need declared in this sphere yet.",
    },

    "fiche_page.caption": {
        "fr": "Fiche publique, en lecture seule — partagée depuis l'Annuaire.",
        "en": "Public, read-only record — shared from the Directory.",
    },
    "entretien.contributeur_bloque": {
        "fr": "Votre contribution à ce lieu a été suspendue par un administrateur ou un steward "
              "de ce lieu, suite à un signalement. Contactez l'équipe si vous pensez qu'il s'agit "
              "d'une erreur.",
        "en": "Your contribution to this space was suspended by an admin or steward of this "
              "space, following a report. Contact the team if you think this is a mistake.",
    },
}


_CATEGORIES_TRANSLATIONS: dict[str, dict[str, str]] = {
    "Alimentaire": {"fr": "Alimentaire", "en": "Food"},
    "Culturel": {"fr": "Culturel", "en": "Cultural"},
    "Éducation": {"fr": "Éducation", "en": "Education"},
    "Santé": {"fr": "Santé", "en": "Health"},
}


def _lang() -> str:
    return st.session_state.get("ui_lang", LANG_DEFAULT)


def t_categorie(categorie: str) -> str:
    """Traduit une catégorie de lieu (Alimentaire/Culturel/Éducation/Santé)
    pour l'AFFICHAGE seulement — la valeur canonique stockée (lieu_derive.
    donnees['categories'], filtres, clé de couleur) reste toujours en
    français, unique source de vérité partagée par schema.py/enrichissement/
    Observatoire ; ne jamais faire dépendre un filtre ou une clé de cette
    traduction, seulement le texte montré à l'utilisateur."""
    entry = _CATEGORIES_TRANSLATIONS.get(categorie)
    if entry is None:
        return categorie
    return entry.get(_lang()) or categorie


def t(key: str, **kwargs) -> str:
    """Traduit `key` dans la langue active (repli sur le français, puis sur
    `key` elle-même si la clé n'existe pas — pour ne jamais planter sur une
    traduction manquante)."""
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        return key
    text = entry.get(_lang()) or entry.get(LANG_DEFAULT) or key
    return text.format(**kwargs) if kwargs else text


def language_toggle() -> str:
    """Affiche le bouton de bascule FR/EN en barre latérale (à appeler une
    fois par script, juste après apply_theme()) et renvoie la langue active.
    Persisté en cookie comme le thème — voir la note dans theme.apply_theme()
    sur pourquoi st.session_state seul ne suffit pas entre les pages."""
    from src.auth_session import LANG_COOKIE_NAME, read_cookie, save_cookie

    if "ui_lang" not in st.session_state:
        st.session_state["ui_lang"] = LANG_DEFAULT
        st.session_state["ui_lang_user_set"] = False

    if not st.session_state.get("ui_lang_user_set"):
        cookie_value = read_cookie(LANG_COOKIE_NAME)
        if cookie_value in LANGUAGES:
            st.session_state["ui_lang"] = cookie_value

    def _basculer_langue() -> None:
        st.session_state["ui_lang"] = "en" if st.session_state["ui_lang"] == "fr" else "fr"
        st.session_state["ui_lang_user_set"] = True
        save_cookie(LANG_COOKIE_NAME, st.session_state["ui_lang"])

    st.sidebar.button(
        t("lang.toggle"), key="ui_lang_toggle", on_click=_basculer_langue, use_container_width=True,
    )
    return st.session_state["ui_lang"]
