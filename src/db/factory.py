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
    """Store pour les scripts de fond (import, enrichissement, migration) qui
    écrivent au nom du système plutôt que d'un utilisateur connecté. Sur
    Supabase, ces écritures doivent contourner RLS (aucune session utilisateur
    dans un script CLI) — nécessite `SUPABASE_SERVICE_KEY` (clé service_role,
    jamais utilisée côté app interactive). À défaut, retombe sur SQLite local."""
    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if url and service_key:
        from .supabase_store import SupabaseStore

        return SupabaseStore(url, service_key)

    if url and os.environ.get("SUPABASE_KEY") and not service_key:
        import warnings

        warnings.warn(
            "SUPABASE_URL est configuré mais SUPABASE_SERVICE_KEY est absent : "
            "les scripts de fond ne peuvent pas écrire sur Supabase à cause de "
            "RLS (elle exige un utilisateur authentifié, absent dans un script "
            "CLI). Utilisation de SQLite local à la place — ajoutez "
            "SUPABASE_SERVICE_KEY dans .env pour basculer ces scripts sur Supabase."
        )

    from .sqlite_store import SqliteStore

    return SqliteStore()
