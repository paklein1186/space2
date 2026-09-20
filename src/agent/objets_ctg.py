"""Objets Changethegame « de connaissance » (organisations, quêtes, entités,
posts — tout sauf les lieux, qui deviennent de vrais lieux Space2) : jeu de
données `organisations_ctg` et texte à indexer pour la recherche sémantique.
Module sans dépendance Streamlit/Chroma/Voyage."""

from __future__ import annotations

import pandas as pd

from ..db.store import Store

COLONNES_ORGANISATIONS = ["ctg_id", "kind", "nom", "description", "url", "website_url", "topics", "territories",
                          "commune", "latitude", "longitude", "parent_ctg_id", "parent_nom", "status",
                          "updated_at"]
TEXTE_MAX = 1500


def est_connaissance(objet: dict) -> bool:
    """Objet à exposer comme connaissance : tout sauf un lieu effectivement
    devenu lieu Space2 (kind "lieu", is_place et tiers_lieu_id renseigné) — un
    lieu rejeté à la création reste donc consultable ici."""
    return not (objet["kind"] == "lieu" and objet["is_place"] and objet.get("tiers_lieu_id"))


def organisations_ctg_dataframe(store: Store) -> pd.DataFrame:
    objets = store.list_objets_ctg()
    noms = {o["ctg_id"]: o["name"] for o in objets}
    lignes = [{"ctg_id": o["ctg_id"], "kind": o["kind"], "nom": o["name"], "description": o["description"],
               "url": o["url"], "website_url": o["website_url"], "topics": o["topics"],
               "territories": o["territories"], "commune": o["commune"], "latitude": o["latitude"],
               "longitude": o["longitude"], "parent_ctg_id": o["parent_ctg_id"],
               "parent_nom": noms.get(o["parent_ctg_id"]), "status": o["status"],
               "updated_at": o["updated_at"]}
              for o in objets if est_connaissance(o)]
    return pd.DataFrame(lignes, columns=COLONNES_ORGANISATIONS)


def texte_objet(objet: dict) -> str:
    """Texte à embedder pour la recherche sémantique d'un objet."""
    morceaux = [f"{objet['name']} ({objet['kind']})", objet.get("description") or "",
                "Thèmes : " + ", ".join(objet["topics"]) if objet.get("topics") else "",
                "Territoires : " + ", ".join(objet["territories"]) if objet.get("territories") else "",
                f"Commune : {objet['commune']}" if objet.get("commune") else ""]
    return "\n".join(m for m in morceaux if m)[:TEXTE_MAX]
