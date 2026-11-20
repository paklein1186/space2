-- Connexion unique depuis troistiers.space : tickets d'entrée à usage unique.
--
-- Le site demande un ticket à l'API (POST /sso/ticket) en transmettant le jeton
-- de connexion ChangeTheGame de la personne ; l'API vérifie elle-même ce jeton
-- auprès de ChangeTheGame, puis crée un ticket valable 2 minutes. Le navigateur
-- arrive sur l'entretien avec ?ticket=... ; l'app l'échange (une seule fois)
-- contre une session Space2 pour le même email.
--
-- Seul le hash du ticket est stocké. RLS activé SANS policy : seule la clé
-- service_role (API et app côté serveur) y accède.
create table if not exists sso_tickets (
    hash text primary key,
    email text not null,
    ctg_user_id text,
    expire_le timestamptz not null,
    utilise_le timestamptz,
    cree_le timestamptz not null default now()
);
create index if not exists sso_tickets_expire_idx on sso_tickets (expire_le);
alter table sso_tickets enable row level security;
