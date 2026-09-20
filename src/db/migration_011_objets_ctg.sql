-- Objets Changethegame (guildes, quêtes, entreprises, posts...) reçus via
-- PUT /ctg/objects. Les lieux (kind "lieu", is_place) créent en plus un lieu
-- Space2 ; tous les autres ne servent que de connaissance (dataset
-- organisations_ctg + recherche sémantique), jamais galerie/portfolio.
create table if not exists objets_ctg (
    ctg_id text primary key,               -- guild:/quest:/company:/post: + uuid
    kind text not null check (kind in ('lieu', 'organisation', 'quete', 'entite', 'post')),
    is_place boolean not null default false,
    name text not null,
    description text,
    url text,
    website_url text,
    topics jsonb not null default '[]'::jsonb,
    territories jsonb not null default '[]'::jsonb,
    commune text,
    latitude double precision,
    longitude double precision,
    parent_ctg_id text,
    status text,
    updated_at timestamptz,                -- date côté ctg
    tiers_lieu_id uuid references tiers_lieux(id) on delete set null,
    recu_le timestamptz not null default now()
);
alter table objets_ctg enable row level security;
create policy "lecture objets ctg (connectes)" on objets_ctg
    for select using (auth.role() = 'authenticated');
