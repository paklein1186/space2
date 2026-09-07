"""Vérification manuelle du schéma + resolver (étape (a) du plan).

Lancer avec: python -m tests.test_schema_resolver depuis la racine du projet.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.questionnaire.resolver import (
    country_code_for,
    field_is_active,
    resolve_section_fields,
    section_is_active,
)
from src.questionnaire.schema import (
    Role,
    get_section,
)


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    # --- Localisation : un champ FR-specifique doit disparaitre pour un lieu belge
    section_rh = get_section("socle", "ressources_humaines")
    answers_be = {"statut_juridique": "ASBL"}
    fields_be = resolve_section_fields(section_rh, answers_be, Role.FONDATEUR, country_code_for("Belgique"))
    field_organisme = next(rf for rf in fields_be if rf.id == "organisme_formation_lien")
    check("Options BE ne contiennent pas 'Pôle emploi / France Travail'",
          "Pôle emploi / France Travail" not in field_organisme.options)
    check("Options BE contiennent le Forem",
          any("Forem" in opt for opt in field_organisme.options))

    fields_fr = resolve_section_fields(section_rh, answers_be, Role.FONDATEUR, country_code_for("France"))
    field_organisme_fr = next(rf for rf in fields_fr if rf.id == "organisme_formation_lien")
    check("Options FR contiennent Pôle emploi / France Travail",
          any("Pôle emploi" in opt for opt in field_organisme_fr.options))

    # --- Rôle : les champs RH internes ne doivent pas être visibles pour un partenaire externe
    fields_partenaire = resolve_section_fields(section_rh, {}, Role.PARTENAIRE, "FR")
    check("Aucun champ RH interne visible pour un partenaire externe", len(fields_partenaire) == 0)

    fields_fondateur = resolve_section_fields(section_rh, {}, Role.FONDATEUR, "FR")
    check("Les champs RH sont visibles pour un fondateur", len(fields_fondateur) > 0)

    # --- Conditions : section "activités alimentaires" seulement si coché
    section_alim = get_section("socle", "activites_alimentaires")
    check("Section alimentaire inactive sans l'activité correspondante",
          not section_is_active(section_alim, {"activites_principales": ["Coworking / bureaux partagés"]}))
    check("Section alimentaire active si l'activité est cochée",
          section_is_active(section_alim, {"activites_principales": [
              "Activités liées à l'alimentation (production, transformation, distribution)"]}))

    # --- Conditions : milieu rural vs urbain
    from src.questionnaire.schema import get_section as gs
    section_rural = gs("socle", "mobilite_rurale")
    section_urbain = gs("socle", "pression_fonciere_urbaine")
    check("Section rurale active si milieu=Rural", section_is_active(section_rural, {"milieu": "Rural"}))
    check("Section urbaine inactive si milieu=Rural", not section_is_active(section_urbain, {"milieu": "Rural"}))

    # --- Conditions : gouvernance coopérative
    section_gouv = gs("socle", "gouvernance")
    fields_gouv_scic = resolve_section_fields(section_gouv, {"statut_juridique": "SCIC"}, Role.FONDATEUR, "FR")
    check("Champ répartition sociétariat visible si statut SCIC",
          any(rf.id == "repartition_societariat" for rf in fields_gouv_scic))
    fields_gouv_asso = resolve_section_fields(section_gouv, {"statut_juridique": "Association loi 1901"}, Role.FONDATEUR, "FR")
    check("Champ répartition sociétariat absent si association",
          not any(rf.id == "repartition_societariat" for rf in fields_gouv_asso))

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
