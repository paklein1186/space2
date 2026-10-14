-- Accord explicite donné pendant l'entretien (voir le tool
-- proposer_guilde_ctg) à ce qu'une guilde Changethegame soit créée pour ce
-- lieu — contourne le seuil de complétion de flux_lieux() au même titre
-- qu'une validation humaine ou une campagne prioritaire terminée.
alter table tiers_lieux add column if not exists ctg_opt_in boolean not null default false;
