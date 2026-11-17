"""Mise en forme des réponses pour les exports tableur des campagnes."""

from __future__ import annotations

from typing import Optional

from .schema import FieldType, field_label, get_field


def _toutes_les_options(field) -> list:
    """Options d'un champ, toutes variantes de pays confondues, sans doublon."""
    if isinstance(field.options, list):
        return list(field.options)
    vues, options = set(), []
    for liste in (field.options or {}).values():
        for o in liste:
            if o not in vues:
                vues.add(o)
                options.append(o)
    return options


def colonnes_par_option(champ_id: str, valeur) -> Optional[dict]:
    """Une réponse à choix multiple éclatée en une colonne par option (« x »
    si cochée), pour l'analyse en tableur — demandé explicitement par le
    questionnaire gestionnaires (« chaque valeur dans une colonne séparée »).
    Les valeurs hors liste (un « Autre » précisé) vont dans une colonne
    « précisions ». None si le champ n'est pas un choix multiple."""
    field = get_field(champ_id)
    if field is None or field.type != FieldType.MULTI_CHOICE or not field.options:
        return None
    options = _toutes_les_options(field)
    cochees = valeur if isinstance(valeur, list) else ([] if valeur in (None, "") else [valeur])
    label = field_label(champ_id)
    colonnes = {f"{label} — {o}": ("x" if o in cochees else "") for o in options}
    autres = [str(v) for v in cochees if v not in options]
    colonnes[f"{label} — précisions"] = ", ".join(autres)
    return colonnes
