-- Entretiens menés depuis troistiers.space (API /entretien) : une ligne par conversation,
-- pour pouvoir la reprendre plus tard. `messages` = l'historique complet de l'agent de collecte
-- (format Anthropic, déjà en JSON) ; `historique` = les seuls échanges visibles (répondant / agent).
-- RLS activé SANS policy : seule la clé service_role (API) y accède, après vérification
-- de l'identité ChangeTheGame et du propriétaire de la conversation.
create table if not exists entretiens_site (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    email text not null,
    tiers_lieu_id text not null,
    contributeur_id text not null,
    role text not null,
    mode text not null default 'histoire',
    campagne_id text,
    messages jsonb not null default '[]'::jsonb,
    historique jsonb not null default '[]'::jsonb,
    cree_le timestamptz not null default now(),
    maj_le timestamptz not null default now()
);
create index if not exists entretiens_site_user_idx on entretiens_site (user_id, maj_le desc);
alter table entretiens_site enable row level security;
