-- Historique des conversations de l'assistant Bibliothèque (RAG), par
-- utilisateur — pour pouvoir rouvrir une discussion précédente plutôt que de
-- repartir de zéro à chaque visite. Table à part de sessions_entretien
-- (celle-ci suit la progression du QUESTIONNAIRE pour un contributeur/lieu
-- donné ; ceci est un historique de chat libre, par utilisateur, jamais
-- rattaché à un lieu précis puisque la Bibliothèque interroge l'ensemble du
-- corpus).
--
-- À exécuter une fois dans l'éditeur SQL Supabase, comme les migrations
-- précédentes (migration_002_...).

create table if not exists conversations_bibliotheque (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    titre text,
    messages jsonb not null default '[]'::jsonb,
    cree_le timestamptz not null default now(),
    maj_le timestamptz not null default now()
);

create index if not exists idx_conversations_bibliotheque_user
    on conversations_bibliotheque(user_id, maj_le desc);

alter table conversations_bibliotheque enable row level security;

create policy "chacun gere ses propres conversations" on conversations_bibliotheque
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
