"""Rattrapage de commune / code_postal pour les lieux existants (à lancer une
fois après migration_010, puis au besoin) :

    python3 -m src.geocode_backfill [--force]

Un lieu qui a déjà des coordonnées est traité par reverse-géocodage de ce
point (commune cohérente avec la position servie) ; sinon, par géocodage de sa
réponse « adresse » (qui pose aussi ses coordonnées). Une requête par lieu, au
plus une par seconde (politique d'usage de Nominatim)."""

from __future__ import annotations

import sys
import time

from .geocoding import commune_cp_depuis_coordonnees, geocoder_adresse_detail

PAUSE_S = 1.1


def main(force: bool = False) -> None:
    from dotenv import load_dotenv

    from .db.factory import get_admin_store

    load_dotenv()
    store = get_admin_store()
    lieux = store.list_tiers_lieux()
    adresses = store.get_public_answers_batch([l.id for l in lieux])
    faits = echecs = 0
    for lieu in lieux:
        if (lieu.commune or lieu.code_postal) and not force:
            continue
        maj = {}
        adresse = (adresses.get(lieu.id) or {}).get("adresse") or ""
        if lieu.latitude is not None and lieu.longitude is not None:
            infos = commune_cp_depuis_coordonnees(lieu.latitude, lieu.longitude, adresse)
            maj = {k: v for k, v in (infos or {}).items() if v}
            time.sleep(PAUSE_S)
            if not maj.get("code_postal") and adresse:
                # Le reverse n'a pas toujours de code postal : on le prend du
                # géocodage direct de l'adresse, sans toucher aux coordonnées.
                detail = geocoder_adresse_detail(adresse, lieu.pays)
                if detail and detail.get("code_postal"):
                    maj["code_postal"] = detail["code_postal"]
        else:
            detail = geocoder_adresse_detail(adresse, lieu.pays)
            if detail:
                maj = {k: v for k, v in detail.items() if v is not None}
        time.sleep(PAUSE_S)
        if maj:
            store.update_tiers_lieu(lieu.id, **maj)
            faits += 1
            print(f"[ok]   {lieu.nom} -> {maj.get('commune')} {maj.get('code_postal')}")
        else:
            echecs += 1
            print(f"[vide] {lieu.nom}")
    print(f"{faits} lieu(x) mis à jour, {echecs} sans résultat.")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
