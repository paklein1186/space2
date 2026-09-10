-- Migration incrémentale pour une base Supabase déjà déployée avec schema.sql
-- (le rôle "steward" et les colonnes lien_externe/photo_url ont été ajoutés
-- après coup — voir schema.sql qui les inclut déjà pour une installation neuve).
-- À exécuter une fois dans l'éditeur SQL Supabase.

alter table contributeurs drop constraint if exists contributeurs_role_check;
alter table contributeurs add constraint contributeurs_role_check
    check (role in ('fondateur', 'equipe', 'partenaire', 'usager', 'steward', 'autre'));

alter table lieu_derive add column if not exists sources jsonb;
alter table lieu_derive add column if not exists lien_externe text;
alter table lieu_derive add column if not exists photo_url text;
