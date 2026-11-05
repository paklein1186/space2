-- Identifiant court et lisible pour un lien direct vers une campagne
-- prioritaire (ex. flyer/QR code imprimé : /entretien?campagne=ka122 plutôt
-- que l'uuid) — voir app.py::_campagne_depuis_url. Optionnel et pas unique
-- en base (l'admin peut laisser vide ou se tromper sans bloquer la
-- sauvegarde) : la résolution d'URL retombe sur l'uuid si aucune campagne
-- active ne porte ce code, ou si deux en partagent un par erreur.
alter table campagnes_prioritaires add column if not exists code text;
