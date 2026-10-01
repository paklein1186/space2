"""Diagnostic des lieux sans point sur la carte (lat/lon manquantes) : pour
chacun, affiche l'adresse publique connue (réponse « adresse ») le cas
échéant, sinon la commune déjà posée directement sur la fiche (lieu créé
depuis un candidat d'extraction — voir `extraction_lieux.creer_lieu_depuis_
candidat` — qui n'a jamais de réponse « adresse », seulement une commune) —
pour voir d'un coup d'œil lesquels ont de quoi être géocodés (automatiquement
à l'ouverture de la fiche admin, voir `geocoding.geocoder_lieu_admin`) et
lesquels n'ont vraiment rien du tout (ni adresse, ni commune — rien à
géocoder tant que personne ne renseigne l'un des deux). Lecture seule, aucune
requête réseau.

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
    avec_adresse = avec_commune_seule = sans_rien = 0
    print(f"{len(sans_coordonnees)} lieu(x) sans point sur la carte :\n")
    for lieu in sans_coordonnees:
        adresse = ((adresses.get(lieu.id) or {}).get("adresse") or "").strip()
        pays = lieu.pays or "?"
        if adresse:
            avec_adresse += 1
            print(f"[adresse connue]   {lieu.nom} ({pays}) : « {adresse} »")
        elif lieu.commune:
            avec_commune_seule += 1
            print(f"[commune seule]    {lieu.nom} ({pays}) : « {lieu.commune} »")
        else:
            sans_rien += 1
            print(f"[AUCUNE info géo]  {lieu.nom} ({pays})")
    print(f"\n{avec_adresse} avec adresse, {avec_commune_seule} avec seulement une commune connue "
          f"(les deux rattrapables automatiquement), {sans_rien} sans la moindre info géographique.")


if __name__ == "__main__":
    main()
