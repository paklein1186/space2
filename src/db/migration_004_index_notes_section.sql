-- Index sur notes_libres.section_id : le % de complétion/bonnes pratiques
-- introduit une lecture régulière par ce champ (get_notes_by_section_id,
-- utilisé par le dataset "bonnes_pratiques" de la Bibliothèque pour
-- retrouver les notes taguées "bonne_pratique" tous lieux confondus), sur
-- le même modèle que idx_notes_libres_tiers_lieu déjà en place.
create index if not exists idx_notes_libres_section on notes_libres(section_id);
