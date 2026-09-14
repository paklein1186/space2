"""Choisit le backend de stockage : Supabase si configuré, sinon SQLite local
(pratique pour développer/tester l'agent sans compte Supabase).

Important pour Supabase : si l'appelant a déjà un client authentifié (ex. une
session Streamlit après connexion par OTP), il DOIT le passer via
`client=...` pour que les policies RLS (`auth.uid()`/`auth.role()`) voient le
bon utilisateur — un client recréé séparément repartirait anonyme."""

from __future__ import annotations

import os

from .store import Store

_store_singleton: Store | None = None


def get_store(client=None) -> Store:
    global _store_singleton
    if client is None and _store_singleton is not None:
        return _store_singleton

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        from .supabase_store import SupabaseStore

        store = SupabaseStore(url, key, client=client)
    else:
        from .sqlite_store import SqliteStore

        store = SqliteStore()

    if client is None:
        _store_singleton = store
    return store


def get_admin_store() -> Store:
    """Store pour les scripts de fond (import, enrichissement, migration) et
    pour les actions d'administration de l'app interactive (modération,
    curation Portfolio...) qui doivent contourner RLS — nécessite
    `SUPABASE_SERVICE_KEY` (clé service_role).

    Si `SUPABASE_URL` est configuré mais que la clé service_role est absente,
    on lève une erreur explicite plutôt que de retomber silencieusement sur
    SQLite local : un tel repli silencieux fait croire qu'une écriture admin
    a réussi (le formulaire se ferme sans erreur) alors qu'elle a atterri
    dans une base SQLite locale que le reste de l'app ne relit jamais — c'est
    exactement le bug rencontré en production avec la case à cocher Portfolio,
    invisible jusqu'à ce qu'on compare les deux bases directement."""
    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if url and service_key:
        from .supabase_store import SupabaseStore

        return SupabaseStore(url, service_key)

    if url and os.environ.get("SUPABASE_KEY") and not service_key:
        raise RuntimeError(
            "SUPABASE_URL est configuré mais SUPABASE_SERVICE_KEY est absent : "
            "impossible d'effectuer cette action admin sur Supabase (RLS exige "
            "soit un utilisateur authentifié admin, soit la clé service_role). "
            "Ajoutez SUPABASE_SERVICE_KEY dans les secrets (.env en local, "
            "secrets de l'app en production) — voir README.md."
        )

    from .sqlite_store import SqliteStore

    return SqliteStore()
