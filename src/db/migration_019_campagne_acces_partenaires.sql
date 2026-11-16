-- Accès partenaires à une campagne prioritaire : une ligne par (campagne,
-- email) autorisé à consulter la page /?partenaire=<code> (questions,
-- répondants et données collectées de CETTE campagne uniquement, sans menu).
--
-- Table séparée plutôt qu'une colonne de campagnes_prioritaires : celle-ci
-- est en lecture publique (policy "lecture publique campagnes"), ce qui
-- exposerait la liste des emails partenaires à n'importe qui. Ici, RLS
-- activé SANS aucune policy : seule la clé service_role (store admin côté
-- app, après vérification en Python de l'email connecté) y accède.
create table if not exists campagne_acces_partenaires (
    campagne_id uuid not null references campagnes_prioritaires(id) on delete cascade,
    email text not null,
    cree_le timestamptz not null default now(),
    primary key (campagne_id, email)
);
create index if not exists campagne_acces_partenaires_email_idx on campagne_acces_partenaires (email);
alter table campagne_acces_partenaires enable row level security;
