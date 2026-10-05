-- Message affiché une fois (côté agent d'entretien) quand toutes les
-- questions d'une campagne prioritaire sont répondues — voir
-- CollecteToolHandler._priority_section. None/absent = message générique de
-- repli, pas de texte propre à cette campagne.
alter table campagnes_prioritaires add column if not exists message_cloture text;
