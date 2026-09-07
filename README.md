# Lieux hybrides et territoires — agent de collecte + assistant RAG

Plateforme pour le secteur des tiers-lieux : un agent conversationnel mène des
entretiens à branchement conditionnel avec les porteurs, équipes et
partenaires de tiers-lieux (France, Belgique, extensible à d'autres pays), un
pipeline d'enrichissement produit une synthèse + un profil sémantique par
lieu, et un assistant RAG permet d'interroger l'ensemble (données collectées,
synthèses, documents déposés) en langage naturel — architecture
"database first, LLM second" : le LLM ne devient jamais la base de données.

Voir le plan détaillé (audit + architecture cible) : `~/.claude/plans/humming-singing-bachman.md`.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Remplir `.env` :
- `ANTHROPIC_API_KEY` — clé API Anthropic (https://console.anthropic.com/).
- `VOYAGE_API_KEY` — clé Voyage AI (https://dashboard.voyageai.com/), pour les
  embeddings du RAG. **Sans moyen de paiement enregistré sur le compte
  Voyage, le débit est plafonné à 3 requêtes/minute** — largement insuffisant
  pour un usage interactif réel (chaque question RAG peut déclencher un
  appel). Le code réessaie automatiquement avec un délai croissant, mais
  ajouter un moyen de paiement (les tokens gratuits restent acquis) est
  recommandé avant toute mise en usage réel.
- `SUPABASE_URL` / `SUPABASE_KEY` (clé **publique**, `sb_publishable_...`) —
  optionnels. Sans eux, l'application utilise une base SQLite locale
  (`data/local_dev.sqlite3`). Pour la production : créez un projet sur
  https://supabase.com, puis dans **SQL Editor**, exécutez le contenu de
  `src/db/schema.sql`.
- `SUPABASE_SERVICE_KEY` (clé **service_role**, secrète — Project Settings →
  API) — nécessaire uniquement pour les scripts de fond exécutés hors d'une
  session utilisateur (import, enrichissement en batch, migration). Cette
  clé contourne RLS : ne jamais l'utiliser côté app interactive, seulement
  dans ces scripts (`get_admin_store()`). L'app Streamlit, elle, utilise
  toujours la clé publique + la session de l'utilisateur connecté, pour que
  RLS s'applique correctement.

## Tester sans clé API

```bash
python3 -m tests.test_schema_resolver
python3 -m tests.test_collecte_tools
python3 -m tests.test_rag_tools
python3 -m tests.test_caching
python3 -m tests.test_usage_and_hash
```

Valident le branchement conditionnel, la localisation FR/BE, le filtrage par
rôle, la reprise exacte d'une session interrompue, le prompt caching et le
calcul des coûts — sans appeler l'API Claude.

## Lancer un entretien en CLI

```bash
python -m src.agent.collecte_agent --lieu "Le Hangar" --pays France --role fondateur
```

La session reprend automatiquement où elle s'est arrêtée si vous relancez la
même commande.

## Lancer l'application web

```bash
streamlit run src/app.py
```

Trois onglets : **Entretien**, **Assistant RAG** (nécessite `VOYAGE_API_KEY`
+ des lieux enrichis ou un index construit), **Annuaire** (fiches de synthèse
multi-répondants + carte + bouton "Finaliser ce lieu" pour déclencher
l'enrichissement).

## Importer des questionnaires déjà remplis (docx/pdf)

Pour des documents reçus hors de l'agent (ex. anciens questionnaires de
capitalisation), un import structuré mappe le texte libre sur le schéma via
un appel LLM par document (jamais d'invention : seuls les champs
explicitement présents dans le texte sont renseignés) :

```bash
python -m src.ingest.import_questionnaire fichier1.docx fichier2.pdf ...
```

Les formats `.doc` binaires (pré-2007) ne sont pas supportés directement —
convertissez d'abord en texte, ex. sur macOS : `textutil -convert txt fichier.doc -output fichier.txt`.

## Enrichissement (synthèse + profil sémantique par lieu)

Un seul appel LLM (Haiku 4.5) par lieu — jamais par réponse — lit toutes les
réponses de tous les contributeurs et produit une synthèse structurée
(activités, publics, gouvernance, modèle économique...) et un texte de
"profil sémantique" embeddé une seule fois par lieu (recherche du type
"quels lieux travaillent sur...", "lieux à l'approche comparable..."). Donnée
strictement séparée des réponses brutes (table `lieu_derive`), jamais
recalculée si les réponses n'ont pas changé (hash de contenu) :

```bash
python -m src.agent.enrich_places          # tous les lieux, seulement ce qui a changé
python -m src.agent.enrich_places --force  # force le recalcul de tout
```

Déclenchable aussi depuis l'onglet Annuaire ("Finaliser ce lieu" / "Ré-enrichir").

## Migration SQLite → Supabase

Une fois le schéma Supabase créé et `SUPABASE_SERVICE_KEY` renseigné :

```bash
python -m src.db.migrate_sqlite_to_supabase
```

Copie tous les lieux/réponses/notes/données dérivées de la base locale vers
Supabase (idempotent, ré-exécutable). Les lieux importés via un
`owner_user_id` libre (ex. `import-drive`) sont rattachés à un compte de
service créé automatiquement dans Supabase Auth.

## Suivi des coûts

Chaque appel LLM (entretien, enrichissement, question RAG, import) est
journalisé dans la table `llm_calls` (modèle, tokens, coût estimé, y compris
la distinction lecture/écriture de cache). Voir `src/agent/usage.py` pour les
tarifs utilisés.

## Structure du projet

```
src/
  questionnaire/   # schéma du questionnaire (modules > sections > champs) + résolveur de conditions
  db/               # accès aux données (Supabase en prod, SQLite en local), schema.sql, migration
  agent/            # tools + boucles des agents (collecte, RAG), embeddings/vectorstore,
                     # enrichissement, caching, suivi des coûts
  ingest/           # pipeline d'indexation RAG (extraction, chunking, datasets, géodonnées) + import
  annuaire.py        # vue agrégée en lecture seule (fiches lieux + carte + déclencheur d'enrichissement)
  app.py             # interface Streamlit (3 onglets)
tests/              # scripts de vérification sans dépendance aux API externes
```

## État d'avancement

- ✅ Schéma du questionnaire, résolveur de conditions, localisation FR/BE, filtrage par rôle
- ✅ Base de données (SQLite local / Supabase avec RLS), sessions interruptibles et reprenables
- ✅ Agent de collecte (CLI + Streamlit), prompt caching, suivi des coûts
- ✅ Pipeline d'enrichissement (synthèse + profil sémantique, 1 appel/lieu) et embedding dédié
- ✅ Assistant RAG (recherche sémantique multi-niveaux + requêtes structurées) et annuaire/carte
- ✅ Import de questionnaires déjà remplis vers le schéma structuré
- ✅ Validé en conditions réelles : 22 tiers-lieux belges importés, enrichis, embeddés et migrés
  vers Supabase ; entretien, RAG sémantique et RAG structuré testés en direct avec Claude
- ⚠️ Connu : le palier gratuit Voyage AI sans moyen de paiement limite à 3 req/min — voir section
  Installation
