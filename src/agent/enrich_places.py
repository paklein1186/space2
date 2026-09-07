"""Batch : (ré)enrichit tous les lieux dont les réponses ont changé depuis le
dernier enrichissement (ou tous si --force).

Usage : python -m src.agent.enrich_places [--force]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.agent.enrichissement import enrich_lieu
from src.db.factory import get_admin_store


def main():
    load_dotenv()
    force = "--force" in sys.argv
    store = get_admin_store()
    lieux = store.list_tiers_lieux()
    print(f"{len(lieux)} lieu(x) à traiter (force={force})")

    for lieu in lieux:
        try:
            result, updated = enrich_lieu(store, lieu.id, force=force, nom_lieu=lieu.nom)
            if result is None:
                print(f"  {lieu.nom}: aucune donnée à enrichir")
            elif not updated:
                print(f"  {lieu.nom}: inchangé, pas de ré-enrichissement")
            else:
                print(f"  {lieu.nom}: enrichi ({result.model})")
        except Exception as exc:
            print(f"  {lieu.nom}: ERREUR — {exc}")


if __name__ == "__main__":
    main()
