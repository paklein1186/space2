-- Lie chaque appel LLM journalisé (llm_calls) à l'utilisateur qui l'a
-- déclenché (auth.users.id), en plus du lieu concerné — pour afficher
-- l'usage/coût par utilisateur (Administration > Usage & coûts) plutôt que
-- seulement par lieu. NULL pour les appels sans utilisateur attribuable
-- (imports en masse, crawl, enrichissement automatique en tâche de fond).
alter table llm_calls add column if not exists user_id uuid references auth.users(id) on delete set null;

-- La policy d'origine ("lecture publique du suivi des coûts") autorisait
-- N'IMPORTE QUEL utilisateur authentifié à lire TOUTES les lignes de
-- llm_calls — sans conséquence tant que la table ne portait qu'un
-- tiers_lieu_id, mais user_id y identifie maintenant une personne précise :
-- resserré à la lecture par un admin uniquement (même page Administration
-- qui s'en sert déjà via le store service_role, donc sans effet sur elle).
drop policy if exists "lecture publique du suivi des couts" on llm_calls;
create policy "admin lit le suivi des couts" on llm_calls
    for select using (exists (select 1 from admins where user_id = auth.uid()));
