"""Rattrapage de commune / code_postal pour les lieux existants (à lancer une
fois après migration_010, puis au besoin) :

    python3 -m src.geocode_backfill [--force]

Un lieu qui a déjà des coordonnées est traité par reverse-géocodage de ce
point (commune cohérente avec la position servie) ; sinon, par géocodage (avec
repli progressif sur une version plus générale de l'adresse, voir
`geocoding.geocoder_adresse_avec_repli`) de sa réponse « adresse », ou à
défaut de sa commune déjà connue (lieu créé depuis un candidat d'extraction :
jamais de réponse « adresse », seulement une commune posée directement sur la
fiche — voir `extraction_lieux.creer_lieu_depuis_candidat`) — l'un ou l'autre
pose aussi les coordonnées. Une requête par lieu, au plus une par seconde
(politique d'usage de Nominatim).

Pour un diagnostic en lecture seule (quels lieux manquent de coordonnées, et
lesquels ont au moins une adresse à géocoder) : python3 -m src.geocode_diagnostic
"""

from __future__ import annotations

import sys
import time

from .geocoding import commune_cp_depuis_coordonnees, geocoder_adresse_avec_repli, geocoder_adresse_detail

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
        deja_complet = (lieu.latitude is not None and lieu.longitude is not None
                        and lieu.commune and lieu.code_postal)
        if deja_complet and not force:
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
            requete = adresse or lieu.commune or ""
            detail = geocoder_adresse_avec_repli(requete, lieu.pays) if requete else None
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
