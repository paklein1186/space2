-- Besoins mis en avant : sous-ensemble des besoins déclarés à l'entretien
-- ("Rendre visibles vos besoins actuels", champ types_soutien_souhaites)
-- que le steward ou un admin choisit de mettre en avant publiquement sur
-- la fiche du lieu (Annuaire) et dans le Portfolio — distinct de la liste
-- brute des besoins déclarés, qui peut être longue et non filtrée pour
-- l'affichage public.
alter table lieu_derive add column if not exists besoins_mis_en_avant jsonb not null default '[]'::jsonb;
