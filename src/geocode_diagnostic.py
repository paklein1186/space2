"""Diagnostic des lieux sans point sur la carte (lat/lon manquantes) : pour
chacun, affiche l'adresse publique connue (réponse « adresse ») le cas
échéant — pour voir d'un coup d'œil lesquels ont de quoi être géocodés (depuis
la fiche admin, bouton « Géocoder ce lieu maintenant », voir
`geocoding.geocoder_lieu_admin`) et lesquels n'ont tout simplement aucune
adresse enregistrée (rien à géocoder tant que personne ne la renseigne).
Lecture seule, aucune requête réseau.

Usage :
    python3 -m src.geocode_diagnostic
"""

from __future__ import annotations


def main() -> None:
    from dotenv import load_dotenv

    from .db.factory import get_admin_store

    load_dotenv()
    store = get_admin_store()
    sans_coordonnees = [l for l in store.list_tiers_lieux() if l.latitude is None or l.longitude is None]
    if not sans_coordonnees:
        print("Tous les lieux ont déjà un point sur la carte.")
        return

    adresses = store.get_public_answers_batch([l.id for l in sans_coordonnees])
    avec_adresse = sans_adresse = 0
    print(f"{len(sans_coordonnees)} lieu(x) sans point sur la carte :\n")
    for lieu in sans_coordonnees:
        adresse = ((adresses.get(lieu.id) or {}).get("adresse") or "").strip()
        pays = lieu.pays or "?"
        if adresse:
            avec_adresse += 1
            print(f"[adresse connue] {lieu.nom} ({pays}) : « {adresse} »")
        else:
            sans_adresse += 1
            print(f"[AUCUNE adresse] {lieu.nom} ({pays})")
    print(f"\n{avec_adresse} à géocoder (adresse connue), {sans_adresse} sans adresse du tout.")


if __name__ == "__main__":
    main()
